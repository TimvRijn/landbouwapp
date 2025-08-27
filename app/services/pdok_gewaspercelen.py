# app/services/pdok_gewaspercelen.py
from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple
import requests

# PDOK OGC API (BRP Gewaspercelen)
PDOK_BASE = "https://api.pdok.nl/rvo/gewaspercelen/ogc/v1"
COLLECTION = "brpgewas"


def _geom_centroid_polygon(coords: List[List[Tuple[float, float]]]) -> Optional[Dict[str, float]]:
    """Centroid van een GeoJSON Polygon (lon,lat). Exterieur ring = coords[0]."""
    try:
        ring = coords[0]
        area2 = 0.0
        cx = 0.0
        cy = 0.0
        n = len(ring)
        if n < 3:
            return None
        for i in range(n - 1):
            x1, y1 = ring[i]
            x2, y2 = ring[i + 1]
            cross = x1 * y2 - x2 * y1
            area2 += cross
            cx += (x1 + x2) * cross
            cy += (y1 + y2) * cross
        if area2 == 0:
            return None
        cx = cx / (3 * area2)
        cy = cy / (3 * area2)
        return {"lat": cy, "lng": cx}
    except Exception:
        return None


def _geom_centroid(geom: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Centroid voor GeoJSON Polygon/MultiPolygon."""
    if not geom:
        return None
    t = geom.get("type")
    if t == "Polygon":
        return _geom_centroid_polygon(geom.get("coordinates") or [])
    if t == "MultiPolygon":
        polys = geom.get("coordinates") or []
        if not polys:
            return None
        return _geom_centroid_polygon(polys[0])
    return None


def geojson_polygon_to_points(geom: Dict[str, Any]) -> Optional[List[Dict[str, float]]]:
    """
    Zet GeoJSON Polygon/MultiPolygon om naar lijst [{lat,lng}, ...] (exterieur ring).
    Handig voor opslag in je 'polygon_coordinates' kolom (front-end verwacht dit formaat).
    """
    if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
        return None

    def ring_to_points(ring: List[List[float]]):
        return [{"lat": float(y), "lng": float(x)} for x, y in ring]

    if geom["type"] == "Polygon":
        exterior = geom["coordinates"][0]
        return ring_to_points(exterior)
    else:
        exterior = geom["coordinates"][0][0]
        return ring_to_points(exterior)


def fetch_brp_items(bbox: str, limit: int = 250) -> Dict[str, Any]:
    """
    Haal BRP gewaspercelen op binnen een bbox.
    - bbox: 'minx,miny,maxx,maxy' (lon,lat,lon,lat) in CRS84/WGS84.
    - limit: max 1000 per verzoek (API-limiet).
    Returned: GeoJSON FeatureCollection (dict).
    """
    url = f"{PDOK_BASE}/collections/{COLLECTION}/items"
    params = {
        "bbox": bbox,
        "limit": min(int(limit), 1000),
        # Sommige OGC implementaties ondersteunen 'properties=' om te projecteren.
        # PDOK levert toch alle props; we strippen ze later in parse_brp_features.
        # "properties": "category",  # ← kun je proberen; is optioneel
    }
    headers = {"Accept": "application/geo+json"}
    r = requests.get(url, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def parse_brp_features(fc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Minimaliseer naar wat de front-end nodig heeft:
    - pdok_id    (optioneel, maar handig als key)
    - category   (voor filteren in de UI)
    - geometry   (GeoJSON, om te tekenen/klikken)
    - centroid   (lat/lng, voor centreren/adres)
    """
    out: List[Dict[str, Any]] = []
    for f in (fc.get("features") or []):
        props = f.get("properties") or {}
        geom = f.get("geometry") or {}
        out.append({
            "pdok_id": f.get("id") or props.get("id"),
            "category": props.get("category"),
            "geometry": geom,
            "centroid": _geom_centroid(geom) if geom else None,
        })
    return out
