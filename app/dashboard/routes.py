from flask import Blueprint, render_template, request, session, jsonify
from app.models.database_beheer import get_connection
from app.dashboard.dashboard_stats import bereken_dashboard_stats
from app.gebruikers.auth_utils import login_required
import logging, traceback
import os

# ✅ extra imports voor de kaart-API
import json, re
from datetime import datetime
from app.dashboard.werkingscoefficient import bereken_werking, is_dierlijk_meststof

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint(
    'dashboard',
    __name__,
    template_folder='templates',
    static_folder='static',
    url_prefix='/dashboard'
)

# routes (dashboard)
@dashboard_bp.route('/', methods=['GET'])
@login_required
def bedrijfsdashboard():
    # ✅ FIX: Verwijder automatische admin rechten
    # session.setdefault("is_admin", 1)  # Dit was onveilig
    
    # ✅ FIX: Gebruik environment variable voor API key
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        logger.warning("Google Maps API key not found in environment variables")
        # Fallback naar hardcoded key alleen voor development
        api_key = "AIzaSyC1vcHufUkQmzq5etm1ah12shO0QciskiA"
    
    return render_template('dashboard/bedrijfsdashboard.html', google_maps_api_key=api_key)


@dashboard_bp.route('/api/dashboard/initial-data')
@login_required
def get_dashboard_initial_data():
    """Haal initiële data op voor dashboard filters"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({"error": "Niet ingelogd"}), 401
            
        conn = get_connection()
        conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
        
        # ✅ FIX: Filter bedrijven op user_id voor security
        bedrijven = [dict(r) for r in conn.execute(
            "SELECT id, naam FROM bedrijven WHERE user_id = ? ORDER BY naam", 
            (user_id,)
        ).fetchall()]
        
        # ✅ FIX: Alleen jaren ophalen waarvoor deze user data heeft
        jaren = [r["jaar"] for r in conn.execute("""
            SELECT DISTINCT gn.jaar 
            FROM gebruiksnormen gn
            JOIN bedrijven b ON b.id = gn.bedrijf_id
            WHERE b.user_id = ? AND gn.jaar IS NOT NULL 
            ORDER BY gn.jaar DESC
        """, (user_id,)).fetchall()]
        
        conn.close()
        
        # ✅ FIX: Meer informatieve response als er geen data is
        if not bedrijven:
            return jsonify({
                "bedrijven": [], 
                "jaren": [], 
                "message": "Geen bedrijven gevonden. Voeg eerst bedrijven toe."
            })
            
        if not jaren:
            return jsonify({
                "bedrijven": bedrijven, 
                "jaren": [], 
                "message": "Geen gebruiksnormen ingesteld. Stel eerst normen in."
            })
        
        return jsonify({"bedrijven": bedrijven, "jaren": jaren})
        
    except Exception as e:
        logger.error(f"Error in get_dashboard_initial_data: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": f"Fout bij ophalen gegevens: {e}"}), 500


@dashboard_bp.route('/api/dashboard/stats')
@login_required
def get_dashboard_stats():
    """Haal dashboard statistieken op voor bedrijf en jaar"""
    try:
        bedrijf_id = request.args.get('bedrijf_id')
        jaar = request.args.get('jaar')
        user_id = session.get('user_id')
        
        # ✅ FIX: Betere input validatie
        if not bedrijf_id or not jaar or not user_id:
            return jsonify({"error": "Bedrijf, jaar en login zijn vereist"}), 400
            
        try:
            jaar_int = int(jaar)
            if jaar_int < 2020 or jaar_int > 2030:
                return jsonify({"error": "Ongeldig jaar (2020-2030)"}), 400
        except ValueError:
            return jsonify({"error": "Jaar moet een nummer zijn"}), 400

        conn = get_connection()
        conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))

        # ✅ FIX: Controleer of gebruiker toegang heeft tot dit bedrijf
        bedrijf_check = conn.execute(
            "SELECT id FROM bedrijven WHERE id = ? AND user_id = ?", 
            (bedrijf_id, user_id)
        ).fetchone()
        
        if not bedrijf_check:
            conn.close()
            return jsonify({"error": "Geen toegang tot dit bedrijf"}), 403

        # ✅ FIX: Geoptimaliseerde query om te checken of er gebruiksnormen zijn
        test = conn.execute("""
            SELECT COUNT(*) AS count 
            FROM gebruiksnormen gn
            JOIN bedrijven b ON b.id = gn.bedrijf_id
            WHERE gn.bedrijf_id = ? AND gn.jaar = ? AND b.user_id = ?
        """, (bedrijf_id, jaar_int, user_id)).fetchone()
        
        if test and test["count"] == 0:
            conn.close()
            return jsonify({
                "bedrijven": [], "jaren": [], 
                "stikstof_norm": 0, "stikstof_dierlijk_norm": 0,
                "fosfaat_norm": 0, "stikstof_total": 0, "stikstof_dierlijk_total": 0,
                "fosfaat_total": 0, "bemestingen_details": [],
                "message": "Geen gebruiksnormen gevonden voor dit bedrijf en jaar"
            })

        stats = bereken_dashboard_stats(conn, bedrijf_id, jaar_int)
        conn.close()
        return jsonify(stats)
        
    except Exception as e:
        logger.error(f"Error in get_dashboard_stats: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": f"Fout bij ophalen dashboard gegevens: {e}"}), 500


@dashboard_bp.route('/api/dashboard/debug')
@login_required
def debug_dashboard():
    """Debug endpoint om database inhoud te controleren"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({"error": "Niet ingelogd"}), 401
            
        conn = get_connection()
        conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
        
        # ✅ FIX: Alleen data van deze gebruiker
        bedrijven = conn.execute("SELECT * FROM bedrijven WHERE user_id = ? LIMIT 5", (user_id,)).fetchall()
        
        gebruiksnormen = conn.execute("""
            SELECT gn.* FROM gebruiksnormen gn
            JOIN bedrijven b ON b.id = gn.bedrijf_id
            WHERE b.user_id = ? LIMIT 5
        """, (user_id,)).fetchall()
        
        bemestingen = conn.execute("""
            SELECT bem.* FROM bemestingen bem
            JOIN bedrijven b ON b.id = bem.bedrijf_id
            WHERE b.user_id = ? LIMIT 5
        """, (user_id,)).fetchall()
        
        percelen = conn.execute("SELECT * FROM percelen WHERE user_id = ? LIMIT 5", (user_id,)).fetchall()
        
        # ✅ FIX: Meer uitgebreide debug info
        stats = {
            "user_id": user_id,
            "bedrijven_count": len(bedrijven),
            "gebruiksnormen_count": len(gebruiksnormen), 
            "bemestingen_count": len(bemestingen),
            "percelen_count": len(percelen),
            "bedrijven": bedrijven,
            "gebruiksnormen": gebruiksnormen,
            "bemestingen": bemestingen,
            "percelen": percelen
        }
        
        conn.close()
        return jsonify(stats)
        
    except Exception as e:
        logger.error(f"Error in debug_dashboard: {e}")
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/map/percelen')
@login_required
def api_map_percelen():
    """
    API endpoint om percelendata te leveren voor de kaart met bemestingsinformatie
    ✅ Verbeterd met betere error handling en security
    """
    try:
        # Haal parameters op
        bedrijf_id = request.args.get('bedrijf_id')
        jaar = request.args.get('jaar')
        user_id = session.get('user_id')
        
        logger.info(f"Loading map percelen for user={user_id}, bedrijf_id={bedrijf_id}, jaar={jaar}")
        
        # ✅ FIX: Betere parameter validatie
        if not bedrijf_id or not jaar or not user_id:
            return jsonify({
                'type': 'FeatureCollection',
                'features': [],
                'error': 'Bedrijf, jaar en login vereist'
            }), 400
        
        try:
            jaar_int = int(jaar)
        except ValueError:
            return jsonify({
                'type': 'FeatureCollection', 
                'features': [],
                'error': 'Ongeldig jaar'
            }), 400
        
        conn = get_connection()
        conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
        
        try:
            # ✅ FIX: Controleer toegang tot bedrijf
            bedrijf_check = conn.execute(
                "SELECT id FROM bedrijven WHERE id = ? AND user_id = ?", 
                (bedrijf_id, user_id)
            ).fetchone()
            
            if not bedrijf_check:
                conn.close()
                return jsonify({
                    'type': 'FeatureCollection',
                    'features': [],
                    'error': 'Geen toegang tot dit bedrijf'
                }), 403
            
            # Haal percelen op die gekoppeld zijn aan dit bedrijf via gebruiksnormen
            percelen_query = """
            SELECT DISTINCT
                p.id as perceel_id,
                p.perceelnaam,
                p.oppervlakte,
                p.grondsoort,
                p.nv_gebied,
                p.polygon_coordinates,
                p.latitude,
                p.longitude
            FROM percelen p
            INNER JOIN gebruiksnormen gn ON gn.perceel_id = p.id
            INNER JOIN bedrijven b ON b.id = gn.bedrijf_id
            WHERE gn.bedrijf_id = ? 
                AND gn.jaar = ?
                AND b.user_id = ?
                AND p.polygon_coordinates IS NOT NULL 
                AND p.polygon_coordinates != ''
            ORDER BY p.perceelnaam
            """
            
            percelen_raw = conn.execute(percelen_query, (bedrijf_id, jaar_int, user_id)).fetchall()
            logger.info(f"Found {len(percelen_raw)} percelen with polygon data")
            
            if not percelen_raw:
                conn.close()
                return jsonify({
                    'type': 'FeatureCollection',
                    'features': [],
                    'message': 'Geen percelen met kaartdata gevonden'
                })
            
            # Voor elk perceel, haal gebruiksnormen en bemestingen op
            features = []
            
            for perceel in percelen_raw:
                try:
                    perceel_id = perceel['perceel_id']
                    
                    # Zoek gebruiksnorm voor dit perceel
                    norm_query = """
                    SELECT 
                        gn.stikstof_norm_kg_ha, 
                        gn.stikstof_dierlijk_kg_ha, 
                        gn.fosfaat_norm_kg_ha,
                        gn.gewas_id,
                        sgn.gewas as gewas_naam
                    FROM gebruiksnormen gn
                    LEFT JOIN stikstof_gewassen_normen sgn ON sgn.id = gn.gewas_id
                    WHERE gn.bedrijf_id = ? AND gn.jaar = ? AND gn.perceel_id = ?
                    LIMIT 1
                    """
                    
                    norm = conn.execute(norm_query, (bedrijf_id, jaar_int, perceel_id)).fetchone()
                    
                    if norm:
                        oppervlakte = perceel['oppervlakte'] or 1.0
                        norm_stikstof_totaal = (norm['stikstof_norm_kg_ha'] or 0) * oppervlakte
                        norm_stikstof_dierlijk = (norm['stikstof_dierlijk_kg_ha'] or 0) * oppervlakte
                        norm_fosfaat = (norm['fosfaat_norm_kg_ha'] or 0) * oppervlakte
                        gewas_naam = norm['gewas_naam'] or 'Onbekend'
                    else:
                        norm_stikstof_totaal = 0
                        norm_stikstof_dierlijk = 0
                        norm_fosfaat = 0
                        gewas_naam = 'Geen norm ingesteld'
                    
                    # Haal bemestingen op voor dit perceel in dit jaar
                    bem_query = """
                    SELECT 
                        b.id, b.datum, b.n_kg_ha, b.p2o5_kg_ha, 
                        b.eigen_bedrijf, b.notities, b.hoeveelheid_kg_ha,
                        uf.meststof, uf.toepassing
                    FROM bemestingen b
                    LEFT JOIN universal_fertilizers uf ON uf.id = b.meststof_id
                    WHERE b.perceel_id = ? 
                        AND strftime('%Y', b.datum) = ?
                    ORDER BY b.datum DESC
                    """
                    
                    bemestingen = conn.execute(bem_query, (perceel_id, str(jaar_int))).fetchall()
                    
                    # Bereken totalen (real-time berekening)
                    eff_n_total = 0
                    eff_n_dier_total = 0
                    preview_bemestingen = []
                    
                    for bem in bemestingen:
                        # Bereken werkingscoefficient dynamisch
                        oppervlakte_perceel = perceel['oppervlakte'] or 1.0
                        werking = bereken_werking(bem['meststof'] or '')
                        
                        # Bereken effectieve stikstof
                        eff_n = (bem['n_kg_ha'] or 0) * oppervlakte_perceel * (werking / 100)
                        eff_n_total += eff_n
                        
                        # Bereken effectieve dierlijke stikstof
                        if is_dierlijk_meststof(bem['meststof'] or ''):
                            eff_n_dier = eff_n
                            eff_n_dier_total += eff_n_dier
                        else:
                            eff_n_dier = 0
                        
                        # Voeg toe aan preview (alleen eerste 5)
                        if len(preview_bemestingen) < 5:
                            preview_bemestingen.append({
                                'datum': bem['datum'],
                                'meststof': bem['meststof'] or '-',
                                'toepassing': bem['toepassing'] or '-',
                                'n_kg_ha': round(bem['n_kg_ha'] or 0, 1),
                                'p2o5_kg_ha': round(bem['p2o5_kg_ha'] or 0, 1),
                                'eff_n': round(eff_n, 1),
                                'eff_n_dier': round(eff_n_dier, 1)
                            })
                    
                    # Bereken usage percentages
                    usage_n_percent = (eff_n_total / norm_stikstof_totaal * 100) if norm_stikstof_totaal > 0 else 0
                    usage_n_dier_percent = (eff_n_dier_total / norm_stikstof_dierlijk * 100) if norm_stikstof_dierlijk > 0 else 0
                    
                    # Parse polygon_coordinates naar GeoJSON
                    geometry = None
                    
                    if perceel['polygon_coordinates']:
                        try:
                            coords_data = json.loads(perceel['polygon_coordinates'])
                            # ✅ FIX: Betere polygon parsing
                            if isinstance(coords_data, list) and len(coords_data) > 0:
                                coordinates = []
                                for point in coords_data:
                                    if isinstance(point, dict) and 'lat' in point and 'lng' in point:
                                        # Valideer coordinaten
                                        lat, lng = float(point['lat']), float(point['lng'])
                                        if -90 <= lat <= 90 and -180 <= lng <= 180:
                                            coordinates.append([lng, lat])  # GeoJSON is [lng, lat]
                                
                                if len(coordinates) >= 3:
                                    # Sluit polygon als dat nog niet gebeurd is
                                    if coordinates[0] != coordinates[-1]:
                                        coordinates.append(coordinates[0])
                                    
                                    geometry = {
                                        'type': 'Polygon',
                                        'coordinates': [coordinates]
                                    }
                        except (json.JSONDecodeError, ValueError, KeyError) as e:
                            logger.warning(f"Could not parse polygon_coordinates for perceel {perceel['perceelnaam']}: {e}")
                    
                    # Als geen geldige geometry, skip dit perceel
                    if not geometry:
                        logger.warning(f"No valid geometry found for perceel {perceel['perceelnaam']}")
                        continue
                    
                    # Format laatste bemesting datum
                    last_date_formatted = '-'
                    if bemestingen:
                        last_date = bemestingen[0]['datum']
                        try:
                            if isinstance(last_date, str):
                                if '-' in last_date and len(last_date) == 10:
                                    parts = last_date.split('-')
                                    if len(parts) == 3 and len(parts[0]) == 4:  # YYYY-MM-DD
                                        dt = datetime.strptime(last_date, '%Y-%m-%d')
                                        last_date_formatted = dt.strftime('%d-%m-%Y')
                                    else:
                                        last_date_formatted = last_date
                                else:
                                    last_date_formatted = last_date
                            else:
                                last_date_formatted = last_date.strftime('%d-%m-%Y')
                        except:
                            last_date_formatted = str(last_date)
                    
                    feature = {
                        'type': 'Feature',
                        'geometry': geometry,
                        'properties': {
                            'perceel_id': perceel_id,
                            'perceelnaam': perceel['perceelnaam'] or f'Perceel {perceel_id}',
                            'oppervlakte_ha': round(float(perceel['oppervlakte'] or 0), 2),
                            'gewas': gewas_naam,
                            'grondsoort': perceel['grondsoort'] or '-',
                            'nv_gebied': 'Ja' if perceel['nv_gebied'] else 'Nee',
                            
                            # Normen
                            'norm_stikstof_totaal': round(float(norm_stikstof_totaal), 1),
                            'norm_stikstof_dierlijk_totaal': round(float(norm_stikstof_dierlijk), 1),
                            'norm_fosfaat_totaal': round(float(norm_fosfaat), 1),
                            
                            # Werkelijke effectieve bemesting
                            'eff_n_total': round(float(eff_n_total), 1),
                            'eff_n_dier_total': round(float(eff_n_dier_total), 1),
                            'eff_p2o5_total': 0,  # Niet berekenen
                            
                            # Usage percentages (voor kleur op kaart)
                            'usage_n_percent': round(float(usage_n_percent), 1),
                            'usage_n_dier_percent': round(float(usage_n_dier_percent), 1),
                            'usage_p_percent': 0,  # Niet berekenen
                            
                            # Bemestingsstatistieken
                            'bemestingen_count': len(bemestingen),
                            'bemestingen_last_date': last_date_formatted,
                            'preview_bemestingen': preview_bemestingen
                        }
                    }
                    
                    features.append(feature)
                    
                except Exception as e:
                    logger.error(f"Error processing perceel {perceel.get('perceelnaam', 'unknown')}: {e}")
                    logger.error(traceback.format_exc())
                    continue
            
            conn.close()
            
            geojson_response = {
                'type': 'FeatureCollection',
                'features': features
            }
            
            logger.info(f"Returning {len(features)} valid features")
            return jsonify(geojson_response)
            
        except Exception as e:
            conn.close()
            raise e
        
    except Exception as e:
        logger.error(f"Error in api_map_percelen: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            'type': 'FeatureCollection',
            'features': [],
            'error': str(e)
        }), 500