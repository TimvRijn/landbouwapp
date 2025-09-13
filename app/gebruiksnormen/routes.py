from flask import Blueprint, render_template, request, redirect, session, url_for, flash, jsonify
import uuid
import app.models.database_beheer as db
from app.gebruiksnormen.bereken_gebruiksnormen import (
    bereken_fosfaatnorm,
    bereken_stikstofnorm,
    bereken_stikstof_dierlijk_kg_ha,
)
from app.gebruikers.auth_utils import login_required
import pandas as pd

gebruiksnormen_bp = Blueprint(
    'gebruiksnormen',
    __name__,
    template_folder='templates',
    static_folder='static',
    url_prefix='/gebruiksnormen'
)


def get_fosfaatnorm_id(c, jaar, type_land, p_cacl2, p_al):
    """Haal fosfaatnorm ID op basis van jaar, type land en bodem parameters"""
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
    """Haal derogatienorm ID op basis van jaar, NV gebied en derogatie status"""
    row = c.execute(
        """
        SELECT id FROM derogatie_normen
        WHERE jaar=? AND nv_gebied=? AND derogatie=?
        LIMIT 1
        """,
        (jaar, nv_gebied, derogatie),
    ).fetchone()
    return row[0] if row else None


@gebruiksnormen_bp.route('/gebruiksnormen', methods=['GET', 'POST'])
@login_required
def gebruiksnormen():
    """Hoofdpagina voor gebruiksnormen beheer"""
    conn = db.get_connection()
    c = conn.cursor()

    # Data voor GET-render (of bij fout teruggeven)
    bedrijven = [
        {"id": str(r[0]), "naam": r[1]}
        for r in c.execute(
            'SELECT id, naam FROM bedrijven WHERE user_id=?', (session['user_id'],)
        ).fetchall()
    ]
    
    percelen = [
        {"id": str(r[0]), "naam": r[1]}
        for r in c.execute(
            'SELECT id, perceelnaam FROM percelen WHERE user_id=?', (session['user_id'],)
        ).fetchall()
    ]
    
    gewassen = [
        {"id": str(r[0]), "naam": f"{r[2]} ({r[1]})", "jaar": r[1]}
        for r in c.execute('SELECT id, jaar, gewas FROM stikstof_gewassen_normen').fetchall()
    ]

    # BELANGRIJK: SELECT * vlak voor c.description gebruiken
    norm_rows = c.execute(
        'SELECT * FROM gebruiksnormen WHERE user_id=?', (session['user_id'],)
    ).fetchall()
    normen = [dict(zip([col[0] for col in c.description], row)) for row in norm_rows]

    if request.method == 'POST':
        try:
            bedrijf_id = request.form['bedrijf_id']
            perceel_id = request.form['perceel_id']
            gewas_id = request.form['gewas_id']
            jaar = int(request.form['jaar'])

            # Haal perceel gegevens op
            perceel = c.execute(
                'SELECT grondsoort, p_al, p_cacl2, nv_gebied FROM percelen WHERE id=?',
                (perceel_id,),
            ).fetchone()
            if not perceel:
                conn.close()
                return jsonify({"success": False, "message": "Perceel niet gevonden"}), 400

            grondsoort, p_al, p_cacl2, nv_gebied = perceel
            
            # Haal gewas naam op
            gewas_row = c.execute(
                'SELECT gewas FROM stikstof_gewassen_normen WHERE id=?', (gewas_id,)
            ).fetchone()
            gewas_naam = gewas_row[0].lower() if gewas_row else ''

            # Derogatie altijd uit formulier nemen
            derogatie = int(request.form.get('derogatie', 0))
            type_land = 'grasland' if 'gras' in gewas_naam else 'bouwland'

            # Haal norm IDs op
            fosfaatnorm_id = get_fosfaatnorm_id(c, jaar, type_land, p_cacl2, p_al)
            derogatienorm_id = get_derogatienorm_id(c, jaar, nv_gebied, derogatie)

            # Bereken normen
            stikstof_norm = bereken_stikstofnorm(gewas_id, perceel_id, jaar)
            fosfaat_norm = bereken_fosfaatnorm(perceel_id, gewas_id, jaar)
            stikstof_dierlijk = bereken_stikstof_dierlijk_kg_ha(
                bedrijf_id, perceel_id, gewas_id, derogatie, jaar
            )

            if stikstof_norm is None or fosfaat_norm is None:
                raise Exception(
                    "Stikstof- of fosfaatnorm niet gevonden voor gekozen perceel/jaar/soort."
                )

            # Insert nieuwe gebruiksnorm
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
                    derogatie, session['user_id']
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
    """Bewerk bestaande gebruiksnorm"""
    conn = db.get_connection()
    c = conn.cursor()

    try:
        bedrijf_id = request.form['bedrijf_id']
        perceel_id = request.form['perceel_id']
        gewas_id = request.form['gewas_id']
        jaar = int(request.form['jaar'])

        # Haal perceel gegevens op
        perceel = c.execute(
            'SELECT grondsoort, p_al, p_cacl2, nv_gebied FROM percelen WHERE id=?', 
            (perceel_id,)
        ).fetchone()
        grondsoort, p_al, p_cacl2, nv_gebied = perceel if perceel else ('', 0, 0, 0)

        # Haal gewas naam op
        gewas_row = c.execute(
            'SELECT gewas FROM stikstof_gewassen_normen WHERE id=?', (gewas_id,)
        ).fetchone()
        gewas_naam = gewas_row[0].lower() if gewas_row else ''

        # Derogatie en type land bepalen
        derogatie = int(request.form.get('derogatie', 0))
        type_land = 'grasland' if 'gras' in gewas_naam else 'bouwland'

        # Herbereken alle norm waarden
        fosfaatnorm_id = get_fosfaatnorm_id(c, jaar, type_land, p_cacl2, p_al)
        derogatienorm_id = get_derogatienorm_id(c, jaar, nv_gebied, derogatie)
        stikstof_norm = bereken_stikstofnorm(gewas_id, perceel_id, jaar)
        fosfaat_norm = bereken_fosfaatnorm(perceel_id, gewas_id, jaar)
        stikstof_dierlijk = bereken_stikstof_dierlijk_kg_ha(
            bedrijf_id, perceel_id, gewas_id, derogatie, jaar
        )

        # Update gebruiksnorm
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
                norm_id, session['user_id'],
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
    """Verwijder gebruiksnorm"""
    conn = db.get_connection()
    c = conn.cursor()
    try:
        c.execute(
            'DELETE FROM gebruiksnormen WHERE id=? AND user_id=?', 
            (norm_id, session['user_id'])
        )
        conn.commit()
        return redirect(url_for('gebruiksnormen.gebruiksnormen'))
    except Exception as e:
        conn.rollback()
        flash(f"Fout bij verwijderen: {str(e)}", "danger")
        return redirect(url_for('gebruiksnormen.gebruiksnormen'))
    finally:
        conn.close()


@gebruiksnormen_bp.route('/import_gebruiksnormen_excel', methods=['POST'])
@login_required
def import_gebruiksnormen_excel():
    """Import gebruiksnormen vanuit Excel bestand"""
    if 'excel_file' not in request.files:
        return "Geen bestand gekozen", 400

    file = request.files['excel_file']
    try:
        df = pd.read_excel(file)
    except Exception as e:
        return f"Fout bij lezen Excel bestand: {str(e)}", 400

    conn = db.get_connection()
    c = conn.cursor()
    imported_count = 0
    skipped = []

    try:
        for _, row in df.iterrows():
            bedrijf_naam = str(row.get('Bedrijfsnaam', '')).strip()
            perceel_naam = str(row.get('Perceelnaam', '')).strip()
            gewas_naam = str(row.get('Gewasnaam', '')).strip()
            jaar = row.get('Jaar')

            # Basis validatie
            if not bedrijf_naam or not perceel_naam or not gewas_naam or pd.isna(jaar):
                skipped.append({
                    'bedrijf': bedrijf_naam, 'perceel': perceel_naam, 
                    'gewas': gewas_naam, 'jaar': jaar,
                    'reden': 'Ontbrekende data'
                })
                continue

            jaar = int(jaar)
            
            # Zoek entiteiten in database
            bedrijf = c.execute(
                "SELECT id FROM bedrijven WHERE naam=? AND user_id=?",
                (bedrijf_naam, session['user_id']),
            ).fetchone()
            
            perceel = c.execute(
                "SELECT id, grondsoort, p_al, p_cacl2, nv_gebied FROM percelen WHERE perceelnaam=? AND user_id=?",
                (perceel_naam, session['user_id']),
            ).fetchone()
            
            gewas = c.execute(
                "SELECT id, MAX(jaar), gewas FROM stikstof_gewassen_normen WHERE gewas=? AND jaar <= ?",
                (gewas_naam, jaar),
            ).fetchone()

            # Controleer of alle entiteiten gevonden zijn
            if not (bedrijf and perceel and gewas and gewas[0]):
                skipped.append({
                    'bedrijf': bedrijf_naam,
                    'perceel': perceel_naam,
                    'gewas': gewas_naam,
                    'jaar': jaar,
                    'reden': 'Geen match in database',
                })
                continue

            # Extract data
            bedrijf_id = bedrijf[0]
            perceel_id, grondsoort, p_al, p_cacl2, nv_gebied = perceel
            gewas_id, _, gewas_str = gewas

            # Derogatie en normen berekenen
            derogatie = int(row.get('Derogatie', 0)) if 'Derogatie' in row else 0
            type_land = 'grasland' if 'gras' in gewas_str.lower() else 'bouwland'

            fosfaatnorm_id = get_fosfaatnorm_id(c, jaar, type_land, p_cacl2, p_al)
            derogatienorm_id = get_derogatienorm_id(c, jaar, nv_gebied, derogatie)
            stikstof_norm = bereken_stikstofnorm(gewas_id, perceel_id, jaar)
            fosfaat_norm = bereken_fosfaatnorm(perceel_id, gewas_id, jaar)
            stikstof_dierlijk = bereken_stikstof_dierlijk_kg_ha(
                bedrijf_id, perceel_id, gewas_id, derogatie, jaar
            )

            # Valideer berekende normen
            if stikstof_norm is None or fosfaat_norm is None:
                skipped.append({
                    'bedrijf': bedrijf_naam,
                    'perceel': perceel_naam,
                    'gewas': gewas_naam,
                    'jaar': jaar,
                    'reden': 'Stikstof- of fosfaatnorm niet gevonden',
                })
                continue

            # Insert gebruiksnorm
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
                    derogatie, session['user_id']
                ),
            )
            imported_count += 1

        conn.commit()
        
        # Bouw response message
        msg = f"{imported_count} gebruiksnormen geïmporteerd."
        if skipped:
            msg += f" {len(skipped)} rijen overgeslagen."
            if len(skipped) <= 5:
                msg += f" Details: {skipped}"
            else:
                msg += f" Eerste 5: {skipped[:5]}"
        
        return msg
        
    except Exception as e:
        conn.rollback()
        return f"Fout tijdens import: {str(e)}", 500
    finally:
        conn.close()


@gebruiksnormen_bp.route('/api/init_gebruiksnormen')
@login_required
def api_init_gebruiksnormen():
    """API endpoint voor initiële data voor frontend - AANGEPAST VOOR KAART FUNCTIONALITEIT"""
    conn = db.get_connection()
    c = conn.cursor()

    try:
        user_id = session['user_id']

        # Bedrijven
        bedrijven = [
            {"id": str(r[0]), "naam": r[1]}
            for r in c.execute(
                'SELECT id, naam FROM bedrijven WHERE user_id=?', (user_id,)
            ).fetchall()
        ]
        
        # BELANGRIJK: Percelen met ALLE velden voor kaart functionaliteit
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
                "naam": r[1],  # perceelnaam
                "perceelnaam": r[1],  # alias voor consistentie
                "oppervlakte": r[2],
                "grondsoort": r[3],
                "p_al": r[4],
                "p_cacl2": r[5],
                "nv_gebied": r[6],
                "latitude": r[7],
                "longitude": r[8],
                "adres": r[9],
                "polygon_coordinates": r[10],  # KRITIEK voor kaart functionaliteit!
                "calculated_area": r[11]
            })
        
        # Gewassen
        gewassen = [
            {"id": str(r[0]), "naam": f"{r[2]} ({r[1]})", "jaar": r[1]}
            for r in c.execute(
                'SELECT id, jaar, gewas FROM stikstof_gewassen_normen ORDER BY jaar DESC, gewas'
            ).fetchall()
        ]

        # BELANGRIJK: SELECT * direct voor c.description om kolom mapping te krijgen
        norm_rows = c.execute(
            'SELECT * FROM gebruiksnormen WHERE user_id=? ORDER BY jaar DESC', 
            (user_id,)
        ).fetchall()
        normen = [dict(zip([col[0] for col in c.description], row)) for row in norm_rows]

        return jsonify({
            'success': True,
            'bedrijven': bedrijven,
            'percelen': percelen,  # Inclusief polygon_coordinates voor kaart
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


# Extra API endpoints voor debugging (optioneel)
@gebruiksnormen_bp.route('/api/debug/percelen')
@login_required  
def debug_percelen():
    """Debug endpoint om perceel data te controleren"""
    conn = db.get_connection()
    c = conn.cursor()
    
    try:
        user_id = session['user_id']
        
        # Check percelen met polygon data
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
    """Debug endpoint voor algemene statistieken"""
    conn = db.get_connection()
    c = conn.cursor()
    
    try:
        user_id = session['user_id']
        
        stats = {}
        
        # Tel verschillende entiteiten
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