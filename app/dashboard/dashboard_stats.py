import sqlite3
from app.dashboard.werkingscoefficient import bereken_werking, is_dierlijk_meststof
from datetime import datetime

def bereken_dashboard_stats(conn, bedrijf_id, jaar):
    conn.row_factory = sqlite3.Row

    # Altijd beschikbare data
    bedrijven = [dict(id=row["id"], naam=row["naam"]) for row in conn.execute("SELECT id, naam FROM bedrijven").fetchall()]
    jaren = [row["jaar"] for row in conn.execute("SELECT DISTINCT jaar FROM gebruiksnormen ORDER BY jaar DESC").fetchall()]

    # Als geen bedrijf of jaar geselecteerd, return lege stats
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
            "bemestingen_details": [],
            "percelen_data": []
        }

    # 1. Haal relevante gebruiksnormen voor gekozen bedrijf & jaar
    normen = conn.execute("""
        SELECT gn.*, p.perceelnaam AS perceel_naam, p.oppervlakte AS oppervlakte_ha
        FROM gebruiksnormen gn
        JOIN percelen p ON p.id = gn.perceel_id
        WHERE gn.bedrijf_id = ? AND gn.jaar = ?
    """, (bedrijf_id, jaar)).fetchall()

    # 2. Haal lijst van gebruiksnorm-ids voor filteren bemestingen
    norm_ids = [str(n["id"]) for n in normen]
    if not norm_ids:
        # Geen normen -> alles is leeg
        return {
            "bedrijven": bedrijven,
            "jaren": jaren,
            "stikstof_norm": 0,
            "stikstof_dierlijk_norm": 0,
            "fosfaat_norm": 0,
            "stikstof_total": 0,
            "stikstof_dierlijk_total": 0,
            "fosfaat_total": 0,
            "bemestingen_details": [],
            "percelen_data": []
        }

    # 3. Bepaal totale normen
    stikstof_norm = sum((n["stikstof_norm_kg_ha"] or 0) * (n["oppervlakte_ha"] or 0) for n in normen)
    stikstof_dierlijk_norm = sum((n["stikstof_dierlijk_kg_ha"] or 0) * (n["oppervlakte_ha"] or 0) for n in normen)
    fosfaat_norm = sum((n["fosfaat_norm_kg_ha"] or 0) * (n["oppervlakte_ha"] or 0) for n in normen)

    # 4. Haal ALLE bemestingen met deze gebruiksnormen
    placeholders = ",".join("?" for _ in norm_ids)
    bemestingen = conn.execute(f"""
        SELECT b.*, 
               p.perceelnaam AS perceel_naam, 
               p.oppervlakte AS oppervlakte_ha,
               u.meststof AS meststof_naam,
               u.toepassing AS meststof_type,
               gn.stikstof_norm_kg_ha, gn.stikstof_dierlijk_kg_ha, gn.fosfaat_norm_kg_ha,
               g.gewas AS gewas_naam,
               p.grondsoort AS grondsoort
        FROM bemestingen b
        JOIN percelen p ON p.id = b.perceel_id
        JOIN gebruiksnormen gn ON gn.id = b.gebruiksnorm_id
        LEFT JOIN universal_fertilizers u ON u.id = b.meststof_id
        LEFT JOIN stikstof_gewassen_normen g ON g.id = gn.gewas_id
        WHERE b.gebruiksnorm_id IN ({placeholders})
        ORDER BY b.datum DESC
    """, norm_ids).fetchall()

    stikstof_total = 0
    stikstof_dierlijk_total = 0
    fosfaat_total = 0
    bemestingen_details = []

    for b in bemestingen:
        oppervlakte = b["oppervlakte_ha"] or 0
        n = b["n_kg_ha"] or 0
        p2o5 = b["p2o5_kg_ha"] or 0
        eigen_bedrijf = b["eigen_bedrijf"] if "eigen_bedrijf" in b.keys() else 0
        meststof_naam = b["meststof_naam"] or ""
        meststof_type = b["meststof_type"] or ""
        datum = b["datum"]
        maand = 0
        jaar_bem = jaar
        if datum:
            try:
                # Probeer YYYY-MM-DD
                dt = datetime.strptime(datum, "%Y-%m-%d")
            except ValueError:
                try:
                    # Probeer DD-MM-YYYY
                    dt = datetime.strptime(datum, "%d-%m-%Y")
                except ValueError:
                    dt = None
            if dt:
                maand = dt.month
                jaar_bem = dt.year

        gewas = b["gewas_naam"] if "gewas_naam" in b.keys() else ""
        grondsoort = b["grondsoort"] if "grondsoort" in b.keys() else ""

        werking, toepassing, mapped_naam = bereken_werking(conn, jaar_bem, meststof_naam, meststof_type, eigen_bedrijf, gewas, grondsoort, maand)

        eff_n = oppervlakte * n * werking / 100
        n_dier = n if is_dierlijk_meststof(meststof_naam) else 0
        eff_n_dier = oppervlakte * n_dier * werking / 100
        eff_p2o5 = oppervlakte * p2o5 * werking / 100

        stikstof_total += eff_n
        stikstof_dierlijk_total += eff_n_dier
        fosfaat_total += eff_p2o5

        bemestingen_details.append(dict(
            datum=datum,
            perceel=b["perceel_naam"],
            gewas=gewas,
            meststof=meststof_naam,
            oppervlakte=oppervlakte,
            werkingscoeff=werking,
            toepassing=toepassing,
            effectieve_n=eff_n,
            effectieve_n_dier=eff_n_dier,
            effectieve_p2o5=eff_p2o5
        ))

    return {
        "bedrijven": bedrijven,
        "jaren": jaren,
        "stikstof_norm": stikstof_norm,
        "stikstof_dierlijk_norm": stikstof_dierlijk_norm,
        "fosfaat_norm": fosfaat_norm,
        "stikstof_total": stikstof_total,
        "stikstof_dierlijk_total": stikstof_dierlijk_total,
        "fosfaat_total": fosfaat_total,
        "bemestingen_details": bemestingen_details
    }