# app/percelen/percelen.py
from __future__ import annotations
from flask import Blueprint, render_template, request, redirect, session, url_for, flash, jsonify
import uuid
import pandas as pd
import sqlite3
import json
import app.models.database_beheer as db
from app.gebruikers.auth_utils import login_required

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
def _map_soil_text_to_category(soil_text: str) -> str:
    """
    Mapt vrije bodemtekst naar app-categorie.
    Belangrijk: zavel -> Klei (incl. varianten als 'lichte/zware zavel', 'zavelig', 'zavelgrond').
    """
    s = (soil_text or "").lower()

    # Veen
    if any(w in s for w in ("veen", "moerig", "venig", "veengrond")):
        return "Veen"

    # Löss / leem (alleen 'Löss' expliciet; 'leem' buiten Zuid-Limburg is vaak geen echte löss,
    # maar hier laten we leem als Löss omdat de dataset dat zo kan aanduiden)
    if "löss" in s or "loess" in s:
        return "Löss"
    if "leem" in s and ("limburg" in s or "zuid-limburg" in s):
        return "Löss"

    # Klei (incl. zavel & varianten en klei-op-veen; 'slib' vaak kleiig)
    if (
        "klei" in s
        or "klei-op-veen" in s
        or "slib" in s
        or "zavel" in s
        or "zavelig" in s
        or "zavelgrond" in s
        or "lichte zavel" in s
        or "zware zavel" in s
    ):
        return "Klei"

    # Zand(achtig)
    if any(w in s for w in ("zand", "podzol", "vaaggronden", "enkeerd", "beekeerd", "gooreerd")):
        return "Noordelijk, westelijk, centraal zand"

    # Fallback
    return "Noordelijk, westelijk, centraal zand"



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
        proj = pyproj.Proj(proj='aea', lat_1=centroid.y - 2, lat_2=centroid.y + 2,
                           lat_0=centroid.y, lon_0=centroid.x)
        wgs84 = pyproj.Proj('epsg:4326')
        project = pyproj.Transformer.from_proj(wgs84, proj, always_xy=True).transform
        area_m2 = sh_transform(project, poly).area
        return round(area_m2 / 10000.0, 4)
    except Exception:
        return None


def _auto_determine_grondsoort(lat: float, lng: float) -> str:
    """Bepaalt grondsoort via bodemkaart en mapped naar app-categorie."""
    try:
        soil_data = query_soil_at_point(lat, lng)  # returns {"soil_text": "...", "raw": {...}}
        soil_text = (soil_data or {}).get("soil_text") or ""
        return _map_soil_text_to_category(soil_text)
    except Exception as e:
        print(f"Error determining grondsoort: {e}")
        return "Noordelijk, westelijk, centraal zand"  # Safe default



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
        nv_gebied = 1 if request.form.get('nv_gebied') == 'ja' else 0

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

        # Auto-determine grondsoort if not provided and coordinates are available
        if (not grondsoort or grondsoort == '') and lat_val and lng_val:
            grondsoort = _auto_determine_grondsoort(lat_val, lng_val)
            flash(f"Grondsoort automatisch bepaald als '{grondsoort}' op basis van bodemkaart.", "info")

        # Validate required fields
        if not grondsoort:
            flash("Grondsoort is verplicht. Zorg dat er coördinaten zijn voor automatische bepaling.", "danger")
            return redirect(url_for('percelen.percelen'))

        # Check for duplicate names
        conn = db.get_connection()
        c = conn.cursor()

        exists = c.execute(
            "SELECT 1 FROM percelen WHERE perceelnaam=? AND user_id=?",
            (perceelnaam, session['user_id'])
        ).fetchone()

        if exists:
            flash(f"Perceel '{perceelnaam}' bestaat al.", "warning")
        else:
            # Insert new perceel
            oppervlakte_value = safe_float(calculated_area) or safe_float(oppervlakte)
            calculated_area_value = safe_float(calculated_area)
            
            c.execute('''
                INSERT INTO percelen
                (id, perceelnaam, oppervlakte, grondsoort, p_al, p_cacl2, nv_gebied,
                 latitude, longitude, adres, polygon_coordinates, calculated_area,
                 pdok_source, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
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
                session['user_id']
            ))
            conn.commit()
            flash(f"Perceel '{perceelnaam}' succesvol toegevoegd.", "success")

        conn.close()
        return redirect(url_for('percelen.percelen'))

    # GET request - show percelen overview
    conn = db.get_connection()
    conn.row_factory = sqlite3.Row
    rows = conn.cursor().execute(
        'SELECT * FROM percelen WHERE user_id=? ORDER BY perceelnaam', 
        (session['user_id'],)
    ).fetchall()
    conn.close()

    return render_template('percelen/percelen.html', percelen=rows)


@percelen_bp.route('/delete/<id>', methods=['POST'])
@login_required
def percelen_delete(id):
    conn = db.get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    perceel = c.execute(
        'SELECT perceelnaam FROM percelen WHERE id=? AND user_id=?',
        (id, session['user_id'])
    ).fetchone()
    
    if perceel:
        c.execute('DELETE FROM percelen WHERE id=? AND user_id=?', (id, session['user_id']))
        conn.commit()
        flash(f"Perceel '{perceel['perceelnaam']}' verwijderd.", "success")
    else:
        flash("Perceel niet gevonden of geen toegang.", "danger")
    
    conn.close()
    return redirect(url_for('percelen.percelen'))


@percelen_bp.route('/edit/<id>', methods=['GET', 'POST'])
@login_required
def percelen_edit(id):
    conn = db.get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

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
        nv_gebied = 1 if request.form.get('nv_gebied') == 'ja' else 0

        latitude = (request.form.get('latitude') or '').strip()
        longitude = (request.form.get('longitude') or '').strip()
        adres = (request.form.get('adres') or '').strip()

        polygon_raw = (request.form.get('polygon_coordinates') or '').strip()
        polygon_json = _parse_coords_or_none(polygon_raw)
        calculated_area = request.form.get('calculated_area')

        # Validate coordinates
        lat_val = None
        lng_val = None
        if latitude and longitude:
            try:
                lat_val = float(latitude)
                lng_val = float(longitude)
            except (ValueError, TypeError):
                flash("Ongeldige coördinaten opgegeven.", "danger")
                return redirect(url_for('percelen.percelen'))

        # Check for duplicate names (excluding current perceel)
        exists = c.execute(
            "SELECT 1 FROM percelen WHERE perceelnaam=? AND user_id=? AND id<>?",
            (perceelnaam, session['user_id'], id)
        ).fetchone()
        
        if exists:
            flash(f"Perceel '{perceelnaam}' bestaat al.", "warning")
            conn.close()
            return redirect(url_for('percelen.percelen'))

        # Update perceel
        oppervlakte_value = safe_float(calculated_area) or safe_float(oppervlakte)
        calculated_area_value = safe_float(calculated_area)
        
        c.execute('''
            UPDATE percelen
            SET perceelnaam=?,
                oppervlakte=?,
                grondsoort=?,
                p_al=?,
                p_cacl2=?,
                nv_gebied=?,
                latitude=?,
                longitude=?,
                adres=?,
                polygon_coordinates=?,
                calculated_area=?
            WHERE id=? AND user_id=?
        ''', (
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
            session['user_id']
        ))
        conn.commit()
        conn.close()
        flash("Perceel bijgewerkt.", "success")
        return redirect(url_for('percelen.percelen'))

    # GET request - show edit form
    perceel = c.execute(
        'SELECT * FROM percelen WHERE id=? AND user_id=?', (id, session['user_id'])
    ).fetchone()
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
        # Fetch data from PDOK
        fc = fetch_brp_items(bbox=bbox, limit=limit)
        feats = parse_brp_features(fc)
        
        # Filter by year if specified
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

    for it in items:
        geom = it.get("geometry")
        if not geom:
            overgeslagen += 1
            continue

        pdok_id = (it.get("pdok_id") or "").strip()
        id_short = pdok_id.split("-")[0] if pdok_id else ""

        # Generate perceel name
        naam = f"PDOK perceel {id_short}".strip() if id_short else "PDOK perceel"

        # Check for duplicates by PDOK ID
        if pdok_id:
            exists = c.execute(
                "SELECT 1 FROM percelen WHERE user_id=? AND pdok_id=?",
                (session['user_id'], pdok_id)
            ).fetchone()
            if exists:
                overgeslagen += 1
                continue

        # Convert geometry to internal format
        points = geojson_polygon_to_points(geom)
        polygon_json = json.dumps(points, separators=(',', ':')) if points else None

        # Calculate area
        area_ha = _calc_area_ha_geojson(geom)

        # Get centroid
        centroid = it.get("centroid") or {}
        lat_val = safe_float(centroid.get("lat"))
        lng_val = safe_float(centroid.get("lng"))

        # Auto-determine grondsoort if coordinates available
        grondsoort = None
        if lat_val and lng_val:
            grondsoort = _auto_determine_grondsoort(lat_val, lng_val)

        # Insert perceel
        c.execute('''
            INSERT INTO percelen
            (id, perceelnaam, oppervlakte, grondsoort, p_al, p_cacl2, nv_gebied,
             latitude, longitude, adres, polygon_coordinates, calculated_area,
             pdok_id, pdok_jaar, pdok_gewascode, pdok_gewasnaam, pdok_status, pdok_category,
             pdok_source, geometry_geojson, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            str(uuid.uuid4()),
            naam,
            area_ha,
            grondsoort,  # Automatically determined
            None, None, 0,  # p_al/p_cacl2/nv_gebied - can be filled in later
            lat_val, lng_val, '',
            polygon_json,
            area_ha,
            pdok_id or None,
            None,  # pdok_jaar
            None,  # pdok_gewascode  
            None,  # pdok_gewasnaam
            None,  # pdok_status
            it.get("category"),
            "PDOK_BRPGewaspercelen_OGC",
            json.dumps(geom, separators=(',', ':')),
            session['user_id']
        ))
        toegevoegd += 1

    conn.commit()
    conn.close()

    if toegevoegd:
        flash(f"{toegevoegd} perceel{'en' if toegevoegd != 1 else ''} via PDOK geïmporteerd. {overgeslagen} overgeslagen.", "success")
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
        data = query_soil_at_point(lat, lng)  # {"soil_text": "...", "raw": {...}}
        soil_text = (data or {}).get("soil_text") or ""
        return jsonify({
            **(data or {}),
            "category": _map_soil_text_to_category(soil_text)
        })
    except Exception as e:
        return jsonify({"error": f"Bodemkaart query fout: {e}"}), 500



@percelen_bp.route('/bodem/layer_name', methods=['GET'])
@login_required
def bodem_layer_name():
    """Get the name of the soil layer for overlay purposes."""
    try:
        name = pick_bodem_layer_name()
        return jsonify({"layer": name})
    except Exception as e:
        return jsonify({"layer": "bodemkaart", "error": str(e)})