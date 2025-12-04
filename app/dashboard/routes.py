from flask import Blueprint, render_template, request, session, jsonify
from app.models.database_beheer import get_connection
from app.dashboard.dashboard_stats import bereken_dashboard_stats
from app.gebruikers.auth_utils import login_required, effective_user_id
import logging, traceback
import os
import json

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint(
    'dashboard',
    __name__,
    template_folder='templates',
    static_folder='static',
    url_prefix='/'
)


def is_admin():
    return session.get('is_admin', 0) == 1


def _rows_to_dicts(cursor):
    """Hulpje: DB-rows -> list[dict] (werkt voor PostgreSQL cursors)."""
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


# routes (dashboard)
@dashboard_bp.route('/', methods=['GET'])
@login_required
def bedrijfsdashboard():
    # Gebruik env variabele voor de Google Maps key; val terug op een dev/dummy key indien nodig
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    return render_template(
        'dashboard/bedrijfsdashboard.html',
        google_maps_api_key=api_key,
        is_admin=is_admin(),
        view_as_user_id=session.get('view_as_user_id'),
        view_as_user_name=session.get('view_as_user_name'),
    )


@dashboard_bp.route('/api/dashboard/initial-data')
@login_required
def get_dashboard_initial_data():
    """Haal initiële data op voor dashboard filters + setup-status."""
    try:
        user_id = effective_user_id()
        if not user_id:
            return jsonify({"error": "Niet ingelogd"}), 401

        conn = get_connection()
        c = conn.cursor()

        # Bedrijven van de (effectieve) gebruiker
        c.execute(
            "SELECT id, naam FROM bedrijven WHERE user_id = %s ORDER BY naam",
            (user_id,)
        )
        bedrijven = _rows_to_dicts(c)

        # Jaren waarin de (effectieve) user gebruiksnormen heeft
        c.execute("""
            SELECT DISTINCT gn.jaar
            FROM gebruiksnormen gn
            JOIN bedrijven b ON b.id = gn.bedrijf_id
            WHERE b.user_id = %s AND gn.jaar IS NOT NULL
            ORDER BY gn.jaar DESC
        """, (user_id,))
        jaren_rows = _rows_to_dicts(c)
        jaren = [r["jaar"] for r in jaren_rows]

        # 🆕 Totaal aantal percelen voor deze user
        c.execute("""
            SELECT COUNT(*) 
            FROM percelen p
            WHERE p.user_id = %s
        """, (user_id,))
        percelen_count = (c.fetchone() or [0])[0]

        # 🆕 Totaal aantal gebruiksnormen (alle jaren) voor deze user
        c.execute("""
            SELECT COUNT(*)
            FROM gebruiksnormen gn
            JOIN bedrijven b ON b.id = gn.bedrijf_id
            WHERE b.user_id = %s
        """, (user_id,))
        gebruiksnormen_count = (c.fetchone() or [0])[0]

        conn.close()

        if not bedrijven:
            # Geen bedrijven → eerste stap in wizard
            return jsonify({
                "bedrijven": [],
                "jaren": [],
                "percelen_count": 0,
                "gebruiksnormen_count": 0,
                "message": "Geen bedrijven gevonden. Voeg eerst bedrijven toe."
            })

        if not jaren:
            # Wel bedrijven maar (nog) geen normen voor een jaar
            return jsonify({
                "bedrijven": bedrijven,
                "jaren": [],
                "percelen_count": percelen_count,
                "gebruiksnormen_count": gebruiksnormen_count,
                "message": "Geen gebruiksnormen ingesteld. Stel eerst normen in."
            })

        # “Normale” situatie: bedrijven + minstens één jaar met normen
        return jsonify({
            "bedrijven": bedrijven,
            "jaren": jaren,
            "percelen_count": percelen_count,
            "gebruiksnormen_count": gebruiksnormen_count
        })

    except Exception as e:
        logger.error(f"Error in get_dashboard_initial_data: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": f"Fout bij ophalen gegevens: {e}"}), 500


@dashboard_bp.route('/api/dashboard/stats')
@login_required
def get_dashboard_stats():
    """Haal dashboard statistieken op voor gebruiker en jaar (alle bedrijven)"""
    try:
        jaar = request.args.get('jaar')
        user_id = effective_user_id()

        # Input validatie
        if not jaar or not user_id:
            return jsonify({"error": "Jaar en login zijn vereist"}), 400

        try:
            jaar_int = int(jaar)
            if jaar_int < 2020 or jaar_int > 2030:
                return jsonify({"error": "Ongeldig jaar (2020-2030)"}), 400
        except ValueError:
            return jsonify({"error": "Jaar moet een nummer zijn"}), 400

        conn = get_connection()
        c = conn.cursor()

        # Check of er gebruiksnormen zijn voor dit jaar en deze gebruiker
        c.execute("""
            SELECT COUNT(*) AS count
            FROM gebruiksnormen gn
            JOIN bedrijven b ON b.id = gn.bedrijf_id
            WHERE gn.jaar = %s AND b.user_id = %s
        """, (jaar_int, user_id))
        row = c.fetchone()
        test_count = row[0] if row else 0

        if test_count == 0:
            conn.close()
            return jsonify({
                "bedrijven": [], "jaren": [],
                "totaal_stats": {
                    "stikstof_norm": 0, "stikstof_dierlijk_norm": 0,
                    "fosfaat_norm": 0, "stikstof_total": 0, "stikstof_dierlijk_total": 0,
                    "fosfaat_total": 0, "kalium_total": 0
                },
                "bedrijf_stats": [],
                "bemestingen_details": [],
                "message": "Geen gebruiksnormen gevonden voor dit jaar"
            })

        # bereken_dashboard_stats gebruikt zelf de cursor/conn
        stats = bereken_dashboard_stats(conn, user_id, jaar_int)
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
        user_id = effective_user_id()
        if not user_id:
            return jsonify({"error": "Niet ingelogd"}), 401

        conn = get_connection()
        c = conn.cursor()

        # Alleen data van deze (effectieve) gebruiker
        c.execute(
            "SELECT * FROM bedrijven WHERE user_id = %s LIMIT 5", (user_id,)
        )
        bedrijven = _rows_to_dicts(c)

        c.execute("""
            SELECT gn.* FROM gebruiksnormen gn
            JOIN bedrijven b ON b.id = gn.bedrijf_id
            WHERE b.user_id = %s LIMIT 5
        """, (user_id,))
        gebruiksnormen = _rows_to_dicts(c)

        c.execute("""
            SELECT bem.* FROM bemestingen bem
            JOIN bedrijven b ON b.id = bem.bedrijf_id
            WHERE b.user_id = %s LIMIT 5
        """, (user_id,))
        bemestingen = _rows_to_dicts(c)

        c.execute(
            "SELECT * FROM percelen WHERE user_id = %s LIMIT 5", (user_id,)
        )
        percelen = _rows_to_dicts(c)

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
    Kaartdata gefilterd op JAAR VAN GEBRUIKSNORMEN.
    1) Haal alle gebruiksnormen (user+jaar) met perceel+bedrijf+polygon.
    2) Haal ALLE bemestingen voor deze gebruiksnorm_ids op (join op b.gebruiksnorm_id).
    3) Bouw GeoJSON features per perceel/norm met werkzame totalen & percentages.
    """
    try:
        jaar = request.args.get('jaar')
        user_id = effective_user_id()

        if not jaar or not user_id:
            return jsonify({'type': 'FeatureCollection', 'features': [], 'error': 'Jaar en login vereist'}), 400

        try:
            jaar_int = int(jaar)
        except ValueError:
            return jsonify({'type': 'FeatureCollection', 'features': [], 'error': 'Ongeldig jaar'}), 400

        conn = get_connection()
        c = conn.cursor()

        try:
            # 1) Alle gebruiksnormen van deze user voor dit jaar (met polygon!)
            c.execute("""
                SELECT
                    gn.id                         AS gebruiksnorm_id,
                    gn.jaar,
                    gn.bedrijf_id,
                    gn.perceel_id,
                    gn.stikstof_norm_kg_ha,
                    gn.stikstof_dierlijk_kg_ha,
                    gn.fosfaat_norm_kg_ha,
                    b.naam                       AS bedrijf_naam,
                    p.perceelnaam,
                    p.oppervlakte,
                    p.grondsoort,
                    p.nv_gebied,
                    p.polygon_coordinates,
                    sgn.gewas                    AS gewas_naam
                FROM gebruiksnormen gn
                JOIN bedrijven b ON b.id = gn.bedrijf_id
                JOIN percelen  p ON p.id = gn.perceel_id
                LEFT JOIN stikstof_gewassen_normen sgn ON sgn.id = gn.gewas_id
                WHERE gn.jaar = %s
                  AND b.user_id = %s
                  AND p.polygon_coordinates IS NOT NULL
                  AND p.polygon_coordinates <> ''
                ORDER BY b.naam, p.perceelnaam
            """, (jaar_int, user_id))
            normen_rows = _rows_to_dicts(c)

            if not normen_rows:
                conn.close()
                return jsonify({
                    'type': 'FeatureCollection',
                    'features': [],
                    'message': 'Geen percelen met normen (en polygon) voor dit jaar'
                })

            norm_ids = [r['gebruiksnorm_id'] for r in normen_rows]

            # 2) Alle bemestingen voor deze norm_ids
            placeholders = ",".join(["%s"] * len(norm_ids))
            c.execute(f"""
                SELECT
                    b.id,
                    b.gebruiksnorm_id,
                    b.datum,
                    COALESCE(b.werkzame_n_kg_ha, 0)    AS werkzame_n_kg_ha,
                    COALESCE(b.werkzame_p2o5_kg_ha, 0) AS werkzame_p2o5_kg_ha,
                    COALESCE(b.n_dierlijk_kg_ha, 0)    AS n_dierlijk_kg_ha,
                    COALESCE(b.k2o_kg_ha, 0)           AS k2o_kg_ha,
                    COALESCE(b.hoeveelheid_kg_ha, 0)   AS hoeveelheid_kg_ha,
                    b.eigen_bedrijf,
                    uf.meststof,
                    uf.toepassing
                FROM bemestingen b
                LEFT JOIN universal_fertilizers uf ON uf.id = b.meststof_id
                WHERE b.gebruiksnorm_id IN ({placeholders})
                ORDER BY b.datum DESC
            """, norm_ids)
            bem_rows = _rows_to_dicts(c)

            # index: gebruiksnorm_id -> lijst bemestingen
            bem_index = {}
            for br in bem_rows:
                bem_index.setdefault(br['gebruiksnorm_id'], []).append(br)

            features = []

            # 3) Bouw per norm/perceel één feature
            for row in normen_rows:
                gn_id        = row['gebruiksnorm_id']
                perceelnaam  = row['perceelnaam'] or f"Perceel {row['perceel_id']}"
                bedrijf_naam = row['bedrijf_naam']
                oppervlakte  = float(row['oppervlakte'] or 0.0)

                # Normen totaal (kg) = norm_kg_ha * ha
                norm_stikstof_totaal  = float(row['stikstof_norm_kg_ha'] or 0)       * oppervlakte
                norm_stikstof_dier    = float(row['stikstof_dierlijk_kg_ha'] or 0)   * oppervlakte
                norm_fosfaat_totaal   = float(row['fosfaat_norm_kg_ha'] or 0)        * oppervlakte

                # Werkelijke totalen op basis van WERKZAME/registratiewaardes
                eff_n_total      = 0.0
                eff_n_dier_total = 0.0
                eff_p2o5_total   = 0.0
                eff_k2o_total    = 0.0
                preview          = []

                bem_for_norm = bem_index.get(gn_id, [])

                for idx, bem in enumerate(bem_for_norm):
                    n_tot   = float(bem['werkzame_n_kg_ha'])    * oppervlakte
                    n_d_tot = float(bem['n_dierlijk_kg_ha'])    * oppervlakte
                    p_tot   = float(bem['werkzame_p2o5_kg_ha']) * oppervlakte
                    k_tot   = float(bem['k2o_kg_ha'])           * oppervlakte

                    eff_n_total      += n_tot
                    eff_n_dier_total += n_d_tot
                    eff_p2o5_total   += p_tot
                    eff_k2o_total    += k_tot

                    if idx < 5:
                        preview.append({
                            'datum': bem['datum'],
                            'meststof': bem['meststof'] or '-',
                            'toepassing': bem['toepassing'] or '-',
                            'hoeveelheid_kg_ha': round(float(bem['hoeveelheid_kg_ha'] or 0), 1),
                            'werkzame_n_kg_ha': round(float(bem['werkzame_n_kg_ha'] or 0), 1),
                            'werkzame_p2o5_kg_ha': round(float(bem['werkzame_p2o5_kg_ha'] or 0), 1),
                            'n_dierlijk_kg_ha': round(float(bem['n_dierlijk_kg_ha'] or 0), 1),
                            'k2o_kg_ha': round(float(bem['k2o_kg_ha'] or 0), 1),
                            'werkzame_n_totaal': round(n_tot, 1),
                            'werkzame_n_dier_totaal': round(n_d_tot, 1),
                            'werkzame_p2o5_totaal': round(p_tot, 1),
                            'k2o_totaal': round(k_tot, 1),
                            'eigen_bedrijf': bem['eigen_bedrijf'],
                        })

                # percentages voor kleur/labels (K₂O heeft geen norm)
                usage_n_percent      = (eff_n_total      / norm_stikstof_totaal * 100) if norm_stikstof_totaal  > 0 else 0
                usage_n_dier_percent = (eff_n_dier_total / norm_stikstof_dier   * 100) if norm_stikstof_dier   > 0 else 0
                usage_p_percent      = (eff_p2o5_total   / norm_fosfaat_totaal  * 100) if norm_fosfaat_totaal  > 0 else 0

                # laatste datum
                last_date_formatted = bem_for_norm[0]['datum'] if bem_for_norm else '-'

                # Polygon -> GeoJSON
                geometry = None
                try:
                    coords_raw = row['polygon_coordinates']
                    coords_data = json.loads(coords_raw) if coords_raw else None
                    if isinstance(coords_data, list) and coords_data:
                        coordinates = []
                        for pt in coords_data:
                            if isinstance(pt, dict) and 'lat' in pt and 'lng' in pt:
                                lat, lng = float(pt['lat']), float(pt['lng'])
                                if -90 <= lat <= 90 and -180 <= lng <= 180:
                                    coordinates.append([lng, lat])  # GeoJSON: [lng, lat]
                        if len(coordinates) >= 3:
                            if coordinates[0] != coordinates[-1]:
                                coordinates.append(coordinates[0])
                            geometry = {'type': 'Polygon', 'coordinates': [coordinates]}
                except Exception as e:
                    logger.warning(f"Polygon parse failed voor {perceelnaam}: {e}")

                if not geometry:
                    continue

                features.append({
                    'type': 'Feature',
                    'geometry': geometry,
                    'properties': {
                        'perceel_id': row['perceel_id'],
                        'bedrijf_id': row['bedrijf_id'],
                        'bedrijf_naam': bedrijf_naam,
                        'perceelnaam': perceelnaam,
                        'oppervlakte_ha': round(oppervlakte, 2),
                        'gewas': row.get('gewas_naam') or 'Onbekend',
                        'grondsoort': row.get('grondsoort') or '-',
                        'nv_gebied': 'Ja' if row.get('nv_gebied') else 'Nee',

                        # Normen (totaal kg)
                        'norm_stikstof_totaal': round(norm_stikstof_totaal, 1),
                        'norm_stikstof_dierlijk_totaal': round(norm_stikstof_dier, 1),
                        'norm_fosfaat_totaal': round(norm_fosfaat_totaal, 1),

                        # Werkelijke totalen (totaal kg)
                        'eff_n_total': round(eff_n_total, 1),
                        'eff_n_dier_total': round(eff_n_dier_total, 1),
                        'eff_p2o5_total': round(eff_p2o5_total, 1),
                        'eff_k2o_total': round(eff_k2o_total, 1),

                        # Percentages (geen K₂O-percentage)
                        'usage_n_percent': round(usage_n_percent, 1),
                        'usage_n_dier_percent': round(usage_n_dier_percent, 1),
                        'usage_p_percent': round(usage_p_percent, 1),

                        # Bemestingsstatistieken
                        'bemestingen_count': len(bem_for_norm),
                        'bemestingen_last_date': last_date_formatted,
                        'preview_bemestingen': preview
                    }
                })

            conn.close()
            logger.info(f"Returning {len(features)} features (jaar={jaar_int})")
            return jsonify({'type': 'FeatureCollection', 'features': features})

        except Exception:
            conn.close()
            raise

    except Exception as e:
        logger.error(f"Error in api_map_percelen: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'type': 'FeatureCollection', 'features': [], 'error': str(e)}), 500
