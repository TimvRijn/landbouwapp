# app/percelen/percelen.py
from __future__ import annotations
from flask import Blueprint, render_template, request, redirect, session, url_for, flash, jsonify, current_app, send_from_directory
import uuid
import pandas as pd
import json
import os
from pathlib import Path

import app.models.database_beheer as db
from app.gebruikers.auth_utils import login_required, effective_user_id
from app.services.rvo_grondsoorten import rvo_grondsoort_at_point



# PDOK client
from app.services.pdok_gewaspercelen import (
    fetch_brp_items, parse_brp_features, geojson_polygon_to_points
)
from app.services.bodemkaart_wms import query_soil_at_point, pick_bodem_layer_name

# Nauwkeurige oppervlakte in ha
try:
    import shapely.geometry as sh_geom
    from shapely.ops import transform as sh_transform
    import pyproj
except Exception:
    sh_geom = None
    sh_transform = None
    pyproj = None

percelen_bp = Blueprint(
    'percelen',
    __name__,
    template_folder='templates',
    static_folder='static',
    url_prefix='/percelen'
)

# Toegestane app-categorieën (zelfde labels als je <select>)
ALLOWED_GRONDSOORTEN = {
    "Klei",
    "Noordelijk, westelijk, centraal zand",
    "Zuidelijk zand",
    "Löss",
    "Veen",
}

# Cache voor NV-gebieden GeoJSON
_NV_GEOJSON_CACHE = None

def get_nv_geojson():
    """
    Lees static/data/test2.geojson één keer in en bewaar het in geheugen.
    Daarna wordt het hergebruikt voor alle requests.
    """
    global _NV_GEOJSON_CACHE
    if _NV_GEOJSON_CACHE is None:
        # current_app.static_folder wijst naar je globale /static map
        geojson_path = Path(current_app.static_folder) / "data" / "test2.geojson"
        with geojson_path.open(encoding="utf-8") as f:
            _NV_GEOJSON_CACHE = json.load(f)
    return _NV_GEOJSON_CACHE



def safe_float(value):
    """Safely convert value to float, return None if not possible."""
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _parse_coords_or_none(raw: str):
    """Parse polygon coordinates from JSON string."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, list) and len(data) >= 3:
            for p in data:
                if not isinstance(p, dict) or 'lat' not in p or 'lng' not in p:
                    return None
            return json.dumps(data, separators=(',', ':'))
    except Exception:
        return None
    return None


def _calc_area_ha_geojson(geom: dict):
    """Oppervlakte (ha) van GeoJSON polygon/multipolygon (EPSG:4326/CRS84) met shapely+pyproj als beschikbaar."""
    if not geom or not sh_geom or not pyproj or not sh_transform:
        return None
    try:
        poly = sh_geom.shape(geom)
        centroid = poly.centroid
        proj = pyproj.Proj(
            proj='aea',
            lat_1=centroid.y - 2,
            lat_2=centroid.y + 2,
            lat_0=centroid.y,
            lon_0=centroid.x
        )
        wgs84 = pyproj.Proj('epsg:4326')
        project = pyproj.Transformer.from_proj(wgs84, proj, always_xy=True).transform
        area_m2 = sh_transform(project, poly).area
        return round(area_m2 / 10000.0, 4)
    except Exception:
        return None


def _auto_determine_grondsoort(lat: float, lng: float) -> str:
    """
    Voorkeur: RVO (indien zinvol resultaat).
    Fallback: PDOK WMS -> tekst -> app-categorie.
    """
    # 1) Probeer RVO, maar alleen gebruiken als het resultaat betekenisvol is
    try:
        r = rvo_grondsoort_at_point(lat, lng) or {}
        r_raw = (r.get("raw") or {})
        r_cat = r.get("category")
        r_meaningful = bool(
            r_cat and (
                r_raw.get("hoofdg") or
                r_raw.get("in_zuidelijk") or
                r_raw.get("in_loess")
            )
        )
        if r_meaningful:
            return r_cat
    except Exception as e:
        print(f"RVO grondsoort fout: {e}")

    # 2) Fallback naar PDOK WMS (zoals je al had)
    try:
        soil_data = query_soil_at_point(lat, lng)  # {"soil_text": "...", "raw": {...}}
        soil_text = (soil_data or {}).get("soil_text") or ""
        mapped = _map_soil_text_to_category(soil_text)
        return mapped or "Noordelijk, westelijk, centraal zand"
    except Exception as e:
        print(f"WMS fallback grondsoort fout: {e}")
        return "Noordelijk, westelijk, centraal zand"


def _map_soil_text_to_category(s: str) -> str:
    t = (s or "").lower()
    if not t:
        return ""
    if "veen" in t:
        return "Veen"
    if "klei" in t or "zavel" in t:
        return "Klei"
    # Löss/leem → apart
    if "löss" in t or "loess" in t or "loss" in t or "leem" in t:
        return "Löss"
    # Zand laten we open; RVO bepaalt Noord/W/C vs Zuid
    if "zand" in t or "podzol" in t:
        return ""
    return ""


# ------------- Routes -------------
@percelen_bp.route('/', methods=['GET', 'POST'])
@login_required
def percelen():
    if request.method == 'POST':
        perceelnaam = request.form['perceelnaam'].strip()
        if not perceelnaam:
            flash("Perceelnaam is verplicht.", "danger")
            return redirect(url_for('percelen.percelen'))

        # Get form data
        oppervlakte = request.form.get('oppervlakte')
        grondsoort = request.form.get('grondsoort')
        p_al = request.form.get('p_al')
        p_cacl2 = request.form.get('p_cacl2')
        

        latitude = (request.form.get('latitude') or '').strip()
        longitude = (request.form.get('longitude') or '').strip()
        adres = (request.form.get('adres') or '').strip()

        polygon_raw = (request.form.get('polygon_coordinates') or '').strip()
        polygon_json = _parse_coords_or_none(polygon_raw)
        calculated_area = request.form.get('calculated_area')

        # Validate and convert coordinates
        lat_val = None
        lng_val = None
        if latitude and longitude:
            try:
                lat_val = float(latitude)
                lng_val = float(longitude)
                if not (50.0 <= lat_val <= 54.0 and 3.0 <= lng_val <= 8.0):
                    flash("Coördinaten lijken niet in Nederland te liggen. Controleer de locatie.", "warning")
            except (ValueError, TypeError):
                flash("Ongeldige coördinaten opgegeven.", "danger")
                return redirect(url_for('percelen.percelen'))
                # ... na het bepalen van lat_val, lng_val ...

        # Bepaal nv_gebied automatisch op basis van NV-gebieden kaartlaag
        if lat_val is not None and lng_val is not None:
            try:
                nv_bool = is_in_nv_gebied(lat_val, lng_val)
                nv_gebied = 1 if nv_bool else 0
            except Exception as e:
                print(f"NV-gebied check fout: {e}")
                nv_gebied = 0
        else:
            nv_gebied = 0

        # Auto-determine grondsoort if not provided and coordinates are available
        if (not grondsoort or grondsoort == '') and lat_val and lng_val:
            grondsoort = _auto_determine_grondsoort(lat_val, lng_val)
            flash(f"Grondsoort automatisch bepaald als '{grondsoort}' op basis van bodemkaart.", "info")

        # Validate required fields
        if not grondsoort:
            flash("Grondsoort is verplicht. Zorg dat er coördinaten zijn voor automatische bepaling.", "danger")
            return redirect(url_for('percelen.percelen'))

        # Check for duplicate names (same user)
        conn, c = db.get_dict_cursor()
        try:
            c.execute(
                "SELECT 1 FROM percelen WHERE perceelnaam=%s AND user_id=%s",
                (perceelnaam, effective_user_id())
            )
            exists = c.fetchone()

            if exists:
                flash("Deze perceelnaam bestaat al. Geef het perceel een andere naam en probeer opnieuw.", "danger")
                conn.close()
                return redirect(url_for('percelen.percelen'))

            # Insert new perceel
            oppervlakte_value = safe_float(calculated_area) or safe_float(oppervlakte)
            calculated_area_value = safe_float(calculated_area)

            c.execute(
                '''
                INSERT INTO percelen
                (id, perceelnaam, oppervlakte, grondsoort, p_al, p_cacl2, nv_gebied,
                 latitude, longitude, adres, polygon_coordinates, calculated_area,
                 pdok_source, user_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''',
                (
                    str(uuid.uuid4()),
                    perceelnaam,
                    oppervlakte_value,
                    grondsoort,
                    safe_float(p_al),
                    safe_float(p_cacl2),
                    nv_gebied,
                    lat_val,
                    lng_val,
                    adres,
                    polygon_json,
                    calculated_area_value,
                    "PDOK_manual_selection",
                    effective_user_id()
                )
            )
            conn.commit()
            flash(f"Perceel '{perceelnaam}' succesvol toegevoegd.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"Fout bij toevoegen perceel: {e}", "danger")
        finally:
            conn.close()

        return redirect(url_for('percelen.percelen'))

    # GET request - show percelen overview
    conn, c = db.get_dict_cursor()
    try:
        c.execute(
            'SELECT * FROM percelen WHERE user_id=%s ORDER BY perceelnaam',
            (effective_user_id(),)
        )
        rows = c.fetchall()  # list[dict]
    finally:
        conn.close()

    def row_to_jsonable(r: dict) -> dict:
        d = dict(r)  # kopie

        def to_float(x):
            try:
                return float(x) if x not in (None, '') else None
            except (TypeError, ValueError):
                return None

        for k in ('oppervlakte', 'calculated_area', 'p_al', 'p_cacl2', 'latitude', 'longitude'):
            d[k] = to_float(d.get(k))

        d['nv_gebied'] = int(d.get('nv_gebied') or 0)

        pc = d.get('polygon_coordinates')
        if isinstance(pc, (bytes, memoryview)):
            d['polygon_coordinates'] = bytes(pc).decode('utf-8', errors='ignore')

        return d

    percelen_list = [row_to_jsonable(r) for r in rows]

    # ⬇️ NV-geojson uit cache halen
    nv_geojson = get_nv_geojson()

    return render_template(
        'percelen/percelen.html',
        percelen=percelen_list,
        nv_geojson=nv_geojson,   # ⬅️ extra variabele naar de template
    )



@percelen_bp.route('/delete/<id>', methods=['POST'])
@login_required
def percelen_delete(id):
    conn, c = db.get_dict_cursor()
    try:
        c.execute(
            'SELECT perceelnaam FROM percelen WHERE id=%s AND user_id=%s',
            (id, effective_user_id())
        )
        perceel = c.fetchone()

        if perceel:
            c.execute(
                'DELETE FROM percelen WHERE id=%s AND user_id=%s',
                (id, effective_user_id())
            )
            conn.commit()
            flash(f"Perceel '{perceel['perceelnaam']}' verwijderd.", "success")
        else:
            flash("Perceel niet gevonden of geen toegang.", "danger")
    except Exception as e:
        conn.rollback()
        flash(f"Fout bij verwijderen perceel: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for('percelen.percelen'))


@percelen_bp.route('/edit/<id>', methods=['GET', 'POST'])
@login_required
def percelen_edit(id):
    conn, c = db.get_dict_cursor()

    if request.method == 'POST':
        try:
            perceelnaam = request.form['perceelnaam'].strip()
            if not perceelnaam:
                flash("Perceelnaam is verplicht.", "danger")
                return redirect(url_for('percelen.percelen'))

            oppervlakte = request.form.get('oppervlakte')
            grondsoort = request.form.get('grondsoort')
            p_al = request.form.get('p_al')
            p_cacl2 = request.form.get('p_cacl2')

            latitude = (request.form.get('latitude') or '').strip()
            longitude = (request.form.get('longitude') or '').strip()
            adres = (request.form.get('adres') or '').strip()

            polygon_raw = (request.form.get('polygon_coordinates') or '').strip()
            polygon_json = _parse_coords_or_none(polygon_raw)
            calculated_area = request.form.get('calculated_area')

            lat_val = None
            lng_val = None
            if latitude and longitude:
                try:
                    lat_val = float(latitude)
                    lng_val = float(longitude)
                except (ValueError, TypeError):
                    flash("Ongeldige coördinaten opgegeven.", "danger")
                    return redirect(url_for('percelen.percelen'))

            # 👉 HIER toevoegen:
            if lat_val is not None and lng_val is not None:
                try:
                    nv_bool = is_in_nv_gebied(lat_val, lng_val)
                    nv_gebied = 1 if nv_bool else 0
                except Exception as e:
                    print(f"NV-gebied check (edit) fout: {e}")
                    nv_gebied = 0
            else:
                nv_gebied = 0

            
            # Check for duplicate names (excluding current perceel)
            c.execute(
                "SELECT 1 FROM percelen WHERE perceelnaam=%s AND user_id=%s AND id<>%s",
                (perceelnaam, effective_user_id(), id)
            )
            exists = c.fetchone()

            if exists:
                flash("Deze perceelnaam bestaat al. Geef het perceel een andere naam en probeer opnieuw.", "danger")
                conn.close()
                return redirect(url_for('percelen.percelen'))

            oppervlakte_value = safe_float(calculated_area) or safe_float(oppervlakte)
            calculated_area_value = safe_float(calculated_area)

            c.execute(
                '''
                UPDATE percelen
                SET perceelnaam=%s,
                    oppervlakte=%s,
                    grondsoort=%s,
                    p_al=%s,
                    p_cacl2=%s,
                    nv_gebied=%s,
                    latitude=%s,
                    longitude=%s,
                    adres=%s,
                    polygon_coordinates=%s,
                    calculated_area=%s
                WHERE id=%s AND user_id=%s
                ''',
                (
                    perceelnaam,
                    oppervlakte_value,
                    grondsoort,
                    safe_float(p_al),
                    safe_float(p_cacl2),
                    nv_gebied,
                    lat_val,
                    lng_val,
                    adres,
                    polygon_json,
                    calculated_area_value,
                    id,
                    effective_user_id()
                )
            )
            conn.commit()
            flash("Perceel bijgewerkt.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"Fout bij bijwerken perceel: {e}", "danger")
        finally:
            conn.close()

        return redirect(url_for('percelen.percelen'))

    # GET request - show edit form
    try:
        c.execute(
            'SELECT * FROM percelen WHERE id=%s AND user_id=%s',
            (id, effective_user_id())
        )
        perceel = c.fetchone()
    finally:
        conn.close()

    if perceel is None:
        flash("Perceel niet gevonden of geen toegang.", "danger")
        return redirect(url_for('percelen.percelen'))

    return render_template('percelen/percelen_edit.html', perceel=perceel)


# -------- PDOK OGC API endpoints --------

@percelen_bp.route('/pdok/search', methods=['GET'])
@login_required
def pdok_search():
    """
    Search for gewaspercelen in a bounding box.
    Example: /percelen/pdok/search?bbox=4.5,52.1,4.7,52.2&year=2024&limit=300
    """
    bbox = (request.args.get('bbox') or '').strip()
    year = request.args.get('year', type=int)
    limit = request.args.get('limit', default=500, type=int)

    if not bbox or len(bbox.split(',')) != 4:
        return jsonify({"error": "bbox vereist: minx,miny,maxx,maxy"}), 400

    try:
        fc = fetch_brp_items(bbox=bbox, limit=limit)
        feats = parse_brp_features(fc)

        if year:
            feats = [f for f in feats if str(f.get("jaar") or "") == str(year)]

        return jsonify({"count": len(feats), "features": feats})
    except Exception as e:
        return jsonify({"error": f"PDOK OGC fout: {e}"}), 502


@percelen_bp.route('/pdok/import', methods=['POST'])
@login_required
def pdok_import():
    """
    Import selected percelen from PDOK.
    Body format:
    {
      "items": [
        {
          "pdok_id": "optional-but-useful",
          "category": "Bouwland" | "Grasland" | ...,
          "geometry": { ... GeoJSON Polygon/MultiPolygon ... },
          "centroid": {"lat": 52.1, "lng": 5.3}  # optional
        },
        ...
      ]
    }
    """
    try:
        payload = request.get_json(force=True) or {}
        items = payload.get("items") or []
    except Exception:
        flash("Ongeldige JSON voor PDOK-import.", "danger")
        return redirect(url_for('percelen.percelen'))

    if not items:
        flash("Geen percelen geselecteerd voor import.", "warning")
        return redirect(url_for('percelen.percelen'))

    conn = db.get_connection()
    c = conn.cursor()
    toegevoegd, overgeslagen = 0, 0

    try:
        for it in items:
            geom = it.get("geometry")
            if not geom:
                overgeslagen += 1
                continue

            pdok_id = (it.get("pdok_id") or "").strip()
            id_short = pdok_id.split("-")[0] if pdok_id else ""

            naam = f"PDOK perceel {id_short}".strip() if id_short else "PDOK perceel"

            if pdok_id:
                c.execute(
                    "SELECT 1 FROM percelen WHERE user_id=%s AND pdok_id=%s",
                    (effective_user_id(), pdok_id)
                )
                exists = c.fetchone()
                if exists:
                    overgeslagen += 1
                    continue

            points = geojson_polygon_to_points(geom)
            polygon_json = json.dumps(points, separators=(',', ':')) if points else None

            area_ha = _calc_area_ha_geojson(geom)

            centroid = it.get("centroid") or {}
            lat_val = safe_float(centroid.get("lat"))
            lng_val = safe_float(centroid.get("lng"))

            grondsoort = None
            nv_gebied = 0
            if lat_val and lng_val:
                grondsoort = _auto_determine_grondsoort(lat_val, lng_val)
                try:
                    nv_bool = is_in_nv_gebied(lat_val, lng_val)
                    nv_gebied = 1 if nv_bool else 0
                except Exception as e:
                    print(f"NV-gebied check (PDOK import) fout: {e}")
                    nv_gebied = 0


            c.execute(
                '''
                INSERT INTO percelen
                (id, perceelnaam, oppervlakte, grondsoort, p_al, p_cacl2, nv_gebied,
                 latitude, longitude, adres, polygon_coordinates, calculated_area,
                 pdok_id, pdok_category, pdok_source, geometry_geojson, user_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''',
                (
                    str(uuid.uuid4()),
                    naam,
                    area_ha,
                    grondsoort,
                    None, None, 0,
                    nv_gebied,
                    lat_val, lng_val, '',
                    polygon_json,
                    area_ha,
                    pdok_id or None,
                    it.get("category"),
                    "PDOK_BRPGewaspercelen_OGC",
                    json.dumps(geom, separators=(',', ':')),
                    effective_user_id()
                )
            )
            toegevoegd += 1


        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f"Fout bij PDOK-import: {e}", "danger")
        conn.close()
        return redirect(url_for('percelen.percelen'))
    finally:
        conn.close()

    if toegevoegd:
        flash(
            f"{toegevoegd} perceel{'en' if toegevoegd != 1 else ''} via PDOK geïmporteerd. "
            f"{overgeslagen} overgeslagen.",
            "success"
        )
    else:
        flash("Geen percelen geïmporteerd (mogelijk al bestaand of zonder geometrie).", "warning")

    return redirect(url_for('percelen.percelen'))


@percelen_bp.route('/bodem/soil_at', methods=['GET'])
@login_required
def bodem_soil_at():
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    if lat is None or lng is None:
        return jsonify({"error": "lat & lng vereist"}), 400
    try:
        rvo = rvo_grondsoort_at_point(lat, lng) or {}
        wms = query_soil_at_point(lat, lng) or {}

        rvo_raw = (rvo.get("raw") or {})
        rvo_cat = rvo.get("category")
        rvo_meaningful = bool(
            rvo_cat and (rvo_raw.get("hoofdg") or rvo_raw.get("in_zuidelijk") or rvo_raw.get("in_loess"))
        )
        soil_text = (wms or {}).get("soil_text") or ""
        category = rvo_cat if rvo_meaningful else _map_soil_text_to_category(soil_text)

        return jsonify({
            "soil_text": soil_text,
            "category": category,
            "rvo_raw": rvo_raw
        })
    except Exception as e:
        return jsonify({"error": f"RVO/WMS query fout: {e}"}), 500


@percelen_bp.route('/bodem/layer_name', methods=['GET'])
@login_required
def bodem_layer_name():
    """Get the name of the soil layer for overlay purposes."""
    try:
        name = pick_bodem_layer_name()
        return jsonify({"layer": name})
    except Exception as e:
        return jsonify({"layer": "bodemkaart", "error": str(e)})




