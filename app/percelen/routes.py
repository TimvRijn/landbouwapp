from flask import Blueprint, render_template, request, redirect, session, url_for, flash
import uuid
import pandas as pd
import sqlite3
import json
import app.models.database_beheer as db
from app.gebruikers.auth_utils import login_required

percelen_bp = Blueprint(
    'percelen',
    __name__,
    template_folder='templates',
    static_folder='static',
    url_prefix='/percelen'
)

def _parse_coords_or_none(raw: str):
    if not raw:
        return None
    try:
        data = json.loads(raw)
        # Verwacht lijst van dicts [{lat:.., lng:..}, ...]
        if isinstance(data, list) and len(data) >= 3:
            # basis sanity check op keys
            for p in data:
                if not isinstance(p, dict) or 'lat' not in p or 'lng' not in p:
                    return None
            return json.dumps(data, separators=(',', ':'))  # compact opslaan
    except Exception:
        return None
    return None

@percelen_bp.route('/', methods=['GET', 'POST'])
@login_required
def percelen():
    if request.method == 'POST':
        perceelnaam = request.form['perceelnaam'].strip()
        if not perceelnaam:
            flash("Perceelnaam is verplicht.", "danger")
            return redirect(url_for('percelen.percelen'))

        oppervlakte = request.form.get('oppervlakte')  # door kaart berekend (readonly)
        grondsoort = request.form.get('grondsoort')
        p_al = request.form.get('p_al')
        p_cacl2 = request.form.get('p_cacl2')
        nv_gebied = 1 if request.form.get('nv_gebied') == 'ja' else 0

        # Locatie velden (centroid/adres)
        latitude = (request.form.get('latitude') or '').strip()
        longitude = (request.form.get('longitude') or '').strip()
        adres = (request.form.get('adres') or '').strip()

        # Polygon + area (vereist bij toevoegen)
        polygon_raw = (request.form.get('polygon_coordinates') or '').strip()
        polygon_json = _parse_coords_or_none(polygon_raw)
        calculated_area = request.form.get('calculated_area')

        if not polygon_json:
            flash("Teken de perceelgrenzen (polygon is verplicht).", "danger")
            return redirect(url_for('percelen.percelen'))

        # Coördinaten sanity (optioneel, niet hard-blockend)
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

        conn = db.get_connection()
        c = conn.cursor()

        # Uniek per user
        exists = c.execute(
            "SELECT 1 FROM percelen WHERE perceelnaam=? AND user_id=?",
            (perceelnaam, session['user_id'])
        ).fetchone()

        if exists:
            flash(f"Perceel '{perceelnaam}' bestaat al.", "warning")
        else:
            c.execute('''
                INSERT INTO percelen
                (id, perceelnaam, oppervlakte, grondsoort, p_al, p_cacl2, nv_gebied,
                 latitude, longitude, adres, polygon_coordinates, calculated_area, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(uuid.uuid4()),
                perceelnaam,
                oppervlakte,
                grondsoort,
                p_al,
                p_cacl2,
                nv_gebied,
                lat_val,
                lng_val,
                adres,
                polygon_json,
                float(calculated_area) if calculated_area not in (None, '',) else None,
                session['user_id']
            ))
            conn.commit()
            flash(f"Perceel '{perceelnaam}' toegevoegd.", "success")

        conn.close()
        return redirect(url_for('percelen.percelen'))

    # GET
    conn = db.get_connection()
    conn.row_factory = sqlite3.Row
    rows = conn.cursor().execute(
        'SELECT * FROM percelen WHERE user_id=?', (session['user_id'],)
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
        flash(f"Perceel '{perceel['perceelnaam']}' verwijderd.", "success")
    else:
        flash("Niet gevonden of geen toegang.", "danger")
    conn.commit()
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

        oppervlakte = request.form.get('oppervlakte')
        grondsoort = request.form.get('grondsoort')
        p_al = request.form.get('p_al')
        p_cacl2 = request.form.get('p_cacl2')
        nv_gebied = 1 if request.form.get('nv_gebied') == 'ja' else 0

        # Locatie velden (centroid/adres)
        latitude = (request.form.get('latitude') or '').strip()
        longitude = (request.form.get('longitude') or '').strip()
        adres = (request.form.get('adres') or '').strip()

        # Polygon + area (vereist in UI; we valideren opnieuw)
        polygon_raw = (request.form.get('polygon_coordinates') or '').strip()
        polygon_json = _parse_coords_or_none(polygon_raw)
        calculated_area = request.form.get('calculated_area')

        if not polygon_json:
            flash("Teken of behoud geldige perceelgrenzen.", "danger")
            return redirect(url_for('percelen.percelen'))

        # Uniekheid voor andere records van dezelfde user
        exists = c.execute(
            "SELECT 1 FROM percelen WHERE perceelnaam=? AND user_id=? AND id<>?",
            (perceelnaam, session['user_id'], id)
        ).fetchone()
        if exists:
            flash(f"Perceel '{perceelnaam}' bestaat al.", "warning")
            conn.close()
            return redirect(url_for('percelen.percelen'))

        # Coördinaten parse
        lat_val = None
        lng_val = None
        if latitude and longitude:
            try:
                lat_val = float(latitude)
                lng_val = float(longitude)
            except (ValueError, TypeError):
                flash("Ongeldige coördinaten opgegeven.", "danger")
                return redirect(url_for('percelen.percelen'))

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
            oppervlakte,
            grondsoort,
            p_al,
            p_cacl2,
            nv_gebied,
            lat_val,
            lng_val,
            adres,
            polygon_json,
            float(calculated_area) if calculated_area not in (None, '',) else None,
            id,
            session['user_id']
        ))
        conn.commit()
        conn.close()
        flash("Perceel bijgewerkt.", "success")
        return redirect(url_for('percelen.percelen'))

    # GET (optioneel, bij losse edit-pagina)
    perceel = c.execute(
        'SELECT * FROM percelen WHERE id=? AND user_id=?', (id, session['user_id'])
    ).fetchone()
    conn.close()
    if perceel is None:
        flash("Niet gevonden of geen toegang.", "danger")
        return redirect(url_for('percelen.percelen'))

    return render_template('percelen/percelen_edit.html', perceel=perceel)

@percelen_bp.route('/import', methods=['POST'])
@login_required
def import_percelen_excel():
    if 'excel_file' not in request.files:
        flash("Geen bestand gekozen.", "danger")
        return redirect(url_for('percelen.percelen'))

    file = request.files['excel_file']
    try:
        df = pd.read_excel(file)
    except Exception as e:
        flash(f"Excel-bestand niet leesbaar: {e}", "danger")
        return redirect(url_for('percelen.percelen'))

    verplichte_kolommen = ['Perceelnaam']
    for col in verplichte_kolommen:
        if col not in df.columns:
            flash(f"Kolom '{col}' ontbreekt in het Excel-bestand.", "danger")
            return redirect(url_for('percelen.percelen'))

    toegevoegd, overgeslagen = 0, 0
    conn = db.get_connection()
    c = conn.cursor()

    for _, row in df.iterrows():
        perceelnaam = str(row.get('Perceelnaam', '')).strip()
        oppervlakte = row.get('Oppervlakte (ha)')
        grondsoort = row.get('Grondsoort')
        p_al = row.get('P-AL gehalte')
        p_cacl2 = row.get('P-CaCl2 gehalte')
        nv_gebied = row.get('NV-gebied')
        nv_gebied_value = 1 if str(nv_gebied).strip().lower() == 'ja' else 0

        # optionele locatie kolommen (centroid)
        latitude = row.get('Latitude')
        longitude = row.get('Longitude')
        adres = row.get('Adres', '')

        lat_val = None
        lng_val = None
        try:
            if pd.notna(latitude) and pd.notna(longitude):
                lat_val = float(latitude)
                lng_val = float(longitude)
                if not (50.0 <= lat_val <= 54.0 and 3.0 <= lng_val <= 8.0):
                    lat_val = None
                    lng_val = None
        except Exception:
            lat_val = None
            lng_val = None

        if not perceelnaam:
            overgeslagen += 1
            continue

        exists = c.execute(
            "SELECT 1 FROM percelen WHERE perceelnaam=? AND user_id=?",
            (perceelnaam, session['user_id'])
        ).fetchone()

        if exists:
            overgeslagen += 1
            continue

        # Let op: polygon niet uit Excel; zet als NULL, user tekent later
        c.execute('''
            INSERT INTO percelen
            (id, perceelnaam, oppervlakte, grondsoort, p_al, p_cacl2, nv_gebied,
             latitude, longitude, adres, polygon_coordinates, calculated_area, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            str(uuid.uuid4()),
            perceelnaam,
            oppervlakte,
            grondsoort,
            p_al,
            p_cacl2,
            nv_gebied_value,
            lat_val,
            lng_val,
            adres,
            None,            # polygon_coordinates
            None,            # calculated_area
            session['user_id']
        ))
        toegevoegd += 1

    conn.commit()
    conn.close()

    if toegevoegd == 0:
        flash("Geen nieuwe percelen geïmporteerd (alles bestond al of naam ontbrak).", "warning")
    else:
        flash(f"{toegevoegd} perceel{'en' if toegevoegd != 1 else ''} geïmporteerd! {overgeslagen} overgeslagen.", "success")

    return redirect(url_for('percelen.percelen'))
