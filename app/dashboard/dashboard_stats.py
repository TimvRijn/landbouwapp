import sqlite3
from datetime import datetime

def bereken_dashboard_stats(conn, user_id, jaar):
    """
    Bereken dashboard statistieken voor alle bedrijven van een gebruiker in een specifiek jaar
    Gebruikt werkzame_n_kg_ha en n_dierlijk_kg_ha direct uit database
    """
    conn.row_factory = sqlite3.Row

    # Haal basis data op voor deze gebruiker
    bedrijven = [dict(id=row["id"], naam=row["naam"]) for row in conn.execute(
        "SELECT id, naam FROM bedrijven WHERE user_id = ? ORDER BY naam", (user_id,)
    ).fetchall()]
    
    jaren = [row["jaar"] for row in conn.execute("""
        SELECT DISTINCT gn.jaar 
        FROM gebruiksnormen gn
        JOIN bedrijven b ON b.id = gn.bedrijf_id
        WHERE b.user_id = ? AND gn.jaar IS NOT NULL 
        ORDER BY gn.jaar DESC
    """, (user_id,)).fetchall()]

    if not jaar or not bedrijven:
        return {
            "bedrijven": bedrijven, 
            "jaren": jaren, 
            "totaal_stats": {
                "stikstof_norm": 0, 
                "stikstof_dierlijk_norm": 0,
                "fosfaat_norm": 0, 
                "stikstof_total": 0, 
                "stikstof_dierlijk_total": 0,
                "fosfaat_total": 0
            },
            "bedrijf_stats": [],
            "bemestingen_details": []
        }

    # Haal alle gebruiksnormen op voor dit jaar (alle bedrijven van gebruiker)
    normen = conn.execute("""
        SELECT 
            gn.*,
            p.perceelnaam,
            p.oppervlakte,
            b.naam as bedrijf_naam,
            sgn.gewas as gewas_naam
        FROM gebruiksnormen gn
        JOIN percelen p ON p.id = gn.perceel_id
        JOIN bedrijven b ON b.id = gn.bedrijf_id
        LEFT JOIN stikstof_gewassen_normen sgn ON sgn.id = gn.gewas_id
        WHERE b.user_id = ? AND gn.jaar = ?
        ORDER BY b.naam, p.perceelnaam
    """, (user_id, jaar)).fetchall()

    if not normen:
        return {
            "bedrijven": bedrijven, 
            "jaren": jaren, 
            "totaal_stats": {
                "stikstof_norm": 0, 
                "stikstof_dierlijk_norm": 0,
                "fosfaat_norm": 0, 
                "stikstof_total": 0, 
                "stikstof_dierlijk_total": 0,
                "fosfaat_total": 0
            },
            "bedrijf_stats": [],
            "bemestingen_details": []
        }

    # Bereken totale normen per bedrijf
    bedrijf_normen = {}
    for norm in normen:
        bedrijf_id = norm["bedrijf_id"]
        if bedrijf_id not in bedrijf_normen:
            bedrijf_normen[bedrijf_id] = {
                "bedrijf_naam": norm["bedrijf_naam"],
                "stikstof_norm": 0,
                "stikstof_dierlijk_norm": 0,
                "fosfaat_norm": 0,
                "percelen_count": 0,
                "oppervlakte_totaal": 0
            }
        
        oppervlakte = norm["oppervlakte"] or 0
        bedrijf_normen[bedrijf_id]["stikstof_norm"] += (norm["stikstof_norm_kg_ha"] or 0) * oppervlakte
        bedrijf_normen[bedrijf_id]["stikstof_dierlijk_norm"] += (norm["stikstof_dierlijk_kg_ha"] or 0) * oppervlakte
        bedrijf_normen[bedrijf_id]["fosfaat_norm"] += (norm["fosfaat_norm_kg_ha"] or 0) * oppervlakte
        bedrijf_normen[bedrijf_id]["percelen_count"] += 1
        bedrijf_normen[bedrijf_id]["oppervlakte_totaal"] += oppervlakte

    # Haal alle bemestingen op voor deze gebruiksnormen (GEBRUIK WERKZAME WAARDES)
    norm_ids = [str(n["id"]) for n in normen]
    placeholders = ",".join("?" for _ in norm_ids)
    
    bemestingen_query = f"""
        SELECT 
            b.*,
            p.perceelnaam,
            p.oppervlakte,
            p.calculated_area,
            p.grondsoort,
            bedrijf.naam as bedrijf_naam,
            uf.meststof as meststof_naam,
            uf.toepassing as meststof_toepassing,
            sgn.gewas as gewas_naam,
            gn.stikstof_norm_kg_ha,
            gn.stikstof_dierlijk_kg_ha,
            gn.fosfaat_norm_kg_ha
        FROM bemestingen b
        JOIN percelen p ON p.id = b.perceel_id
        JOIN gebruiksnormen gn ON gn.id = b.gebruiksnorm_id
        JOIN bedrijven bedrijf ON bedrijf.id = b.bedrijf_id
        LEFT JOIN universal_fertilizers uf ON uf.id = b.meststof_id
        LEFT JOIN stikstof_gewassen_normen sgn ON sgn.id = gn.gewas_id
        WHERE b.gebruiksnorm_id IN ({placeholders})
        ORDER BY bedrijf.naam, b.datum DESC
    """
    
    bemestingen = conn.execute(bemestingen_query, norm_ids).fetchall()

    # Bereken werkelijke totalen per bedrijf (GEBRUIK WERKZAME WAARDES)
    bedrijf_werkelijk = {}
    bemestingen_details = []

    for bem_row in bemestingen:
        bem = dict(bem_row)
        bedrijf_id = bem["bedrijf_id"]
        
        # Initialiseer bedrijf als nog niet bestaat
        if bedrijf_id not in bedrijf_werkelijk:
            bedrijf_werkelijk[bedrijf_id] = {
                "stikstof_total": 0,
                "stikstof_dierlijk_total": 0,
                "fosfaat_total": 0,
                "bemestingen_count": 0
            }
        
        # Bepaal oppervlakte
        oppervlakte = bem.get("calculated_area") or bem.get("oppervlakte") or 1.0
        
        # GEBRUIK WERKZAME WAARDES UIT DATABASE (geen berekeningen meer!)
        werkzame_n = (bem.get("werkzame_n_kg_ha") or 0) * oppervlakte
        werkzame_n_dierlijk = (bem.get("n_dierlijk_kg_ha") or 0) * oppervlakte  
        werkzame_p2o5 = (bem.get("werkzame_p2o5_kg_ha") or 0) * oppervlakte

        # Voeg toe aan bedrijf totalen
        bedrijf_werkelijk[bedrijf_id]["stikstof_total"] += werkzame_n
        bedrijf_werkelijk[bedrijf_id]["stikstof_dierlijk_total"] += werkzame_n_dierlijk
        bedrijf_werkelijk[bedrijf_id]["fosfaat_total"] += werkzame_p2o5
        bedrijf_werkelijk[bedrijf_id]["bemestingen_count"] += 1

        # Voeg toe aan details
        bemestingen_details.append({
            "datum": bem.get("datum"),
            "bedrijf": bem.get("bedrijf_naam"),
            "perceel": bem.get("perceelnaam"),
            "gewas": bem.get("gewas_naam"),
            "meststof": bem.get("meststof_naam"),
            "oppervlakte": oppervlakte,
            "toepassing": bem.get("meststof_toepassing", ""),
            "werkzame_n": werkzame_n,
            "werkzame_n_dierlijk": werkzame_n_dierlijk,
            "werkzame_p2o5": werkzame_p2o5,
            "n_kg_ha": bem.get("n_kg_ha", 0),
            "p2o5_kg_ha": bem.get("p2o5_kg_ha", 0)
        })

    # Combineer normen en werkelijke waardes per bedrijf
    bedrijf_stats = []
    totaal_stats = {
        "stikstof_norm": 0,
        "stikstof_dierlijk_norm": 0, 
        "fosfaat_norm": 0,
        "stikstof_total": 0,
        "stikstof_dierlijk_total": 0,
        "fosfaat_total": 0
    }

    for bedrijf_id, normen_data in bedrijf_normen.items():
        werkelijk_data = bedrijf_werkelijk.get(bedrijf_id, {
            "stikstof_total": 0,
            "stikstof_dierlijk_total": 0,
            "fosfaat_total": 0,
            "bemestingen_count": 0
        })

        bedrijf_stat = {
            "bedrijf_id": bedrijf_id,
            "bedrijf_naam": normen_data["bedrijf_naam"],
            "percelen_count": normen_data["percelen_count"],
            "oppervlakte_totaal": normen_data["oppervlakte_totaal"],
            
            # Normen
            "stikstof_norm": normen_data["stikstof_norm"],
            "stikstof_dierlijk_norm": normen_data["stikstof_dierlijk_norm"],
            "fosfaat_norm": normen_data["fosfaat_norm"],
            
            # Werkelijk
            "stikstof_total": werkelijk_data["stikstof_total"],
            "stikstof_dierlijk_total": werkelijk_data["stikstof_dierlijk_total"],
            "fosfaat_total": werkelijk_data["fosfaat_total"],
            
            # Percentages
            "stikstof_percentage": (werkelijk_data["stikstof_total"] / normen_data["stikstof_norm"] * 100) if normen_data["stikstof_norm"] > 0 else 0,
            "stikstof_dierlijk_percentage": (werkelijk_data["stikstof_dierlijk_total"] / normen_data["stikstof_dierlijk_norm"] * 100) if normen_data["stikstof_dierlijk_norm"] > 0 else 0,
            "fosfaat_percentage": (werkelijk_data["fosfaat_total"] / normen_data["fosfaat_norm"] * 100) if normen_data["fosfaat_norm"] > 0 else 0,
            
            "bemestingen_count": werkelijk_data["bemestingen_count"]
        }
        
        bedrijf_stats.append(bedrijf_stat)
        
        # Voeg toe aan totalen
        totaal_stats["stikstof_norm"] += normen_data["stikstof_norm"]
        totaal_stats["stikstof_dierlijk_norm"] += normen_data["stikstof_dierlijk_norm"]
        totaal_stats["fosfaat_norm"] += normen_data["fosfaat_norm"]
        totaal_stats["stikstof_total"] += werkelijk_data["stikstof_total"]
        totaal_stats["stikstof_dierlijk_total"] += werkelijk_data["stikstof_dierlijk_total"]
        totaal_stats["fosfaat_total"] += werkelijk_data["fosfaat_total"]

    return {
        "bedrijven": bedrijven,
        "jaren": jaren,
        "totaal_stats": totaal_stats,
        "bedrijf_stats": bedrijf_stats,
        "bemestingen_details": bemestingen_details
    }