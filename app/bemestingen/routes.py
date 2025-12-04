# app/blueprints/bemestingen/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session

import uuid
import app.models.database_beheer as db
from app.gebruikers.auth_utils import login_required
import logging
from datetime import datetime

bemestingen_bp = Blueprint(
    'bemestingen',
    __name__,
    template_folder='templates',
    static_folder='static',
    url_prefix='/bemestingen'
)

# Setup logging
logger = logging.getLogger(__name__)

# ============== HELPERS ==============
def is_admin():
    return session.get('is_admin', 0) == 1

def get_effective_user_id():
    """
    Admin kan 'bekijk als' kiezen (session['view_as_user_id']).
    Anders gewoon eigen user_id.
    """
    view_as = session.get('view_as_user_id')
    if is_admin() and view_as:
        return view_as
    return session.get('user_id')


def _safe_float(val, fallback=None):
    """Safely convert value to float with fallback"""
    try:
        if val is None or val == "" or val == "None":
            return fallback
        return float(val)
    except (ValueError, TypeError):
        return fallback

def _safe_int(val, fallback=None):
    """Safely convert value to int with fallback"""
    try:
        if val is None or val == "" or val == "None":
            return fallback
        return int(val)
    except (ValueError, TypeError):
        return fallback
    
def _load_werkingscoefficienten():
    """
    Haal werkingscoëfficiënten op en normaliseer naar:
    { jaar: int|None, meststof: str, toepassing: str, werking: float }
    Werkt met zowel nieuwe als oude tabelstructuur.
    """
    conn = db.get_connection()
    c = conn.cursor()
    data = []
    try:
        # ---- Oude tabel (heeft 'jaar') ----
        try:
            c.execute('''
                SELECT jaar, meststof, toepassing, werking
                FROM stikstof_werkingscoefficient_dierlijk
            ''')
            rows = c.fetchall()
            data = [{
                "jaar": r[0],
                "meststof": r[1] or "",
                "toepassing": r[2] or "",
                "werking": _safe_float(r[3], 0.0) or 0.0
            } for r in rows]
            return data
        except Exception:
            pass

        # ---- Nieuwe tabel (geen 'jaar') ----
        try:
            c.execute('''
                SELECT meststof_naam, toepassing, werking_pct
                FROM werkingscoefficienten
            ''')
            rows = c.fetchall()
            data = [{
                "jaar": None,  # geen jaar in nieuwe tabel
                "meststof": r[0] or "",
                "toepassing": r[1] or "",
                "werking": _safe_float(r[2], 0.0) or 0.0
            } for r in rows]
            return data
        except Exception:
            pass

        logger.warning("Geen werkingscoëfficiënten tabel gevonden")
        return []
    except Exception as e:
        logger.error(f"Fout bij ophalen werkingscoëfficiënten: {e}")
        return []
    finally:
        conn.close()
    

# ============== API ENDPOINTS ==============

@bemestingen_bp.route('/api/werkingscoefficienten', methods=['GET'])
@login_required
def api_werkingscoefficienten():
    """Genormaliseerde API-output voor de frontend utils."""
    try:
        data = _load_werkingscoefficienten()
        return jsonify(data)
    except Exception as e:
        logger.error(f"Fout bij api_werkingscoefficienten: {e}")
        return jsonify([]), 200


# ============== OVERZICHT ==============

@bemestingen_bp.route('/')
@login_required
def bemestingen():
    eff_uid = get_effective_user_id()
    conn = db.get_connection()
    c = conn.cursor()
    try:
        c.execute('''
            SELECT 
                b.id, 
                b.datum, 
                COALESCE(sgm.gewas, 'Onbekend gewas') as gewas,
                g.jaar as jaar,
                COALESCE(p.perceelnaam, 'Onbekend perceel') as perceelnaam,
                COALESCE(bedr.naam, 'Onbekend bedrijf') as bedrijfsnaam,
                COALESCE(u.meststof, 'Onbekende meststof') as meststof,
                b.meststof_id,   
                b.hoeveelheid_kg_ha, 
                b.n_kg_ha, 
                b.p2o5_kg_ha, 
                b.k2o_kg_ha,
                b.werkzame_n_kg_ha,
                b.werkzame_p2o5_kg_ha,
                b.n_dierlijk_kg_ha,
                b.eigen_bedrijf, 
                b.notities,
                COALESCE(u.leverancier, 'Onbekende leverancier') as leverancier
            FROM bemestingen b
            LEFT JOIN gebruiksnormen g   ON b.gebruiksnorm_id = g.id
            LEFT JOIN stikstof_gewassen_normen sgm ON g.gewas_id = sgm.id
            LEFT JOIN percelen p         ON b.perceel_id = p.id
            LEFT JOIN bedrijven bedr     ON b.bedrijf_id = bedr.id
            LEFT JOIN universal_fertilizers u ON b.meststof_id = u.id
            WHERE bedr.user_id = %s
            ORDER BY 
                CASE WHEN b.datum IS NULL THEN 1 ELSE 0 END,
                b.datum DESC
        ''', (eff_uid,))

        bemestingen_rows = c.fetchall()

        # Meststoffen (mag voor iedereen hetzelfde zijn)
        c.execute('SELECT id, meststof, n, p2o5, k2o, toepassing, leverancier FROM universal_fertilizers ORDER BY meststof')
        meststoffen_rows = c.fetchall()

    except Exception as e:
        logger.error(f"Fout bij ophalen bemestingen: {e}")
        flash("Fout bij ophalen bemestingen.", "danger")
        bemestingen_rows, meststoffen_rows = [], []
    finally:
        conn.close()

    werkingscoefficienten = _load_werkingscoefficienten()
    return render_template(
        'bemestingen/bemestingen.html', 
        bemestingen=bemestingen_rows, 
        meststoffen=meststoffen_rows,
        werkingscoefficienten=werkingscoefficienten
    )



# ============== TOEVOEGEN: FORM ==============

@bemestingen_bp.route('/nieuw', methods=['GET'])
@login_required
def bemestingen_nieuw():
    conn = db.get_connection()
    c = conn.cursor()
    try:
        user_id = get_effective_user_id()

        c.execute('''
            SELECT g.id, sgm.gewas, g.jaar, g.bedrijf_id, g.perceel_id, p.oppervlakte
            FROM gebruiksnormen g
            JOIN stikstof_gewassen_normen sgm ON g.gewas_id = sgm.id
            JOIN percelen p ON g.perceel_id = p.id
            WHERE g.user_id = %s
            ORDER BY g.jaar DESC, sgm.gewas
        ''', (user_id,))
        gebruiksnormen = c.fetchall()

        c.execute('SELECT id, naam FROM bedrijven WHERE user_id=%s ORDER BY naam', (user_id,))
        bedrijven = c.fetchall()

        c.execute('''
            SELECT id, perceelnaam, oppervlakte, grondsoort, p_al, p_cacl2,
                   nv_gebied, latitude, longitude, adres, polygon_coordinates, calculated_area
            FROM percelen 
            WHERE user_id=%s
            ORDER BY perceelnaam
        ''', (user_id,))
        percelen = c.fetchall()

        c.execute('SELECT id, meststof, n, p2o5, k2o, toepassing, leverancier FROM universal_fertilizers ORDER BY meststof')
        meststoffen = c.fetchall()
        
        logger.info(f"Data geladen voor user {user_id} - Gebruiksnormen: {len(gebruiksnormen)}, Bedrijven: {len(bedrijven)}, Percelen: {len(percelen)}, Meststoffen: {len(meststoffen)}")
        
    except Exception as e:
        logger.error(f"Fout bij laden formulier data: {e}")
        flash("Fout bij laden formulier data.", "danger")
        gebruiksnormen = []
        bedrijven = []
        percelen = []
        meststoffen = []
    finally:
        conn.close()

    return render_template(
        'bemestingen/bemestingen_nieuw.html',
        gebruiksnormen=gebruiksnormen,
        bedrijven=bedrijven,
        percelen=percelen,
        meststoffen=meststoffen
    )

# ============== TOEVOEGEN: ACTIE ==============

@bemestingen_bp.route('/toevoegen', methods=['POST'])
@login_required
def bemesting_toevoegen():
    """Verwerk nieuwe bemesting"""
    try:
        form = request.form
        
        # Bestaande waarden
        gebruiksnorm_ids = form.getlist('gebruiksnorm_ids[]')
        bedrijf_id = form.get('bedrijf_id')
        meststof_id = form.get('meststof_id')
        datum = form.get('datum')
        hoeveelheid = _safe_float(form.get('hoeveelheid_kg_ha'))
        eigen_bedrijf = 1 if 'eigen_bedrijf' in form else 0
        notities = form.get('notities', "")
        
        # NPK waarden
        n_kg_ha = _safe_float(form.get('n_kg_ha'), 0)
        p2o5_kg_ha = _safe_float(form.get('p2o5_kg_ha'), 0)
        k2o_kg_ha = _safe_float(form.get('k2o_kg_ha'), 0)
        
        # Werkzame waarden
        werkzame_n_kg_ha = _safe_float(form.get('werkzame_n_kg_ha'), 0)
        werkzame_p2o5_kg_ha = _safe_float(form.get('werkzame_p2o5_kg_ha'), 0)  # NIEUW
        n_dierlijk_kg_ha = _safe_float(form.get('n_dierlijk_kg_ha'), 0)
        
        logger.info(f"Werkzame waarden - N: {werkzame_n_kg_ha}, P2O5: {werkzame_p2o5_kg_ha}, N Dierlijk: {n_dierlijk_kg_ha}")

        # Validatie
        if not all([bedrijf_id, gebruiksnorm_ids, meststof_id, datum, hoeveelheid]) or hoeveelheid <= 0:
            flash("Vul alle verplichte velden correct in.", "danger")
            return redirect(url_for('bemestingen.bemestingen_nieuw'))

        conn = db.get_connection()
        c = conn.cursor()

        # Haal meststof info op voor eventuele fallback berekening
        c.execute(
            'SELECT n, p2o5, k2o, toepassing FROM universal_fertilizers WHERE id=%s', 
            (meststof_id,)
        )
        meststof_info = c.fetchone()

        if not meststof_info:
            flash("Geselecteerde meststof niet gevonden.", "danger")
            conn.close()
            return redirect(url_for('bemestingen.bemestingen_nieuw'))

        n_pct, p2o5_pct, k2o_pct, toepassing = meststof_info

        # Voor kunstmest: bereken NPK als het niet door frontend is gedaan
        if not toepassing or (isinstance(toepassing, str) and toepassing.lower() != 'dierlijke mest'):
            if n_kg_ha == 0 and p2o5_kg_ha == 0 and k2o_kg_ha == 0:
                # Fallback berekening
                n_kg_ha = hoeveelheid * (_safe_float(n_pct, 0.0) / 100.0)
                p2o5_kg_ha = hoeveelheid * (_safe_float(p2o5_pct, 0.0) / 100.0)
                k2o_kg_ha = hoeveelheid * (_safe_float(k2o_pct, 0.0) / 100.0)

        # Insert bemesting voor elk geselecteerd perceel
        succesvol_toegevoegd = 0
        for gebruiksnorm_id in gebruiksnorm_ids:
            try:
                # Haal perceel_id op uit gebruiksnorm
                c.execute(
                    'SELECT perceel_id FROM gebruiksnormen WHERE id=%s', 
                    (gebruiksnorm_id,)
                )
                norm_info = c.fetchone()
                
                if not norm_info:
                    logger.warning(f"Gebruiksnorm {gebruiksnorm_id} niet gevonden")
                    continue
                    
                perceel_id = norm_info[0]
                
                # Insert bemesting record
                bemesting_id = str(uuid.uuid4())
                c.execute('''
                    INSERT INTO bemestingen
                    (id, gebruiksnorm_id, bedrijf_id, perceel_id, meststof_id, datum,
                    hoeveelheid_kg_ha, n_kg_ha, p2o5_kg_ha, k2o_kg_ha,
                    werkzame_n_kg_ha, werkzame_p2o5_kg_ha, n_dierlijk_kg_ha, 
                    eigen_bedrijf, notities)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (
                    bemesting_id, gebruiksnorm_id, bedrijf_id, perceel_id, meststof_id,
                    datum, hoeveelheid, n_kg_ha, p2o5_kg_ha, k2o_kg_ha,
                    werkzame_n_kg_ha, werkzame_p2o5_kg_ha, n_dierlijk_kg_ha,
                    eigen_bedrijf, notities
                ))
                
                succesvol_toegevoegd += 1
                logger.info(f"Bemesting toegevoegd voor perceel {perceel_id}")
                
            except Exception as e:
                logger.error(f"Fout bij toevoegen bemesting: {e}")
                continue

        conn.commit()
        conn.close()
        
        if succesvol_toegevoegd > 0:
            flash(f"Bemesting(en) succesvol geregistreerd voor {succesvol_toegevoegd} perceel(en).", "success")
        else:
            flash("Geen bemestingen konden worden toegevoegd. Controleer de gegevens.", "danger")
            
    except Exception as e:
        logger.error(f"Algemene fout bij toevoegen bemesting: {e}")
        flash("Er is een fout opgetreden bij het toevoegen van de bemesting.", "danger")
        
    return redirect(url_for('bemestingen.bemestingen'))

# ============== BEWERKEN ==============

@bemestingen_bp.route('/bewerken/<id>', methods=['GET'])
@login_required
def bewerken_bemesting(id):
    """Formulier voor bewerken bemesting"""
    conn = db.get_connection()
    c = conn.cursor()
    
    try:
        # Haal meststoffen op
        c.execute('SELECT id, meststof, n, p2o5, k2o, toepassing, leverancier FROM universal_fertilizers ORDER BY meststof')
        meststoffen = c.fetchall()
        
        # Haal bemesting op
        c.execute('SELECT * FROM bemestingen WHERE id=%s', (id,))
        bemesting = c.fetchone()
        
        toepassing = None
        if bemesting:
            meststof_id = bemesting[5]  # Aanpassen volgens kolom index
            c.execute('SELECT toepassing FROM universal_fertilizers WHERE id=%s', (meststof_id,))
            row = c.fetchone()
            toepassing = row[0] if row else None
            
    except Exception as e:
        logger.error(f"Fout bij laden bemesting {id}: {e}")
        flash("Bemesting niet gevonden.", "danger")
        bemesting = None
        meststoffen = []
        toepassing = None
    finally:
        conn.close()
    
    if not bemesting:
        return redirect(url_for('bemestingen.bemestingen'))
        
    return render_template(
        'bemestingen/bemestingen.html',
        bemesting=bemesting,
        meststoffen=meststoffen,
        toepassing=toepassing
    )

@bemestingen_bp.route('/bewerken/<id>', methods=['POST'])
@login_required
def bemesting_bewerken(id):
    """Verbeterde versie van bemesting bewerken met validatie en logging"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            flash("Geen geldige sessie.", "danger")
            return redirect(url_for('bemestingen.bemestingen'))

        # Input validation
        datum = request.form.get('datum', '').strip()
        hoeveelheid = _safe_float(request.form.get('hoeveelheid_kg_ha'), 0.0)
        meststof_id = request.form.get('meststof_id', '').strip()
        eigen_bedrijf = 1 if 'eigen_bedrijf' in request.form else 0
        notities = request.form.get('notities', '').strip()
        
        # Basic validation
        if not all([datum, meststof_id]) or hoeveelheid <= 0:
            flash("Vul alle verplichte velden correct in.", "danger")
            return redirect(url_for('bemestingen.bemestingen'))

        # NPK waarden met validatie
        n_kg_ha = _safe_float(request.form.get('n_kg_ha'), 0.0)
        p2o5_kg_ha = _safe_float(request.form.get('p2o5_kg_ha'), 0.0)
        k2o_kg_ha = _safe_float(request.form.get('k2o_kg_ha'), 0.0)
        
        # Werkzame waarden
        werkzame_n_kg_ha = _safe_float(request.form.get('werkzame_n_kg_ha'), 0.0)
        werkzame_p2o5_kg_ha = _safe_float(request.form.get('werkzame_p2o5_kg_ha'), 0.0)
        n_dierlijk_kg_ha = _safe_float(request.form.get('n_dierlijk_kg_ha'), 0.0)

        conn = db.get_connection()
        c = conn.cursor()

        # Security check: controleer of bemesting bij deze gebruiker hoort
        eff_uid = get_effective_user_id()

        c.execute('''
            SELECT b.id, b.meststof_id, b.hoeveelheid_kg_ha
            FROM bemestingen b
            JOIN bedrijven bed ON b.bedrijf_id = bed.id
            WHERE b.id = %s AND bed.user_id = %s
        ''', (id, eff_uid))
        ownership_check = c.fetchone()

        if not ownership_check:
            flash("Bemesting niet gevonden of geen toegang.", "danger")
            conn.close()
            return redirect(url_for('bemestingen.bemestingen'))

        # Valideer meststof bestaat
        c.execute(
            'SELECT id, meststof FROM universal_fertilizers WHERE id = %s', 
            (meststof_id,)
        )
        meststof_check = c.fetchone()
        
        if not meststof_check:
            flash("Geselecteerde meststof is niet geldig.", "danger")
            conn.close()
            return redirect(url_for('bemestingen.bemestingen'))

        # Log before update (oude waarden)
        old_values = f"Hoeveelheid: {ownership_check[2]}, Meststof_ID: {ownership_check[1]}"
        logger.info(f"Bemesting {id} wordt bijgewerkt door user {user_id}. Oude waarden: {old_values}")

        # Datum format handling: converteer dd-mm-yyyy naar yyyy-mm-dd voor database
        formatted_date = datum
        if '-' in datum:
            parts = datum.split('-')
            if len(parts) == 3:
                # Als het dd-mm-yyyy is, converteer naar yyyy-mm-dd
                if len(parts[2]) == 4:  # dd-mm-yyyy
                    formatted_date = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                # Anders aannemen dat het al yyyy-mm-dd is

        # Update bemesting met prepared statement
        update_query = '''
            UPDATE bemestingen SET
                datum = %s,
                hoeveelheid_kg_ha = %s,
                meststof_id = %s,
                n_kg_ha = %s,
                p2o5_kg_ha = %s,
                k2o_kg_ha = %s,
                werkzame_n_kg_ha = %s,
                werkzame_p2o5_kg_ha = %s,
                n_dierlijk_kg_ha = %s,
                eigen_bedrijf = %s,
                notities = %s
            WHERE id = %s
        '''
        
        c.execute(update_query, (
            formatted_date, hoeveelheid, meststof_id, 
            n_kg_ha, p2o5_kg_ha, k2o_kg_ha, 
            werkzame_n_kg_ha, werkzame_p2o5_kg_ha, n_dierlijk_kg_ha,
            eigen_bedrijf, notities, id
        ))
        
        # Check if update was successful
        if c.rowcount == 0:
            flash("Geen wijzigingen doorgevoerd.", "warning")
        else:
            conn.commit()
            flash("Bemesting succesvol bijgewerkt.", "success")
            logger.info(f"Bemesting {id} succesvol bijgewerkt. Nieuwe meststof: {meststof_check[1]}, Hoeveelheid: {hoeveelheid}")
        
        conn.close()
        
    except Exception as e:
        logger.error(f"Fout bij bewerken bemesting {id}: {e}")
        flash("Er is een fout opgetreden bij het bijwerken van de bemesting.", "danger")
        
    return redirect(url_for('bemestingen.bemestingen'))

# ============== VERWIJDEREN ==============

@bemestingen_bp.route('/verwijderen/<id>', methods=['POST'])
@login_required
def bemesting_verwijderen(id):
    """Verwijder bemesting"""
    try:
        conn = db.get_connection()
        c = conn.cursor()
        
        # Check of bemesting bestaat
        eff_uid = get_effective_user_id()
        c.execute('''
            SELECT b.id
            FROM bemestingen b
            JOIN bedrijven bed ON b.bedrijf_id = bed.id
            WHERE b.id = %s AND bed.user_id = %s
        ''', (id, eff_uid))
        existing = c.fetchone()

        if not existing:
            flash("Bemesting niet gevonden of geen toegang.", "danger")
        else:
            c.execute('DELETE FROM bemestingen WHERE id = %s', (id,))
            conn.commit()
            flash("Bemesting verwijderd.", "success")

        conn.close()
        
    except Exception as e:
        logger.error(f"Fout bij verwijderen bemesting {id}: {e}")
        flash("Fout bij verwijderen bemesting.", "danger")
        
    return redirect(url_for('bemestingen.bemestingen'))

# ============== DEBUG/TESTING ENDPOINTS ==============

@bemestingen_bp.route('/debug/data', methods=['GET'])
@login_required  
def debug_data():
    """Debug endpoint om data te controleren"""
    conn = db.get_connection()
    c = conn.cursor()
    
    try:
        # Tel records in verschillende tabellen
        stats = {}
        
        tables = ['gebruiksnormen', 'bedrijven', 'percelen', 'universal_fertilizers', 'bemestingen']
        for table in tables:
            try:
                c.execute(f'SELECT COUNT(*) FROM {table}')
                count = c.fetchone()[0]
                stats[table] = count
            except Exception:
                stats[table] = 'FOUT - tabel bestaat niet'
        
        # Check werkingscoëfficiënten
        try:
            c.execute('SELECT COUNT(*) FROM werkingscoefficienten')
            count = c.fetchone()[0]
            stats['werkingscoefficienten'] = count
        except Exception:
            try:
                c.execute('SELECT COUNT(*) FROM stikstof_werkingscoefficient_dierlijk')
                count = c.fetchone()[0]
                stats['stikstof_werkingscoefficient_dierlijk'] = count
            except Exception:
                stats['werkingscoefficienten'] = 'GEEN TABEL GEVONDEN'
        
        return jsonify({
            'status': 'OK',
            'database_stats': stats,
            'timestamp': str(datetime.now())
        })
        
    except Exception as e:
        return jsonify({
            'status': 'ERROR',
            'error': str(e)
        }), 500
    finally:
        conn.close()

        


@bemestingen_bp.route('/api/init_bemestingen', methods=['GET'])
@login_required
def api_init_bemestingen():
    conn = db.get_connection()
    c = conn.cursor()
    try:
        user_id = get_effective_user_id()

        c.execute(
            'SELECT id, naam FROM bedrijven WHERE user_id=%s ORDER BY naam',
            (user_id,)
        )
        bedrijven = [
            {"id": str(r[0]), "naam": r[1]}
            for r in c.fetchall()
        ]

        # Percelen (alle geometrie)
        c.execute('''
            SELECT id, perceelnaam, oppervlakte, grondsoort, p_al, p_cacl2,
                   nv_gebied, latitude, longitude, adres, polygon_coordinates, calculated_area
            FROM percelen
            WHERE user_id=%s
            ORDER BY perceelnaam
        ''', (user_id,))
        perceel_rows = c.fetchall()

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

        # Meststoffen
        c.execute(
            'SELECT id, meststof, n, p2o5, k2o, toepassing, leverancier FROM universal_fertilizers ORDER BY meststof'
        )
        meststoffen = [
            {
                "id": str(r[0]),
                "naam": r[1] or "",
                "n": float(r[2] or 0),
                "p2o5": float(r[3] or 0),
                "k2o": float(r[4] or 0),
                "toepassing": r[5] or "",
                "leverancier": r[6] or ""
            }
            for r in c.fetchall()
        ]

        # ➜ Gebruiksnormen (voor jaarfilter + mapping perceel → gebruiksnorm)
        c.execute('''
            SELECT g.id, g.perceel_id, g.jaar, sgm.gewas
            FROM gebruiksnormen g
            LEFT JOIN stikstof_gewassen_normen sgm ON g.gewas_id = sgm.id
            WHERE g.user_id = %s
            ORDER BY g.jaar DESC, g.perceel_id
        ''', (user_id,))
        gn_rows = c.fetchall()

        gebruiksnormen = [{
            "id": str(r[0]),
            "perceel_id": str(r[1]),
            "jaar": int(r[2]) if r[2] is not None else None,
            "gewas": r[3] or ""
        } for r in gn_rows]

        return jsonify({
            "status": "OK",
            "percelen": percelen,
            "bedrijven": bedrijven,
            "meststoffen": meststoffen,
            "gebruiksnormen": gebruiksnormen,   # ⬅️ nieuw
            "timestamp": str(datetime.now())
        })

    except Exception as e:
        logger.error(f"Fout in api_init_bemestingen: {e}")
        return jsonify({"status": "ERROR", "error": str(e)}), 500
    finally:
        conn.close()
