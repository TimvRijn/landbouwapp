# app/blueprints/bemestingen/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
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

# ============== API ENDPOINTS ==============

@bemestingen_bp.route('/api/werkingscoefficienten', methods=['GET'])
@login_required
def api_werkingscoefficienten():
    """
    API endpoint voor werkingscoëfficiënten.
    Verwacht een tabel 'werkingscoefficienten' of 'stikstof_werkingscoefficient_dierlijk'.
    """
    conn = db.get_connection()
    c = conn.cursor()
    try:
        # Probeer eerst de nieuwe tabel structuur
        try:
            rows = c.execute('''
                SELECT id, meststof_naam, toepassing, gewas, grondsoort, maand_van, maand_tot, werking_pct
                FROM werkingscoefficienten
            ''').fetchall()
            data = [{
                "id": r[0],
                "meststof_naam": r[1],
                "toepassing": r[2] or "",
                "gewas": r[3] or "",
                "grondsoort": r[4] or "",
                "maand_van": r[5],
                "maand_tot": r[6],
                "werking_pct": _safe_float(r[7], 0),
            } for r in rows]
        except Exception:
            # Fallback naar oude tabel structuur
            try:
                rows = c.execute('''
                    SELECT jaar, meststof, toepassing, werking
                    FROM stikstof_werkingscoefficient_dierlijk
                ''').fetchall()
                data = [{
                    "jaar": r[0],
                    "meststof": r[1],
                    "toepassing": r[2] or "",
                    "werking": _safe_float(r[3], 0)
                } for r in rows]
            except Exception:
                logger.warning("Geen werkingscoëfficiënten tabel gevonden")
                data = []
                
    except Exception as e:
        logger.error(f"Fout bij ophalen werkingscoëfficiënten: {e}")
        data = []
    finally:
        conn.close()
    
    return jsonify(data)

# ============== OVERZICHT ==============

@bemestingen_bp.route('/')
@login_required
def bemestingen():
    """Overzicht van alle bemestingen - verbeterde versie die alle records toont"""
    conn = db.get_connection()
    c = conn.cursor()
    
    try:
        # Gebruik LEFT JOINs om alle bemestingen te tonen, ook als er geen relaties zijn
        c.execute('''
            SELECT 
                b.id, 
                b.datum, 
                COALESCE(sgm.gewas, 'Onbekend gewas') as gewas,
                COALESCE(g.jaar, 'Onbekend jaar') as jaar,
                COALESCE(p.perceelnaam, 'Onbekend perceel') as perceelnaam,
                COALESCE(bedr.naam, 'Onbekend bedrijf') as bedrijfsnaam,
                COALESCE(u.meststof, 'Onbekende meststof') as meststof,
                b.hoeveelheid_kg_ha, 
                b.n_kg_ha, 
                b.p2o5_kg_ha, 
                b.k2o_kg_ha, 
                b.eigen_bedrijf, 
                b.notities
            FROM bemestingen b
            LEFT JOIN gebruiksnormen g ON b.gebruiksnorm_id = g.id
            LEFT JOIN stikstof_gewassen_normen sgm ON g.gewas_id = sgm.id
            LEFT JOIN percelen p ON b.perceel_id = p.id
            LEFT JOIN bedrijven bedr ON b.bedrijf_id = bedr.id
            LEFT JOIN universal_fertilizers u ON b.meststof_id = u.id
            ORDER BY 
                CASE WHEN b.datum IS NULL THEN 1 ELSE 0 END,
                b.datum DESC
        ''')
        bemestingen = c.fetchall()
        
        # Debug informatie
        total_count = c.execute('SELECT COUNT(*) FROM bemestingen').fetchone()[0]
        logger.info(f"Totaal bemestingen in database: {total_count}")
        logger.info(f"Bemestingen getoond na JOIN: {len(bemestingen)}")
        
        # Als er een verschil is, log dit
        if total_count != len(bemestingen):
            logger.warning(f"VERSCHIL GEVONDEN: {total_count - len(bemestingen)} bemestingen worden niet getoond door ontbrekende relaties!")
            
            # Zoek bemestingen zonder relaties
            c.execute('''
                SELECT b.id, b.datum, b.gebruiksnorm_id, b.perceel_id, b.bedrijf_id, b.meststof_id
                FROM bemestingen b
                LEFT JOIN gebruiksnormen g ON b.gebruiksnorm_id = g.id
                LEFT JOIN percelen p ON b.perceel_id = p.id  
                LEFT JOIN bedrijven bedr ON b.bedrijf_id = bedr.id
                LEFT JOIN universal_fertilizers u ON b.meststof_id = u.id
                WHERE g.id IS NULL OR p.id IS NULL OR bedr.id IS NULL OR u.id IS NULL
            ''')
            orphaned = c.fetchall()
            
            for orphan in orphaned:
                logger.warning(f"Bemesting {orphan[0]} heeft ontbrekende relaties: gebruiksnorm_id={orphan[2]}, perceel_id={orphan[3]}, bedrijf_id={orphan[4]}, meststof_id={orphan[5]}")
        
        # Meststoffen voor modal
        c.execute('SELECT id, meststof, n, p2o5, k2o, toepassing FROM universal_fertilizers ORDER BY meststof')
        meststoffen = c.fetchall()
        
    except Exception as e:
        logger.error(f"Fout bij ophalen bemestingen: {e}")
        flash("Fout bij ophalen bemestingen.", "danger")
        bemestingen = []
        meststoffen = []
    finally:
        conn.close()
    
    return render_template('bemestingen/bemestingen.html', 
                         bemestingen=bemestingen, 
                         meststoffen=meststoffen)

# ============== TOEVOEGEN: FORM ==============

@bemestingen_bp.route('/nieuw', methods=['GET'])
@login_required
def bemestingen_nieuw():
    """Formulier voor nieuwe bemesting"""
    conn = db.get_connection()
    c = conn.cursor()
    
    try:
        # Haal gebruiksnormen op met gewas info
        c.execute('''
            SELECT g.id, sgm.gewas, g.jaar, g.bedrijf_id, g.perceel_id, p.oppervlakte
            FROM gebruiksnormen g
            JOIN stikstof_gewassen_normen sgm ON g.gewas_id = sgm.id
            JOIN percelen p ON g.perceel_id = p.id
            ORDER BY g.jaar DESC, sgm.gewas
        ''')
        gebruiksnormen = c.fetchall()
        
        # Haal bedrijven op
        c.execute('SELECT id, naam FROM bedrijven ORDER BY naam')
        bedrijven = c.fetchall()
        
        # Haal percelen op
        c.execute('SELECT id, perceelnaam, oppervlakte, grondsoort FROM percelen ORDER BY perceelnaam')
        percelen = c.fetchall()
        
        # Haal meststoffen op
        c.execute('SELECT id, meststof, n, p2o5, k2o, toepassing FROM universal_fertilizers ORDER BY meststof')
        meststoffen = c.fetchall()
        
        logger.info(f"Data geladen - Gebruiksnormen: {len(gebruiksnormen)}, Bedrijven: {len(bedrijven)}, Percelen: {len(percelen)}, Meststoffen: {len(meststoffen)}")
        
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
        
        # Haal form data op
        gebruiksnorm_ids = form.getlist('gebruiksnorm_ids[]')
        bedrijf_id = form.get('bedrijf_id')
        meststof_id = form.get('meststof_id')
        datum = form.get('datum')  # dd-mm-jjjj format
        hoeveelheid = _safe_float(form.get('hoeveelheid_kg_ha'))
        
        eigen_bedrijf = 1 if 'eigen_bedrijf' in form else 0
        notities = form.get('notities', "")
        
        # NPK waarden uit frontend
        n_kg_ha = _safe_float(form.get('n_kg_ha'), 0)
        p2o5_kg_ha = _safe_float(form.get('p2o5_kg_ha'), 0)
        k2o_kg_ha = _safe_float(form.get('k2o_kg_ha'), 0)
        
        logger.info(f"Bemesting toevoegen - Norm IDs: {gebruiksnorm_ids}, Bedrijf: {bedrijf_id}, Meststof: {meststof_id}")
        logger.info(f"NPK waarden: N={n_kg_ha}, P2O5={p2o5_kg_ha}, K2O={k2o_kg_ha}")

        # Validatie
        if not all([bedrijf_id, gebruiksnorm_ids, meststof_id, datum, hoeveelheid]) or hoeveelheid <= 0:
            flash("Vul alle verplichte velden correct in.", "danger")
            return redirect(url_for('bemestingen.bemestingen_nieuw'))

        conn = db.get_connection()
        c = conn.cursor()

        # Haal meststof info op voor eventuele fallback berekening
        meststof_info = c.execute(
            'SELECT n, p2o5, k2o, toepassing FROM universal_fertilizers WHERE id=?', 
            (meststof_id,)
        ).fetchone()

        if not meststof_info:
            flash("Geselecteerde meststof niet gevonden.", "danger")
            conn.close()
            return redirect(url_for('bemestingen.bemestingen_nieuw'))

        n_pct, p2o5_pct, k2o_pct, toepassing = meststof_info

        # Voor kunstmest: bereken NPK als het niet door frontend is gedaan
        if not toepassing or toepassing.lower() != 'dierlijke mest':
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
                norm_info = c.execute(
                    'SELECT perceel_id FROM gebruiksnormen WHERE id=?', 
                    (gebruiksnorm_id,)
                ).fetchone()
                
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
                     eigen_bedrijf, notities)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    bemesting_id, gebruiksnorm_id, bedrijf_id, perceel_id, meststof_id,
                    datum, hoeveelheid, n_kg_ha, p2o5_kg_ha, k2o_kg_ha, eigen_bedrijf, notities
                ))
                
                succesvol_toegevoegd += 1
                logger.info(f"Bemesting toegevoegd voor perceel {perceel_id}")
                
            except Exception as e:
                logger.error(f"Fout bij toevoegen bemesting voor norm {gebruiksnorm_id}: {e}")
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
        c.execute('SELECT id, meststof, n, p2o5, k2o, toepassing FROM universal_fertilizers ORDER BY meststof')
        meststoffen = c.fetchall()
        
        # Haal bemesting op
        c.execute('SELECT * FROM bemestingen WHERE id=?', (id,))
        bemesting = c.fetchone()
        
        toepassing = None
        if bemesting:
            meststof_id = bemesting[5]  # Aanpassen volgens kolom index
            row = c.execute('SELECT toepassing FROM universal_fertilizers WHERE id=?', (meststof_id,)).fetchone()
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
    """Verwerk bewerking bemesting"""
    try:
        datum = request.form.get('datum')
        hoeveelheid = _safe_float(request.form.get('hoeveelheid_kg_ha'), 0.0)
        meststof_id = request.form.get('meststof_id')
        eigen_bedrijf = 1 if 'eigen_bedrijf' in request.form else 0
        notities = request.form.get('notities', "")

        conn = db.get_connection()
        c = conn.cursor()
        
        # Haal meststof info op
        meststof_info = c.execute(
            'SELECT n, p2o5, k2o, toepassing FROM universal_fertilizers WHERE id=?', 
            (meststof_id,)
        ).fetchone()

        n_kg_ha = p2o5_kg_ha = k2o_kg_ha = None
        
        if meststof_info:
            n_pct, p2o5_pct, k2o_pct, toepassing = meststof_info
            
            if toepassing and toepassing.lower() == 'dierlijke mest':
                # Voor dierlijke mest: gebruik handmatige invoer
                n_kg_ha = _safe_float(request.form.get('n_kg_ha'))
                p2o5_kg_ha = _safe_float(request.form.get('p2o5_kg_ha'))
                k2o_kg_ha = _safe_float(request.form.get('k2o_kg_ha'))
            else:
                # Voor kunstmest: bereken op basis van percentages
                n_kg_ha = hoeveelheid * (_safe_float(n_pct, 0.0) / 100.0)
                p2o5_kg_ha = hoeveelheid * (_safe_float(p2o5_pct, 0.0) / 100.0)
                k2o_kg_ha = hoeveelheid * (_safe_float(k2o_pct, 0.0) / 100.0)

        # Update bemesting
        c.execute('''
            UPDATE bemestingen SET
                datum = ?,
                hoeveelheid_kg_ha = ?,
                meststof_id = ?,
                n_kg_ha = ?,
                p2o5_kg_ha = ?,
                k2o_kg_ha = ?,
                eigen_bedrijf = ?,
                notities = ?
            WHERE id = ?
        ''', (
            datum, hoeveelheid, meststof_id, n_kg_ha, p2o5_kg_ha, k2o_kg_ha, 
            eigen_bedrijf, notities, id
        ))
        
        conn.commit()
        conn.close()
        
        flash("Bemesting aangepast.", "success")
        
    except Exception as e:
        logger.error(f"Fout bij bewerken bemesting {id}: {e}")
        flash("Fout bij aanpassen bemesting.", "danger")
        
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
        existing = c.execute('SELECT id FROM bemestingen WHERE id = ?', (id,)).fetchone()
        if not existing:
            flash("Bemesting niet gevonden.", "danger")
        else:
            c.execute('DELETE FROM bemestingen WHERE id = ?', (id,))
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
                count = c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                stats[table] = count
            except:
                stats[table] = 'FOUT - tabel bestaat niet'
        
        # Check werkingscoëfficiënten
        try:
            count = c.execute('SELECT COUNT(*) FROM werkingscoefficienten').fetchone()[0]
            stats['werkingscoefficienten'] = count
        except:
            try:
                count = c.execute('SELECT COUNT(*) FROM stikstof_werkingscoefficient_dierlijk').fetchone()[0]
                stats['stikstof_werkingscoefficient_dierlijk'] = count
            except:
                stats['werkingscoefficienten'] = 'GEEN TABEL GEVONDEN'
        
        return jsonify({
            'status': 'OK',
            'database_stats': stats,
            'timestamp': str(datetime.now()) if 'datetime' in globals() else 'Nu'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'ERROR',
            'error': str(e)
        }), 500
    finally:
        conn.close()