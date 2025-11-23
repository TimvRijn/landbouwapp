# app/dashboard/dashboard_stats.py (of waar deze functie ook staat)

def bereken_dashboard_stats(conn, user_id, jaar):
    """
    Bereken dashboard statistieken voor alle bedrijven van een gebruiker in een specifiek jaar.
    Groepeer bemestingen op het bedrijf van de GEBRUIKSNORM (gn.bedrijf_id) zodat
    bemestingen bij het juiste bedrijf in de linkerkolom worden opgeteld.
    Werkt nu met PostgreSQL (psycopg2): gebruikt cursor + %s placeholders.
    """

    def fetchall_dicts(cur):
        """Zet cursor-resultaat om naar lijst met dicts (kolomnamen als keys)."""
        rows = cur.fetchall()
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, r)) for r in rows]

    cur = conn.cursor()

    # Bedrijvenlijst voor deze gebruiker
    cur.execute(
        "SELECT id, naam FROM bedrijven WHERE user_id = %s ORDER BY naam",
        (user_id,)
    )
    bedrijven = fetchall_dicts(cur)

    # Beschikbare jaren uit gebruiksnormen
    cur.execute(
        """
        SELECT DISTINCT gn.jaar 
        FROM gebruiksnormen gn
        JOIN bedrijven b ON b.id = gn.bedrijf_id
        WHERE b.user_id = %s AND gn.jaar IS NOT NULL 
        ORDER BY gn.jaar DESC
        """,
        (user_id,)
    )
    jaren = [row["jaar"] for row in fetchall_dicts(cur)]

    def _empty():
        return {
            "bedrijven": bedrijven,
            "jaren": jaren,
            "totaal_stats": {
                "stikstof_norm": 0,
                "stikstof_dierlijk_norm": 0,
                "fosfaat_norm": 0,
                "stikstof_total": 0,
                "stikstof_dierlijk_total": 0,
                "fosfaat_total": 0,
                "kalium_total": 0,
            },
            "bedrijf_stats": [],
            "bemestingen_details": [],
        }

    if not jaar or not bedrijven:
        return _empty()

    # Normen (perceel x bedrijf) voor gekozen jaar
    cur.execute(
        """
        SELECT 
            gn.*,
            p.perceelnaam,
            p.oppervlakte,
            b.naam AS bedrijf_naam,
            sgn.gewas AS gewas_naam
        FROM gebruiksnormen gn
        JOIN percelen p ON p.id = gn.perceel_id
        JOIN bedrijven b ON b.id = gn.bedrijf_id
        LEFT JOIN stikstof_gewassen_normen sgn ON sgn.id = gn.gewas_id
        WHERE b.user_id = %s AND gn.jaar = %s
        ORDER BY b.naam, p.perceelnaam
        """,
        (user_id, jaar),
    )
    normen = fetchall_dicts(cur)

    if not normen:
        return _empty()

    # Totaal normen per bedrijf
    bedrijf_normen = {}
    for norm in normen:
        bedrijf_id = norm["bedrijf_id"]
        d = bedrijf_normen.setdefault(
            bedrijf_id,
            {
                "bedrijf_naam": norm["bedrijf_naam"],
                "stikstof_norm": 0.0,
                "stikstof_dierlijk_norm": 0.0,
                "fosfaat_norm": 0.0,
                "percelen_count": 0,
                "oppervlakte_totaal": 0.0,
            },
        )
        opp = float(norm["oppervlakte"] or 0.0)
        d["stikstof_norm"]          += float(norm["stikstof_norm_kg_ha"] or 0.0) * opp
        d["stikstof_dierlijk_norm"] += float(norm["stikstof_dierlijk_kg_ha"] or 0.0) * opp
        d["fosfaat_norm"]           += float(norm["fosfaat_norm_kg_ha"] or 0.0) * opp
        d["percelen_count"]         += 1
        d["oppervlakte_totaal"]     += opp

    # Alle bemestingen gekoppeld aan de geselecteerde gebruiksnormen
    norm_ids = [str(n["id"]) for n in normen]
    if not norm_ids:
        return _empty()

    placeholders = ",".join(["%s"] * len(norm_ids))

    bemestingen_query = f"""
        SELECT 
            b.*,
            gn.bedrijf_id AS norm_bedrijf_id,

            p.perceelnaam,
            p.oppervlakte,
            p.calculated_area,
            p.grondsoort,

            bedrijf.naam AS bedrijf_naam,
            uf.meststof AS meststof_naam,
            uf.toepassing AS meststof_toepassing,
            sgn.gewas AS gewas_naam,

            gn.stikstof_norm_kg_ha,
            gn.stikstof_dierlijk_kg_ha,
            gn.fosfaat_norm_kg_ha
        FROM bemestingen b
        JOIN percelen p           ON p.id = b.perceel_id
        JOIN gebruiksnormen gn    ON gn.id = b.gebruiksnorm_id
        JOIN bedrijven bedrijf    ON bedrijf.id = b.bedrijf_id
        LEFT JOIN universal_fertilizers uf ON uf.id = b.meststof_id
        LEFT JOIN stikstof_gewassen_normen sgn ON sgn.id = gn.gewas_id
        WHERE b.gebruiksnorm_id IN ({placeholders})
        ORDER BY bedrijf.naam, b.datum DESC
    """
    cur.execute(bemestingen_query, norm_ids)
    bemestingen = fetchall_dicts(cur)

    # Werkelijke totalen per bedrijf, gegroepeerd op gn.bedrijf_id
    bedrijf_werkelijk = {}
    bemestingen_details = []

    for bem in bemestingen:
        bedrijf_id = bem.get("norm_bedrijf_id") or bem.get("bedrijf_id")
        d = bedrijf_werkelijk.setdefault(
            bedrijf_id,
            {
                "stikstof_total": 0.0,
                "stikstof_dierlijk_total": 0.0,
                "fosfaat_total": 0.0,
                "kalium_total": 0.0,
                "bemestingen_count": 0,
            },
        )

        opp = float(bem.get("calculated_area") or bem.get("oppervlakte") or 1.0)

        werkzame_n      = float(bem.get("werkzame_n_kg_ha") or 0.0) * opp
        werkzame_n_dier = float(bem.get("n_dierlijk_kg_ha") or 0.0) * opp
        werkzame_p2o5   = float(bem.get("werkzame_p2o5_kg_ha") or 0.0) * opp
        k2o_total       = float(bem.get("k2o_kg_ha") or 0.0) * opp

        d["stikstof_total"]          += werkzame_n
        d["stikstof_dierlijk_total"] += werkzame_n_dier
        d["fosfaat_total"]           += werkzame_p2o5
        d["kalium_total"]            += k2o_total
        d["bemestingen_count"]       += 1

        bemestingen_details.append({
            "datum": bem.get("datum"),
            "bedrijf": bem.get("bedrijf_naam"),
            "perceel": bem.get("perceelnaam"),
            "gewas": bem.get("gewas_naam"),
            "meststof": bem.get("meststof_naam"),
            "oppervlakte": opp,
            "toepassing": bem.get("meststof_toepassing", ""),
            "werkzame_n": werkzame_n,
            "werkzame_n_dierlijk": werkzame_n_dier,
            "werkzame_p2o5": werkzame_p2o5,
            "k2o_kg_ha": float(bem.get("k2o_kg_ha") or 0.0),
            "k2o_total": k2o_total,
            "n_kg_ha": float(bem.get("n_kg_ha") or 0.0),
            "p2o5_kg_ha": float(bem.get("p2o5_kg_ha") or 0.0),
        })

    # Combineer normen en werkelijk per bedrijf
    bedrijf_stats = []
    totaal_stats = {
        "stikstof_norm": 0.0,
        "stikstof_dierlijk_norm": 0.0,
        "fosfaat_norm": 0.0,
        "stikstof_total": 0.0,
        "stikstof_dierlijk_total": 0.0,
        "fosfaat_total": 0.0,
        "kalium_total": 0.0,
    }

    for bedrijf_id, ndata in bedrijf_normen.items():
        wdata = bedrijf_werkelijk.get(
            bedrijf_id,
            {
                "stikstof_total": 0.0,
                "stikstof_dierlijk_total": 0.0,
                "fosfaat_total": 0.0,
                "kalium_total": 0.0,
                "bemestingen_count": 0,
            },
        )

        stikstof_pct = (
            (wdata["stikstof_total"] / ndata["stikstof_norm"] * 100.0)
            if ndata["stikstof_norm"] > 0
            else 0.0
        )
        stikstof_dierlijk_pct = (
            (wdata["stikstof_dierlijk_total"] / ndata["stikstof_dierlijk_norm"] * 100.0)
            if ndata["stikstof_dierlijk_norm"] > 0
            else 0.0
        )
        fosfaat_pct = (
            (wdata["fosfaat_total"] / ndata["fosfaat_norm"] * 100.0)
            if ndata["fosfaat_norm"] > 0
            else 0.0
        )

        bedrijf_stats.append({
            "bedrijf_id": bedrijf_id,
            "bedrijf_naam": ndata["bedrijf_naam"],
            "percelen_count": ndata["percelen_count"],
            "oppervlakte_totaal": ndata["oppervlakte_totaal"],
            "stikstof_norm": ndata["stikstof_norm"],
            "stikstof_dierlijk_norm": ndata["stikstof_dierlijk_norm"],
            "fosfaat_norm": ndata["fosfaat_norm"],
            "stikstof_total": wdata["stikstof_total"],
            "stikstof_dierlijk_total": wdata["stikstof_dierlijk_total"],
            "fosfaat_total": wdata["fosfaat_total"],
            "kalium_total": wdata["kalium_total"],
            "stikstof_percentage": stikstof_pct,
            "stikstof_dierlijk_percentage": stikstof_dierlijk_pct,
            "fosfaat_percentage": fosfaat_pct,
            "bemestingen_count": wdata["bemestingen_count"],
        })

        # Totalen
        totaal_stats["stikstof_norm"]           += ndata["stikstof_norm"]
        totaal_stats["stikstof_dierlijk_norm"]  += ndata["stikstof_dierlijk_norm"]
        totaal_stats["fosfaat_norm"]            += ndata["fosfaat_norm"]
        totaal_stats["stikstof_total"]          += wdata["stikstof_total"]
        totaal_stats["stikstof_dierlijk_total"] += wdata["stikstof_dierlijk_total"]
        totaal_stats["fosfaat_total"]           += wdata["fosfaat_total"]
        totaal_stats["kalium_total"]            += wdata["kalium_total"]

    return {
        "bedrijven": bedrijven,
        "jaren": jaren,
        "totaal_stats": totaal_stats,
        "bedrijf_stats": bedrijf_stats,
        "bemestingen_details": bemestingen_details,
    }
