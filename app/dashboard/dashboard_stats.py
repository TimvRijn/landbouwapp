import sqlite3
from app.dashboard.werkingscoefficient import bereken_werking, is_dierlijk_meststof
from datetime import datetime

def bereken_dashboard_stats(conn, bedrijf_id, jaar):
    """
    Bereken dashboard statistieken voor een bedrijf in een specifiek jaar
    Gebruikt bestaande database structuur zonder wijzigingen
    """
    conn.row_factory = sqlite3.Row

    # Haal basis data op
    bedrijven = [dict(id=row["id"], naam=row["naam"]) for row in conn.execute("SELECT id, naam FROM bedrijven").fetchall()]
    jaren = [row["jaar"] for row in conn.execute("SELECT DISTINCT jaar FROM gebruiksnormen ORDER BY jaar DESC").fetchall()]

    if not bedrijf_id or not jaar:
        return {
            "bedrijven": bedrijven, 
            "jaren": jaren, 
            "stikstof_norm": 0, 
            "stikstof_dierlijk_norm": 0,
            "fosfaat_norm": 0, 
            "stikstof_total": 0, 
            "stikstof_dierlijk_total": 0,
            "fosfaat_total": 0, 
            "bemestingen_details": []
        }

    # Haal gebruiksnormen op voor dit bedrijf en jaar
    normen = conn.execute("""
        SELECT 
            gn.*,
            p.perceelnaam,
            p.oppervlakte,
            sgn.gewas as gewas_naam
        FROM gebruiksnormen gn
        JOIN percelen p ON p.id = gn.perceel_id
        LEFT JOIN stikstof_gewassen_normen sgn ON sgn.id = gn.gewas_id
        WHERE gn.bedrijf_id = ? AND gn.jaar = ?
    """, (bedrijf_id, jaar)).fetchall()

    if not normen:
        return {
            "bedrijven": bedrijven, 
            "jaren": jaren, 
            "stikstof_norm": 0, 
            "stikstof_dierlijk_norm": 0,
            "fosfaat_norm": 0, 
            "stikstof_total": 0, 
            "stikstof_dierlijk_total": 0,
            "fosfaat_total": 0, 
            "bemestingen_details": []
        }

    # Bereken totale normen (norm per ha * oppervlakte)
    stikstof_norm = sum((n["stikstof_norm_kg_ha"] or 0) * (n["oppervlakte"] or 0) for n in normen)
    stikstof_dierlijk_norm = sum((n["stikstof_dierlijk_kg_ha"] or 0) * (n["oppervlakte"] or 0) for n in normen)
    fosfaat_norm = sum((n["fosfaat_norm_kg_ha"] or 0) * (n["oppervlakte"] or 0) for n in normen)

    # Haal alle bemestingen op voor deze gebruiksnormen
    norm_ids = [str(n["id"]) for n in normen]
    placeholders = ",".join("?" for _ in norm_ids)
    
    bemestingen_query = f"""
        SELECT 
            b.*,
            p.perceelnaam,
            p.oppervlakte,
            p.calculated_area,
            p.grondsoort,
            uf.meststof as meststof_naam,
            uf.toepassing as meststof_toepassing,
            sgn.gewas as gewas_naam,
            gn.stikstof_norm_kg_ha,
            gn.stikstof_dierlijk_kg_ha,
            gn.fosfaat_norm_kg_ha
        FROM bemestingen b
        JOIN percelen p ON p.id = b.perceel_id
        JOIN gebruiksnormen gn ON gn.id = b.gebruiksnorm_id
        LEFT JOIN universal_fertilizers uf ON uf.id = b.meststof_id
        LEFT JOIN stikstof_gewassen_normen sgn ON sgn.id = gn.gewas_id
        WHERE b.gebruiksnorm_id IN ({placeholders})
        ORDER BY b.datum DESC
    """
    
    bemestingen = conn.execute(bemestingen_query, norm_ids).fetchall()

    # Bereken totalen en details (real-time berekening)
    stikstof_total = 0.0
    stikstof_dierlijk_total = 0.0
    fosfaat_total = 0.0  # Blijft 0 zoals gevraagd
    bemestingen_details = []

    for bem_row in bemestingen:
        bem = dict(bem_row)
        
        # Bepaal oppervlakte (gebruik calculated_area als backup, anders oppervlakte)
        oppervlakte = bem.get("calculated_area") or bem.get("oppervlakte") or 1.0
        n_kg_ha = bem.get("n_kg_ha") or 0
        p2o5_kg_ha = bem.get("p2o5_kg_ha") or 0
        meststof_naam = bem.get("meststof_naam") or ""
        
        # Bepaal werkingscoefficient (vereenvoudigde versie)
        werking = bereken_werking(meststof_naam)
        
        # Bereken effectieve bemesting (real-time)
        eff_n = oppervlakte * n_kg_ha * (werking / 100.0)
        
        # Bepaal of het dierlijke mest is voor effectieve N dier
        if is_dierlijk_meststof(meststof_naam):
            eff_n_dier = eff_n
        else:
            eff_n_dier = 0.0
            
        # P2O5 wordt niet berekend zoals gevraagd
        eff_p2o5 = 0.0

        # Voeg toe aan totalen
        stikstof_total += eff_n
        stikstof_dierlijk_total += eff_n_dier
        # fosfaat_total blijft 0

        # Voeg toe aan details
        bemestingen_details.append({
            "datum": bem.get("datum"),
            "perceel": bem.get("perceelnaam"),
            "gewas": bem.get("gewas_naam"),
            "meststof": meststof_naam,
            "oppervlakte": oppervlakte,
            "werkingscoeff": werking,
            "toepassing": bem.get("meststof_toepassing", ""),
            "effectieve_n": eff_n,
            "effectieve_n_dier": eff_n_dier,
            "effectieve_p2o5": eff_p2o5  # Altijd 0
        })

    return {
        "bedrijven": bedrijven,
        "jaren": jaren,
        "stikstof_norm": stikstof_norm,
        "stikstof_dierlijk_norm": stikstof_dierlijk_norm,
        "fosfaat_norm": fosfaat_norm,
        "stikstof_total": stikstof_total,
        "stikstof_dierlijk_total": stikstof_dierlijk_total,
        "fosfaat_total": fosfaat_total,  # Blijft 0
        "bemestingen_details": bemestingen_details
    }