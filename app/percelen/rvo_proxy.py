from flask import Blueprint, request, Response, jsonify
import requests

# Losse API-blueprint die in de 'percelen' package leeft,
# maar met eigen url_prefix zodat de URL /api/rvo/... is
rvo_api_bp = Blueprint("rvo_api", __name__, url_prefix="/api/rvo")

PDOK_WFS = "https://service.pdok.nl/rvo/brpgewaspercelen/wfs/v2_0"

def _bad_request(msg, code=400):
    return jsonify({"error": msg}), code

@rvo_api_bp.get("/brp")
def brp():
    """
    Proxy naar PDOK WFS (BRP gewaspercelen) om CORS te omzeilen.
    Verwacht: bbox=minx,miny,maxx,maxy,EPSG:4326  (WGS84)
    """
    bbox = (request.args.get("bbox") or "").strip()
    if not bbox or bbox.count(",") < 4 or "EPSG:4326" not in bbox:
        return _bad_request("Geef bbox als 'minx,miny,maxx,maxy,EPSG:4326'.")

    try:
        parts = bbox.split(",")
        minx, miny, maxx, maxy = map(float, parts[:4])
        if maxx <= minx or maxy <= miny:
            return _bad_request("bbox is ongeldig (max <= min).")
        # simpele limiet tegen te grote queries
        if (maxx - minx) * (maxy - miny) > 10:
            return _bad_request("bbox te groot, zoom verder in.")
    except ValueError:
        return _bad_request("bbox bevat geen geldige getallen.")

    params = {
        "service": "WFS",
        "request": "GetFeature",
        "typeName": "brpgewaspercelen:gewaspercelen",
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "bbox": bbox,
    }
    headers = {"User-Agent": "AgriTech2100/1.0 (support@jouwdomein.nl)"}

    try:
        r = requests.get(PDOK_WFS, params=params, headers=headers, timeout=15)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        return _bad_request(f"Fout bij ophalen PDOK: {e}", 502)

    resp = Response(r.content, status=200, mimetype="application/json")
    resp.headers["Cache-Control"] = "public, max-age=120"
    return resp
