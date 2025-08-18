from flask import Blueprint, render_template, request, session
import app.models.database_beheer as db
from app.dashboard.dashboard_stats import bereken_dashboard_stats
from app.gebruikers.auth_utils import login_required

dashboard_bp = Blueprint(
    'dashboard',
    __name__,
    template_folder='templates',
    static_folder='static',
    url_prefix='/dashboard'
)

@dashboard_bp.route('/bedrijfsdashboard', methods=['GET'])
@login_required
def bedrijfsdashboard():
    conn = db.get_connection()
    
    # Haal geselecteerde waarden uit query parameters
    selected_bedrijf_id = request.args.get('bedrijf_id')
    selected_jaar = request.args.get('jaar')
    
    # Converteer naar juiste types als ze bestaan
    if selected_bedrijf_id:
        try:
            selected_bedrijf_id = int(selected_bedrijf_id)
        except (ValueError, TypeError):
            selected_bedrijf_id = None
            
    if selected_jaar:
        try:
            selected_jaar = int(selected_jaar)
        except (ValueError, TypeError):
            selected_jaar = None

    # Bereken dashboard stats
    if selected_bedrijf_id and selected_jaar:
        stats = bereken_dashboard_stats(conn, selected_bedrijf_id, selected_jaar)
        
        # Haal perceel data op met polygon coordinates en gebruiksnormen
        percelen_data = []
        if stats['bemestingen_details']:
            # Verkrijg unieke percelen uit bemestingen
            unique_percelen = {}
            for bemesting in stats['bemestingen_details']:
                perceel_naam = bemesting['perceel']
                if perceel_naam not in unique_percelen:
                    unique_percelen[perceel_naam] = bemesting
            
            # Haal volledige perceel data op inclusief polygon coordinates
            for perceel_naam in unique_percelen.keys():
                perceel_query = """
                    SELECT p.*, gn.stikstof_norm_kg_ha, gn.stikstof_dierlijk_kg_ha, 
                           gn.fosfaat_norm_kg_ha, g.gewas
                    FROM percelen p
                    LEFT JOIN gebruiksnormen gn ON p.id = gn.perceel_id 
                        AND gn.bedrijf_id = ? AND gn.jaar = ?
                    LEFT JOIN stikstof_gewassen_normen g ON gn.gewas_id = g.id
                    WHERE p.perceelnaam = ? AND p.user_id = ?
                    LIMIT 1
                """
                
                perceel_row = conn.execute(perceel_query, (
                    selected_bedrijf_id, 
                    selected_jaar, 
                    perceel_naam, 
                    session['user_id']
                )).fetchone()
                
                if perceel_row:
                    # Convert row to dict
                    perceel_dict = {}
                    for i, col in enumerate(conn.execute(perceel_query, (
                        selected_bedrijf_id, selected_jaar, perceel_naam, session['user_id']
                    )).description):
                        perceel_dict[col[0]] = perceel_row[i]
                    
                    percelen_data.append(perceel_dict)
        
        stats['percelen_data'] = percelen_data
    else:
        stats = bereken_dashboard_stats(conn, None, None)
        stats['percelen_data'] = []

    conn.close()
    
    return render_template(
        'dashboard/bedrijfsdashboard.html',
        bedrijven=stats['bedrijven'],
        jaren=stats['jaren'],
        selected_bedrijf_id=selected_bedrijf_id,
        selected_jaar=selected_jaar,
        stikstof_norm=stats['stikstof_norm'],
        stikstof_dierlijk_norm=stats['stikstof_dierlijk_norm'],
        fosfaat_norm=stats['fosfaat_norm'],
        stikstof_total=stats['stikstof_total'],
        stikstof_dierlijk_total=stats['stikstof_dierlijk_total'],
        fosfaat_total=stats['fosfaat_total'],
        bemestingen_details=stats['bemestingen_details'],
        percelen_data=stats['percelen_data']
    )