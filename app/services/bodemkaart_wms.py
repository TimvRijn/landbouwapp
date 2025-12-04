# app/services/bodemkaart_wms.py
from __future__ import annotations

import math
import re
import logging
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

"""
PDOK BRO Bodemkaart – robuuste WMS GetFeatureInfo client

- Detecteert automatisch de juiste (queryable) bodemlaag via GetCapabilities.
- Voert GetFeatureInfo uit met voorkeur voor JSON, met HTML/XML fallback.
- Extraheert properties en **normaliseert kolomnamen** zodat je in je app
  altijd dezelfde sleutels hebt.
- Levert `soil_text` op basis van de beste kolom (met prioriteit op de
  PDOK-namen die je screenshot toont).

Publieke helpers (backwards compatible):
- query_soil_at_point(lat, lon) -> {"soil_text": str|None, "raw": {...}}
- pick_bodem_layer_name() -> str|None
"""

# ---------------------------- Config ----------------------------

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

WMS_BASE = "https://service.pdok.nl/bzk/bro-bodemkaart/wms/v1_0"
WMS_VERSION = "1.3.0"
DEFAULT_TIMEOUT = 15
MAX_RETRIES = 3
BACKOFF_FACTOR = 0.4

# Niet té strikt houden, maar netjes voor waarschuwingen:
NL_LAT_MIN, NL_LAT_MAX = 50.0, 54.5
NL_LON_MIN, NL_LON_MAX = 2.8, 8.1

# PDOK accepteert JSON voor GetFeatureInfo; we proberen dit eerst.
PREFERRED_INFO_FORMATS = [
    "application/json",
    "application/vnd.ogc.gml",
    "text/xml",
    "text/html",
]

# Bekende PDOK-sleutels uit jouw screenshot + generieke varianten:
# → deze normaliseren we naar consistente namen.
NORMALIZE_KEY_MAP = {
    # Uit jouw screenshot (PDOK BRO Bodemkaart)
    "first_soilname": "soilname_first",
    "normal_soilprofile_name": "soilprofile_name",
    "normal_soilprofile_code": "soilprofile_code",
    "soilcode": "soilcode",
    "soilslope": "soilslope",
    "maparea_id": "maparea_id",
    "maparea_collection": "maparea_collection",

    # Mogelijke alternatieven/varianten
    "bodemtype": "bodemtype",
    "bodem_type": "bodemtype",
    "grondsoort": "grondsoort",
    "grond_soort": "grondsoort",
    "legenda": "legenda",
    "legend": "legenda",
    "omschrijving": "omschrijving",
    "beschrijving": "omschrijving",
    "naam": "naam",
    "name": "naam",
    "klasse": "klasse",
    "class": "klasse",
    "subtype": "subtype",
    "categorie": "categorie",
    "category": "categorie",
    "code": "code",
    "bodemcode": "code",
}

# Waar halen we liefst de 'mooie' bodemnaam uit?
SOIL_NAME_PRIORITY = [
    "soilname_first",       # first_soilname
    "soilprofile_name",     # normal_soilprofile_name
    "grondsoort",
    "bodemtype",
    "legenda",
    "omschrijving",
    "naam",
    "klasse",
    "subtype",
    "categorie",
    "soilcode",             # PDOK-code (minder mooi, maar bruikbaar)
    "soilprofile_code",     # idem
    "code",
]

WMS_NS = {"wms": "http://www.opengis.net/wms"}


# ---------------------------- Datatypes ----------------------------

@dataclass
class SoilQueryResult:
    success: bool
    soil_text: Optional[str]
    layer_name: Optional[str]
    coordinates: Tuple[float, float]
    info_format_used: Optional[str] = None
    properties_raw: Optional[Dict[str, Any]] = None  # originele keys van PDOK
    properties: Optional[Dict[str, Any]] = None      # genormaliseerde keys
    feature: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class BodemkaartWMSError(Exception):
    pass


class CoordinateValidationError(BodemkaartWMSError):
    pass


class LayerDiscoveryError(BodemkaartWMSError):
    pass


# ---------------------------- Client ----------------------------

class BodemkaartWMSClient:
    """
    Robuuste PDOK Bodemkaart WMS-client met normalisatie van kolomnamen.
    """

    def __init__(self, timeout: int = DEFAULT_TIMEOUT, buffer_m: float = 40.0):
        self.timeout = timeout
        self.buffer_m = buffer_m
        self._layer_cache: Optional[str] = None
        self._cache_lock = Lock()
        self._session = self._build_session()

    @staticmethod
    def _build_session() -> requests.Session:
        s = requests.Session()
        retry = Retry(
            total=MAX_RETRIES,
            connect=MAX_RETRIES,
            read=MAX_RETRIES,
            backoff_factor=BACKOFF_FACTOR,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers.update(
            {
                "User-Agent": "AgriTech-Bodemkaart/1.0",
                "Accept": "application/json, text/xml, text/html",
            }
        )
        return s

    # -------------------- Validatie / projectie --------------------

    @staticmethod
    def _validate_latlon(lat: float, lon: float) -> None:
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            raise CoordinateValidationError("Latitude en longitude moeten numeriek zijn.")
        if not (NL_LAT_MIN <= lat <= NL_LAT_MAX and NL_LON_MIN <= lon <= NL_LON_MAX):
            logger.warning(
                "Coördinaten (%.6f, %.6f) lijken buiten NL-bounds (%.1f..%.1f, %.1f..%.1f).",
                lat, lon, NL_LAT_MIN, NL_LAT_MAX, NL_LON_MIN, NL_LON_MAX
            )

    @staticmethod
    def _ll_to_web_mercator(lon: float, lat: float) -> Tuple[float, float]:
        lat = max(-85.051128779807, min(85.051128779807, lat))
        x = lon * 20037508.34 / 180.0
        y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
        y = y * 20037508.34 / 180.0
        return x, y

    # -------------------- Laagdetectie --------------------

    def _discover_layer(self) -> Optional[str]:
        with self._cache_lock:
            if self._layer_cache:
                return self._layer_cache

        params = {"service": "WMS", "request": "GetCapabilities", "version": WMS_VERSION}
        try:
            r = self._session.get(WMS_BASE, params=params, timeout=self.timeout)
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except Exception as e:
            raise LayerDiscoveryError(f"GetCapabilities mislukte: {e}")

        # Verzamel queryable lagen met bodem/soil/grond in de naam
        candidates: List[str] = []
        for layer in root.findall(".//wms:Layer/wms:Layer", WMS_NS):
            name_el = layer.find("wms:Name", WMS_NS)
            if name_el is None:
                continue
            name = (name_el.text or "").strip()
            if not name:
                continue
            if layer.attrib.get("queryable", "0") != "1":
                continue
            lname = name.lower()
            if any(w in lname for w in ("bodem", "soil", "grond", "bodemkaart")):
                candidates.append(name)

        # Voorkeuren
        preferred = ["bodemkaart", "bro-bodemkaart", "bodem", "soil"]
        chosen = None
        for pref in preferred:
            for c in candidates:
                if pref in c.lower():
                    chosen = c
                    break
            if chosen:
                break
        if not chosen and candidates:
            chosen = candidates[0]

        with self._cache_lock:
            self._layer_cache = chosen

        if chosen:
            logger.info("Gekozen bodemlaag: %s", chosen)
        else:
            logger.error("Geen geschikte queryable bodemlaag gevonden.")
        return chosen

    def get_available_layer(self) -> Optional[str]:
        return self._discover_layer()

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._layer_cache = None

    # -------------------- GetFeatureInfo --------------------

    def _build_gfi_params(self, layer: str, lat: float, lon: float) -> Dict[str, str]:
        x, y = self._ll_to_web_mercator(lon, lat)
        bbox = f"{x - self.buffer_m},{y - self.buffer_m},{x + self.buffer_m},{y + self.buffer_m}"
        return {
            "SERVICE": "WMS",
            "VERSION": WMS_VERSION,
            "REQUEST": "GetFeatureInfo",
            "LAYERS": layer,
            "QUERY_LAYERS": layer,
            "CRS": "EPSG:3857",
            "BBOX": bbox,
            "WIDTH": "256",
            "HEIGHT": "256",
            "I": "128",
            "J": "128",
            "FEATURE_COUNT": "5",
            "STYLES": "",
        }

    def _try_gfi(self, params: Dict[str, str]) -> Tuple[Optional[str], Optional[Any]]:
        for fmt in PREFERRED_INFO_FORMATS:
            p = dict(params)
            p["INFO_FORMAT"] = fmt
            try:
                r = self._session.get(WMS_BASE, params=p, timeout=self.timeout)
                r.raise_for_status()
                if fmt == "application/json":
                    return fmt, r.json()
                return fmt, r.text
            except Exception as e:
                logger.debug("GetFeatureInfo (%s) faalde: %s", fmt, e)
                continue
        return None, None

    # -------------------- Parsers --------------------

    @staticmethod
    def _parse_json_payload(obj: Any) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        if not isinstance(obj, dict):
            return None, None
        feats = obj.get("features")
        if not isinstance(feats, list) or not feats:
            return None, None
        feat = feats[0]
        props = feat.get("properties") if isinstance(feat, dict) else None
        return feat if isinstance(feat, dict) else None, props if isinstance(props, dict) else None

    @staticmethod
    def _parse_html_to_props(html: str) -> Optional[Dict[str, Any]]:
        if not isinstance(html, str) or not html.strip():
            return None
        # Vervang <br> door \n en strip alle tags
        text = re.sub(r"<\s*br\s*/?>", "\n", html, flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        props: Dict[str, Any] = {}
        for line in lines:
            if ":" in line:
                k, v = line.split(":", 1)
                k = k.strip()
                v = v.strip()
                if k and v:
                    props[k] = v
        return props or None

    @staticmethod
    def _parse_xml_to_props(xml_text: str) -> Optional[Dict[str, Any]]:
        try:
            root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
        except Exception:
            return None
        props: Dict[str, Any] = {}
        for elem in root.iter():
            if elem is root:
                continue
            tag = elem.tag.split("}", 1)[-1]
            val = (elem.text or "").strip()
            if tag and val:
                if tag not in props or len(val) > len(str(props[tag])):
                    props[tag] = val
        return props or None

    # -------------------- Normaliseren --------------------

    @staticmethod
    def _normalize_key(k: str) -> str:
        kl = (k or "").strip()
        key = kl.lower()
        if key in NORMALIZE_KEY_MAP:
            return NORMALIZE_KEY_MAP[key]

        # heuristieken voor varianten
        if "bodem" in key and "type" in key:
            return "bodemtype"
        if "grond" in key and ("soort" in key or "type" in key):
            return "grondsoort"
        if "legend" in key:
            return "legenda"
        if "beschr" in key or "omschr" in key:
            return "omschrijving"
        if key in {"naam", "name", "label", "titel", "title"}:
            return "naam"
        if "klasse" in key or "class" in key:
            return "klasse"
        if "subtype" in key:
            return "subtype"
        if "cat" in key or "categ" in key:
            return "categorie"
        if "code" in key or key.endswith("_cd"):
            return "code"

        return kl  # behoud originele sleutel

    @staticmethod
    def _normalize_props(props: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k, v in (props or {}).items():
            out[BodemkaartWMSClient._normalize_key(str(k))] = v
        return out

    @staticmethod
    def _pick_soil_text(props_norm: Dict[str, Any]) -> Optional[str]:
        for key in SOIL_NAME_PRIORITY:
            val = props_norm.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        # Fallback: kies langste string
        best = None
        for v in props_norm.values():
            if isinstance(v, str) and v.strip():
                if best is None or len(v) > len(best):
                    best = v
        return best

    # -------------------- Hoofd-API --------------------

    def query_soil_at_point(self, lat: float, lon: float) -> SoilQueryResult:
        self._validate_latlon(lat, lon)
        layer = self._discover_layer()
        if not layer:
            return SoilQueryResult(
                success=False,
                soil_text=None,
                layer_name=None,
                coordinates=(lat, lon),
                error_message="Geen queryable bodemlaag gevonden in WMS capabilities.",
            )

        params = self._build_gfi_params(layer, lat, lon)
        used_fmt, payload = self._try_gfi(params)
        if used_fmt is None or payload is None:
            return SoilQueryResult(
                success=False,
                soil_text=None,
                layer_name=layer,
                coordinates=(lat, lon),
                error_message="GetFeatureInfo gaf geen resultaat.",
            )

        feature: Optional[Dict[str, Any]] = None
        props_raw: Optional[Dict[str, Any]] = None

        if used_fmt == "application/json":
            feature, props_raw = self._parse_json_payload(payload)
        else:
            if isinstance(payload, str):
                props_raw = self._parse_html_to_props(payload) or self._parse_xml_to_props(payload)
            else:
                props_raw = self._parse_xml_to_props(payload)

        if not props_raw:
            return SoilQueryResult(
                success=True,
                soil_text=None,
                layer_name=layer,
                coordinates=(lat, lon),
                info_format_used=used_fmt,
                properties_raw={},
                properties={},
                feature=feature,
            )

        props_norm = self._normalize_props(props_raw)
        soil_text = self._pick_soil_text(props_norm)

        return SoilQueryResult(
            success=True,
            soil_text=soil_text,
            layer_name=layer,
            coordinates=(lat, lon),
            info_format_used=used_fmt,
            properties_raw=props_raw,
            properties=props_norm,
            feature=feature,
        )

    def query_multiple_points(self, coordinates: List[Tuple[float, float]]) -> List[SoilQueryResult]:
        out: List[SoilQueryResult] = []
        for (lat, lon) in coordinates or []:
            try:
                out.append(self.query_soil_at_point(lat, lon))
            except Exception as e:
                out.append(
                    SoilQueryResult(
                        success=False,
                        soil_text=None,
                        layer_name=self._layer_cache,
                        coordinates=(lat, lon),
                        error_message=str(e),
                    )
                )
        return out


# -------------------- Singleton helpers (backwards compatible) --------------------

_default_client: Optional[BodemkaartWMSClient] = None
_client_lock = Lock()


def _get_client() -> BodemkaartWMSClient:
    global _default_client
    with _client_lock:
        if _default_client is None:
            _default_client = BodemkaartWMSClient()
        return _default_client


def query_soil_at_point(lat: float, lon: float) -> Dict[str, Any]:
    """
    Backwards-compatible helper.
    Return:
      {
        "soil_text": <str|None>,
        "raw": {
            "layer": <str|None>,
            "info_format": <str|None>,
            "properties": <dict>        # GENORMALISEERD (bv. soilname_first, soilprofile_name, soilcode, ...)
            "properties_raw": <dict>,   # originele PDOK keys (bv. first_soilname, normal_soilprofile_name, ...)
            "feature": <dict|None>,
            "error": <str|None>
        }
      }
    """
    client = _get_client()
    res = client.query_soil_at_point(lat, lon)
    raw: Dict[str, Any] = {
        "layer": res.layer_name,
        "info_format": res.info_format_used,
        "properties": res.properties or {},
        "properties_raw": res.properties_raw or {},
        "feature": res.feature,
        "error": res.error_message if not res.success else None,
    }
    return {"soil_text": res.soil_text, "raw": raw}


def pick_bodem_layer_name() -> Optional[str]:
    client = _get_client()
    return client.get_available_layer()


# -------------------- Handmatige test --------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    lat, lon = 52.0907, 5.1214  # Utrecht
    data = query_soil_at_point(lat, lon)
    print("soil_text:", data["soil_text"])
    print("normalized keys:", sorted((data["raw"]["properties"] or {}).keys()))
    print("original sample:", {k: data["raw"]["properties_raw"].get(k) for k in ["first_soilname","normal_soilprofile_name","soilcode"]})
