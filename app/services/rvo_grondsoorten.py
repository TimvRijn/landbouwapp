# app/services/rvo_grondsoorten.py
from __future__ import annotations
import requests
from functools import lru_cache
from typing import Optional, Dict

# === VUL DEZE 2 CONSTANTEN IN MET JOUW LAYER-ENDPOINTS ===
# Voorbeeldvorm (LET OP: dit zijn VOORBEELD-paden, zet hier je eigen endpoints):
RVO_GRONDSOORTEN_FEATURE_URL = "https://<org>.maps.arcgis.com/arcgis/rest/services/Grondsoortenkaart/FeatureServer/0"
RVO_ZUIDELIJK_GEBIED_FEATURE_URL = "https://<org>.maps.arcgis.com/arcgis/rest/services/Zuidelijk_zand_en_loessgebied/FeatureServer/0"

# Als je een losse "Lössgebied"-laag hebt, vul die hier in; anders laten op None
RVO_LOESS_GEBIED_FEATURE_URL = None  # bv. ".../FeatureServer/1" als beschikbaar

# In de grondsoortenlaag: welk attribuut draagt de hoofdgrondsoort?
# Veel gebruikt: "HOOFDGRS" of "GRONDSOORT". Zet je veldnaam hier.
GRONDSOORT_VELD = "HOOFDGRS"   # pas aan indien nodig

# Kleine helper om ArcGIS FeatureServer te bevragen op intersectie met een punt:
def _arcgis_query_point(layer_url: str, lat: float, lng: float, out_fields="*") -> Dict:
    params = {
        "f": "json",
        "geometry": f'{{"x":{lng},"y":{lat},"spatialReference":{{"wkid":4326}}}}',
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": out_fields,
        "returnGeometry": "false",
        "where": "1=1"
    }
    r = requests.get(layer_url + "/query", params=params, timeout=15)
    r.raise_for_status()
    return r.json()

@lru_cache(maxsize=2048)
def _point_in_region(layer_url: str, lat: float, lng: float) -> bool:
    try:
        data = _arcgis_query_point(layer_url, lat, lng, out_fields="OBJECTID")
        return bool(data.get("features"))
    except Exception:
        return False

@lru_cache(maxsize=2048)
def _grondsoort_raw(lat: float, lng: float) -> Dict:
    """
    Haalt het ruwe feature-attribuut uit de RVO grondsoortenkaart (punt-intersect).
    Retourneert bijv. {"hoofdg": "ZAND"} of {"hoofdg": "KLEI"} afhankelijk van jouw veldnaam.
    """
    try:
        data = _arcgis_query_point(RVO_GRONDSOORTEN_FEATURE_URL, lat, lng, out_fields=f"{GRONDSOORT_VELD}")
        feats = data.get("features") or []
        if not feats:
            return {"hoofdg": ""}
        attrs = (feats[0].get("attributes") or {})
        val = str(attrs.get(GRONDSOORT_VELD, "") or "").strip()
        return {"hoofdg": val}
    except Exception:
        return {"hoofdg": ""}

def _norm(s: str) -> str:
    return (s or "").lower().replace("ö", "o").replace("öss", "oss").strip()

def _map_rvo_to_app(hoofdg: str, in_zuidelijk: bool, in_loess: bool) -> str:
    """
    RVO -> app-categorieën, met aparte 'Zuidelijk zand' en 'Löss' zoals in Tabel 2 (2025).
    """
    h = _norm(hoofdg)

    # Löss (altijd apart tonen)
    if in_loess or "loss" in h or "loess" in h or "löss" in h or "leem" in h:
        return "Löss"

    # Veen
    if "veen" in h:
        return "Veen"

    # Klei (in sommige kaarten komt 'zavel' ook voor; die rekent RVO onder klei)
    if "klei" in h or "zavel" in h:
        return "Klei"

    # Zand
    if "zand" in h or "podzol" in h:
        return "Zuidelijk zand" if in_zuidelijk else "Noordelijk, westelijk, centraal zand"

    # Fallbacks
    if in_zuidelijk:
        return "Zuidelijk zand"
    return "Noordelijk, westelijk, centraal zand"

def rvo_grondsoort_at_point(lat: float, lng: float) -> Dict:
    """
    Bepaalt de grondsoort volgens RVO-grondsoortenkaart + beleidregio:
    - Leest hoofdgrondsoort uit de kaart (bv. HOOFDGRS).
    - Checkt of punt in 'Zuidelijk zand- en lössgebied' valt.
    - (Optioneel) Checkt losse 'Lössgebied'-laag; anders herkennen we löss via veldwaarde.
    Retourneert: {"category": "...", "raw": {"hoofdg": "...", "in_zuidelijk": bool, "in_loess": bool}}
    """
    raw = _grondsoort_raw(lat, lng)
    in_zuid = _point_in_region(RVO_ZUIDELIJK_GEBIED_FEATURE_URL, lat, lng) if RVO_ZUIDELIJK_GEBIED_FEATURE_URL else False

    if RVO_LOESS_GEBIED_FEATURE_URL:
        in_loess = _point_in_region(RVO_LOESS_GEBIED_FEATURE_URL, lat, lng)
    else:
        # Zonder losse löss-laag: herkennen we via grondsoortenwaarde zelf
        in_loess = False

    cat = _map_rvo_to_app(raw.get("hoofdg", ""), in_zuid, in_loess)
    return {
        "category": cat,
        "raw": {"hoofdg": raw.get("hoofdg", ""), "in_zuidelijk": in_zuid, "in_loess": in_loess}
    }
