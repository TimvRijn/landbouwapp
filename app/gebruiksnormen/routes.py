from flask import Blueprint, render_template, request, redirect, session, url_for, flash, jsonify
import uuid
import pandas as pd

import app.models.database_beheer as db
from app.gebruiksnormen.bereken_gebruiksnormen import (
    bereken_fosfaatnorm,
    bereken_stikstofnorm,
    bereken_stikstof_dierlijk_kg_ha,
)
from app.gebruikers.auth_utils import login_required, effective_user_id

gebruiksnormen_bp = Blueprint(
    'gebruiksnormen',
    __name__,
    template_folder='templates',
    static_folder='static',
    url_prefix='/gebruiksnormen'
)

# ----------------- Helpers -----------------
def ensure_indexes(conn):
    """Zachte migratie: maak unieke index als deze nog niet bestaat."""
    c = conn.cursor()
    c.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uniq_gebruiksnormen_user_perceel_jaar
        ON gebruiksnormen (user_id, perceel_id, jaar)
    """)
    conn.commit()

def get_fosfaatnorm_id(c, jaar, type_land, p_cacl2, p_al):
    row = c.execute(
        """
        SELECT id FROM fosfaat_normen
        WHERE jaar=? AND type_land=?
          AND ? >= p_cacl2_van AND ? <= p_cacl2_tot
          AND ? >= p_al_van   AND ? <= p_al_tot
        LIMIT 1
        """,
        (jaar, type_land, p_cacl2, p_cacl2, p_al, p_al),
    ).fetchone()
    return row[0] if row else None

def get_derogatienorm_id(c, jaar, nv_gebied, derogatie):
    row = c.execute(
        """
        SELECT id FROM derogatie_normen
        WHERE jaar=? AND nv_gebied=? AND derogatie=?
        LIMIT 1
        """,
        (jaar, nv_gebied, derogatie),
    ).fetchone()
    return row[0] if row else None

# ----------------- Routes -----------------
@gebruiksnormen_bp.route('/gebruiksnormen', methods=['GET', 'POST'])
@login_required
def gebruiksnormen():
    """Hoofdpagina voor gebruiksnormen beheer (lijst + toevoegen)."""
    conn = db.get_connection()
    ensure_indexes(conn)
    c = conn.cursor()

    eff_uid = effective_user_id()

    # Data voor render (GET of na fout)
    bedrijven = [
        {"id": str(r[0]), "naam": r[1]}
        for r in c.execute(
            'SELECT id, naam FROM bedrijven WHERE user_id=? ORDER BY naam', (eff_uid,)
        ).fetchall()
    ]

    percelen = [
        {"id": str(r[0]), "naam": r[1]}
        for r in c.execute(
            'SELECT id, perceelnaam FROM percelen WHERE user_id=? ORDER BY perceelnaam', (eff_uid,)
        ).fetchall()
    ]

    gewassen = [
        {"id": str(r[0]), "naam": f"{r[2]} ({r[1]})", "jaar": r[1]}
        for r in c.execute('SELECT id, jaar, gewas FROM stikstof_gewassen_normen').fetchall()
    ]

    norm_rows = c.execute(
        'SELECT * FROM gebruiksnormen WHERE user_id=? ORDER BY jaar DESC', (eff_uid,)
    ).fetchall()
    normen = [dict(zip([col[0] for col in c.description], row)) for row in norm_rows]

    if request.method == 'POST':
        try:
            bedrijf_id = request.form['bedrijf_id']
            perceel_id = request.form['perceel_id']
            gewas_id = request.form['gewas_id']
            jaar = int(request.form['jaar'])
            derogatie = int(request.form.get('derogatie', 0))

            # Eigendomschecks
            own_bedrijf = c.execute(
                'SELECT 1 FROM bedrijven WHERE id=? AND user_id=?',
                (bedrijf_id, eff_uid)
            ).fetchone()
            own_perceel = c.execute(
                'SELECT 1 FROM percelen WHERE id=? AND user_id=?',
                (perceel_id, eff_uid)
            ).fetchone()
            if not own_bedrijf or not own_perceel:
                conn.close()
                return jsonify({"success": False, "message": "Geen toegang tot dit bedrijf/perceel"}), 403

            # Voorkom dubbele norm (zelfde user/perceel/jaar)
            dup = c.execute(
                'SELECT 1 FROM gebruiksnormen WHERE user_id=? AND perceel_id=? AND jaar=?',
                (eff_uid, perceel_id, jaar)
            ).fetchone()
            if dup:
                conn.close()
                return jsonify({"success": False, "message": "Er bestaat al een norm voor dit perceel en jaar"}), 409

            # Perceel + gewas ophalen
            perceel = c.execute(
                'SELECT grondsoort, p_al, p_cacl2, nv_gebied FROM percelen WHERE id=?',
                (perceel_id,)
            ).fetchone()
            if not perceel:
                conn.close()
                return jsonify({"success": False, "message": "Perceel niet gevonden"}), 400
            grondsoort, p_al, p_cacl2, nv_gebied = perceel

            gewas_row = c.execute(
                'SELECT gewas FROM stikstof_gewassen_normen WHERE id=?', (gewas_id,)
            ).fetchone()
            gewas_naam = (gewas_row[0] if gewas_row else '').lower()
            type_land = 'grasland' if 'gras' in gewas_naam else 'bouwland'

            # Norm-IDs
            fosfaatnorm_id = get_fosfaatnorm_id(c, jaar, type_land, p_cacl2, p_al)
            derogatienorm_id = get_derogatienorm_id(c, jaar, nv_gebied, derogatie)

            # Waarden berekenen
            stikstof_norm = bereken_stikstofnorm(gewas_id, perceel_id, jaar)
            fosfaat_norm = bereken_fosfaatnorm(perceel_id, gewas_id, jaar)
            stikstof_dierlijk = bereken_stikstof_dierlijk_kg_ha(
                bedrijf_id, perceel_id, gewas_id, derogatie, jaar
            )

            if stikstof_norm is None or fosfaat_norm is None:
                raise Exception("Stikstof- of fosfaatnorm niet gevonden voor gekozen perceel/jaar/soort.")

            # Insert
            c.execute(
                '''
                INSERT INTO gebruiksnormen (
                    id, jaar, bedrijf_id, perceel_id, gewas_id,
                    fosfaatnorm_id, derogatienorm_id,
                    stikstof_norm_kg_ha, stikstof_dierlijk_kg_ha, fosfaat_norm_kg_ha,
                    derogatie, user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    str(uuid.uuid4()), jaar, bedrijf_id, perceel_id, gewas_id,
                    fosfaatnorm_id, derogatienorm_id,
                    stikstof_norm, stikstof_dierlijk, fosfaat_norm,
                    derogatie, eff_uid
                ),
            )
            conn.commit()
            return jsonify({"success": True, "message": "Gebruiksnorm toegevoegd."})

        except Exception as e:
            conn.rollback()
            return jsonify({"success": False, "message": str(e)}), 400
        finally:
            conn.close()

    conn.close()
    return render_template(
        'gebruiksnormen/gebruiksnormen.html',
        bedrijven=bedrijven,
        percelen=percelen,
        gewassen=gewassen,
        normen=normen,
    )

@gebruiksnormen_bp.route('/gebruiksnormen_edit/<norm_id>', methods=['POST'])
@login_required
def gebruiksnormen_edit(norm_id):
    """Bewerk bestaande gebruiksnorm."""
    conn = db.get_connection()
    ensure_indexes(conn)
    c = conn.cursor()
    eff_uid = effective_user_id()

    try:
        bedrijf_id = request.form['bedrijf_id']
        perceel_id = request.form['perceel_id']
        gewas_id = request.form['gewas_id']
        jaar = int(request.form['jaar'])
        derogatie = int(request.form.get('derogatie', 0))

        # Norm bestaat en is van deze (effective) user?
        exists = c.execute(
            'SELECT 1 FROM gebruiksnormen WHERE id=? AND user_id=?',
            (norm_id, eff_uid)
        ).fetchone()
        if not exists:
            conn.close()
            return jsonify({"success": False, "message": "Norm niet gevonden of geen toegang"}), 404

        # Eigendomschecks voor nieuwe waarden
        own_bedrijf = c.execute(
            'SELECT 1 FROM bedrijven WHERE id=? AND user_id=?',
            (bedrijf_id, eff_uid)
        ).fetchone()
        own_perceel = c.execute(
            'SELECT 1 FROM percelen WHERE id=? AND user_id=?',
            (perceel_id, eff_uid)
        ).fetchone()
        if not own_bedrijf or not own_perceel:
            conn.close()
            return jsonify({"success": False, "message": "Geen toegang tot dit bedrijf/perceel"}), 403

        # Perceel + gewas ophalen
        perceel = c.execute(
            'SELECT grondsoort, p_al, p_cacl2, nv_gebied FROM percelen WHERE id=?',
            (perceel_id,)
        ).fetchone()
        grondsoort, p_al, p_cacl2, nv_gebied = perceel if perceel else ('', 0, 0, 0)

        gewas_row = c.execute(
            'SELECT gewas FROM stikstof_gewassen_normen WHERE id=?', (gewas_id,)
        ).fetchone()
        gewas_naam = (gewas_row[0] if gewas_row else '').lower()
        type_land = 'grasland' if 'gras' in gewas_naam else 'bouwland'

        # Norm-IDs + waarden
        fosfaatnorm_id = get_fosfaatnorm_id(c, jaar, type_land, p_cacl2, p_al)
        derogatienorm_id = get_derogatienorm_id(c, jaar, nv_gebied, derogatie)
        stikstof_norm = bereken_stikstofnorm(gewas_id, perceel_id, jaar)
        fosfaat_norm = bereken_fosfaatnorm(perceel_id, gewas_id, jaar)
        stikstof_dierlijk = bereken_stikstof_dierlijk_kg_ha(
            bedrijf_id, perceel_id, gewas_id, derogatie, jaar
        )

        c.execute(
            '''
            UPDATE gebruiksnormen SET
                jaar=?, bedrijf_id=?, perceel_id=?, gewas_id=?,
                fosfaatnorm_id=?, derogatienorm_id=?,
                stikstof_norm_kg_ha=?, stikstof_dierlijk_kg_ha=?, fosfaat_norm_kg_ha=?, 
                derogatie=?
            WHERE id=? AND user_id=?
            ''',
            (
                jaar, bedrijf_id, perceel_id, gewas_id,
                fosfaatnorm_id, derogatienorm_id,
                stikstof_norm, stikstof_dierlijk, fosfaat_norm, derogatie,
                norm_id, eff_uid,
            ),
        )
        conn.commit()
        return jsonify({"success": True, "message": "Gebruiksnorm aangepast."})

    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 400
    finally:
        conn.close()

@gebruiksnormen_bp.route('/gebruiksnormen_delete/<norm_id>', methods=['POST'])
@login_required
def gebruiksnormen_delete(norm_id):
    """Verwijder gebruiksnorm."""
    conn = db.get_connection()
    ensure_indexes(conn)
    c = conn.cursor()
    try:
        c.execute(
            'DELETE FROM gebruiksnormen WHERE id=? AND user_id=?',
            (norm_id, effective_user_id())
        )
        conn.commit()
        return redirect(url_for('gebruiksnormen.gebruiksnormen'))
    except Exception as e:
        conn.rollback()
        flash(f"Fout bij verwijderen: {str(e)}", "danger")
        return redirect(url_for('gebruiksnormen.gebruiksnormen'))
    finally:
        conn.close()


@gebruiksnormen_bp.route('/api/init_gebruiksnormen')
@login_required
def api_init_gebruiksnormen():
    """API voor initiële data tbv frontend (incl. polygonen voor kaart)."""
    conn = db.get_connection()
    c = conn.cursor()

    try:
        user_id = effective_user_id()

        bedrijven = [
            {"id": str(r[0]), "naam": r[1]}
            for r in c.execute(
                'SELECT id, naam FROM bedrijven WHERE user_id=? ORDER BY naam', (user_id,)
            ).fetchall()
        ]

        perceel_rows = c.execute('''
            SELECT id, perceelnaam, oppervlakte, grondsoort, p_al, p_cacl2,
                   nv_gebied, latitude, longitude, adres, polygon_coordinates, calculated_area
            FROM percelen
            WHERE user_id=?
            ORDER BY perceelnaam
        ''', (user_id,)).fetchall()

        percelen = []
        for r in perceel_rows:
            percelen.append({
                "id": str(r[0]),
                "naam": r[1],
                "perceelnaam": r[1],
                "oppervlakte": r[2],
                "grondsoort": r[3],
                "p_al": r[4],
                "p_cacl2": r[5],
                "nv_gebied": r[6],
                "latitude": r[7],
                "longitude": r[8],
                "adres": r[9],
                "polygon_coordinates": r[10],
                "calculated_area": r[11]
            })

        gewassen = [
            {"id": str(r[0]), "naam": f"{r[2]} ({r[1]})", "jaar": r[1]}
            for r in c.execute(
                'SELECT id, jaar, gewas FROM stikstof_gewassen_normen ORDER BY jaar DESC, gewas'
            ).fetchall()
        ]

        norm_rows = c.execute(
            'SELECT * FROM gebruiksnormen WHERE user_id=? ORDER BY jaar DESC',
            (user_id,)
        ).fetchall()
        normen = [dict(zip([col[0] for col in c.description], row)) for row in norm_rows]

        return jsonify({
            'success': True,
            'bedrijven': bedrijven,
            'percelen': percelen,
            'gewassen': gewassen,
            'normen': normen,
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Fout bij ophalen data: {str(e)}'
        }), 500
    finally:
        conn.close()

# ---- Optionele debug endpoints (ongewijzigd) ----
@gebruiksnormen_bp.route('/api/debug/percelen')
@login_required
def debug_percelen():
    conn = db.get_connection()
    c = conn.cursor()
    try:
        user_id = effective_user_id()
        percelen_with_polygons = c.execute('''
            SELECT id, perceelnaam, 
                   CASE WHEN polygon_coordinates IS NOT NULL THEN 'YES' ELSE 'NO' END as has_polygon,
                   LENGTH(polygon_coordinates) as polygon_length
            FROM percelen 
            WHERE user_id=?
        ''', (user_id,)).fetchall()
        return jsonify({
            'total_percelen': len(percelen_with_polygons),
            'percelen_data': [
                {
                    'id': r[0],
                    'naam': r[1],
                    'has_polygon': r[2],
                    'polygon_size': r[3]
                }
                for r in percelen_with_polygons
            ]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@gebruiksnormen_bp.route('/api/debug/stats')
@login_required
def debug_stats():
    conn = db.get_connection()
    c = conn.cursor()
    try:
        user_id = effective_user_id()
        stats = {}
        tables_to_check = [
            ('bedrijven', 'WHERE user_id=?', (user_id,)),
            ('percelen', 'WHERE user_id=?', (user_id,)),
            ('gebruiksnormen', 'WHERE user_id=?', (user_id,)),
            ('stikstof_gewassen_normen', '', ()),
        ]
        for table, where_clause, params in tables_to_check:
            try:
                query = f'SELECT COUNT(*) FROM {table} {where_clause}'
                count = c.execute(query, params).fetchone()[0]
                stats[table] = count
            except Exception as e:
                stats[table] = f'ERROR: {str(e)}'
        return jsonify({
            'user_id': user_id,
            'stats': stats,
            'timestamp': str(pd.Timestamp.now())
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()
