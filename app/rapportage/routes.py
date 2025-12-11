# app/rapportage/rapportage.py
from __future__ import annotations
from flask import (
    Blueprint, render_template, request, redirect,
    session, url_for, flash, send_file, make_response
)
import io
import xlsxwriter
from fpdf import FPDF


import app.models.database_beheer as db
from app.gebruikers.auth_utils import login_required, effective_user_id


rapportage_bp = Blueprint(
    "rapportage",
    __name__,
    template_folder="templates",
    static_folder="static",
    url_prefix="/rapportage"
)


# ---------------- Helper functions ----------------

def _get_jaren(user_id):
    conn, cur = db.get_dict_cursor()
    try:
        cur.execute("""
            SELECT DISTINCT jaar
            FROM gebruiksnormen
            WHERE user_id = %s
            ORDER BY jaar DESC
        """, (user_id,))
        return [r["jaar"] for r in cur.fetchall()]
    finally:
        conn.close()


def _get_bedrijven(user_id):
    conn, cur = db.get_dict_cursor()
    try:
        cur.execute("""
            SELECT id, naam, plaats
            FROM bedrijven
            WHERE user_id = %s
            ORDER BY naam
        """, (user_id,))
        return cur.fetchall()
    finally:
        conn.close()


def _build_in_clause(column, ids, params):
    """
    ids:
      - None  -> geen filter op dit veld
      - []    -> bewust GEEN items geselecteerd -> WHERE ... AND 1=0
      - [..]  -> normale IN-filter
    """
    # Geen filter
    if ids is None:
        return "", params

    # Bewust geen bedrijven geselecteerd -> geen resultaten
    if len(ids) == 0:
        return " AND 1 = 0 ", params

    # Normale IN-clause
    placeholders = ", ".join(["%s"] * len(ids))
    params.extend(ids)
    return f" AND {column} IN ({placeholders}) ", params



def _query_normen(user_id, jaar, bedrijf_ids):
    """
    Haalt per bedrijf:
    - N-gebruiksruimte (totaal + dierlijk)
    - P-gebruiksruimte (alleen totaal; dierlijk valt daarin)
    """
    conn, cur = db.get_dict_cursor()
    try:
        params = [user_id, jaar]
        clause, params = _build_in_clause("g.bedrijf_id", bedrijf_ids, params)

        cur.execute(f"""
            SELECT
                g.bedrijf_id,
                b.naam AS bedrijf_naam,
                -- N
                SUM(g.stikstof_norm_kg_ha * p.oppervlakte) AS n_toegestaan,
                SUM(g.stikstof_dierlijk_kg_ha * p.oppervlakte) AS n_toegestaan_dierlijk,
                -- P (fosfaat) -> alleen totale gebruiksruimte
                SUM(g.fosfaat_norm_kg_ha * p.oppervlakte) AS p_toegestaan
            FROM gebruiksnormen g
            JOIN percelen p ON g.perceel_id = p.id
            JOIN bedrijven b ON g.bedrijf_id = b.id
            WHERE g.user_id = %s AND g.jaar = %s
            {clause}
            GROUP BY g.bedrijf_id, b.naam
        """, params)

        data = {}
        for r in cur.fetchall():
            # Ruwe waarden uit de query
            n_toegestaan = float(r["n_toegestaan"] or 0)
            n_toegestaan_dierlijk = float(r["n_toegestaan_dierlijk"] or 0)
            p_toegestaan = float(r["p_toegestaan"] or 0)

            # NIEUWE REGEL:
            # dierlijke N-gebruiksruimte mag niet hoger zijn dan totale N-gebruiksruimte
            if n_toegestaan_dierlijk > n_toegestaan:
                n_toegestaan_dierlijk = n_toegestaan

            data[r["bedrijf_id"]] = {
                "bedrijf_id": r["bedrijf_id"],
                "bedrijf_naam": r["bedrijf_naam"],
                # N
                "n_toegestaan": n_toegestaan,
                "n_toegestaan_dierlijk": n_toegestaan_dierlijk,
                # P (alleen totaal)
                "p_toegestaan": p_toegestaan,
            }
        return data

    finally:
        conn.close()



def _query_bemesting(user_id, jaar, bedrijf_ids):
    """
    Haalt per bedrijf:
    - N dierlijk + N overige mest
    - P dierlijk + P overige mest (afgeleid uit werkzame_p2o5_kg_ha)

    Belangrijk:
    We groeperen nu op g.bedrijf_id (het bedrijf van de gebruiksnorm / perceel),
    zodat de bemesting terechtkomt bij hetzelfde bedrijf als de normen.
    """
    conn, cur = db.get_dict_cursor()
    try:
        params = [user_id, jaar]
        # filter op g.bedrijf_id i.p.v. b.bedrijf_id
        clause, params = _build_in_clause("g.bedrijf_id", bedrijf_ids, params)

        cur.execute(f"""
            SELECT
                g.bedrijf_id,
                br_norm.naam AS bedrijf_naam,

                -- N
                SUM(b.n_dierlijk_kg_ha * COALESCE(p.oppervlakte,0)) AS n_dierlijk_kg,
                SUM(
                    GREATEST(b.werkzame_n_kg_ha - b.n_dierlijk_kg_ha, 0)
                    * COALESCE(p.oppervlakte,0)
                ) AS n_overige_kg,

                -- P (fosfaat) op basis van werkzame_p2o5_kg_ha
                SUM(
                    CASE
                        WHEN b.n_dierlijk_kg_ha > 0
                             THEN b.werkzame_p2o5_kg_ha * COALESCE(p.oppervlakte,0)
                        ELSE 0
                    END
                ) AS p_dierlijk_kg,
                SUM(
                    CASE
                        WHEN b.n_dierlijk_kg_ha > 0
                             THEN 0
                        ELSE b.werkzame_p2o5_kg_ha * COALESCE(p.oppervlakte,0)
                    END
                ) AS p_overige_kg
            FROM bemestingen b
            JOIN gebruiksnormen g ON b.gebruiksnorm_id = g.id
            JOIN percelen p       ON b.perceel_id = p.id
            JOIN bedrijven br_norm ON g.bedrijf_id = br_norm.id
            WHERE g.user_id = %s
              AND EXTRACT(YEAR FROM b.datum)::INT = %s
              {clause}
            GROUP BY g.bedrijf_id, br_norm.naam
        """, params)

        data = {}
        for r in cur.fetchall():
            data[r["bedrijf_id"]] = {
                "bedrijf_id": r["bedrijf_id"],
                "bedrijf_naam": r["bedrijf_naam"],
                # N
                "n_dierlijk_kg": float(r["n_dierlijk_kg"] or 0),
                "n_overige_kg": float(r["n_overige_kg"] or 0),
                # P
                "p_dierlijk_kg": float(r["p_dierlijk_kg"] or 0),
                "p_overige_kg": float(r["p_overige_kg"] or 0),
            }
        return data

    finally:
        conn.close()




def _combine(normen, bemesting, jaar, mode, hoofd_bedrijf_id):
    # hoofd_bedrijf_id normaliseren naar string of None
    hoofd_bedrijf_id_str = str(hoofd_bedrijf_id) if hoofd_bedrijf_id else None

    bedrijven = set(normen.keys()) | set(bemesting.keys())
    rows = []

    for bedrijf_id in bedrijven:
        n = normen.get(bedrijf_id, {})
        b = bemesting.get(bedrijf_id, {})

        row = {
            "bedrijf_id": bedrijf_id,  # dit mag UUID blijven
            "bedrijf_naam": n.get("bedrijf_naam") or b.get("bedrijf_naam"),
            "jaar": jaar,

            # N
            "n_toegestaan": n.get("n_toegestaan", 0.0),
            "n_toegestaan_dierlijk": n.get("n_toegestaan_dierlijk", 0.0),
            "n_dierlijk_kg": b.get("n_dierlijk_kg", 0.0),
            "n_overige_kg": b.get("n_overige_kg", 0.0),

            # P
            "p_toegestaan": n.get("p_toegestaan", 0.0),
            "p_dierlijk_kg": b.get("p_dierlijk_kg", 0.0),
            "p_overige_kg": b.get("p_overige_kg", 0.0),
        }
        rows.append(row)

    # KUNSTMEST (nu: overige mest) HERVERDELEN
    if hoofd_bedrijf_id_str is not None:
        totaal_n_overige = sum(r["n_overige_kg"] for r in rows)
        totaal_p_overige = sum(r["p_overige_kg"] for r in rows)

        for r in rows:
            if str(r["bedrijf_id"]) == hoofd_bedrijf_id_str:
                r["n_overige_kg"] = totaal_n_overige
                r["p_overige_kg"] = totaal_p_overige
            else:
                r["n_overige_kg"] = 0.0
                r["p_overige_kg"] = 0.0

    # -------------- SALDO'S UITREKENEN PER BEDRIJF --------------
    for r in rows:
        # N totaal (organisch + overige mest)
        n_tot = r["n_dierlijk_kg"] + r["n_overige_kg"]
        r["n_bemest_totaal"] = n_tot
        r["n_over"] = max(0.0, r["n_toegestaan"] - n_tot)
        r["n_af_te_voeren"] = max(0.0, n_tot - r["n_toegestaan"])

        # N organisch t.o.v. dierlijke norm (organische mest eerst)
        r["n_org_over"] = max(0.0, r["n_toegestaan_dierlijk"] - r["n_dierlijk_kg"])
        r["n_org_af_te_voeren"]  = max(0.0, r["n_dierlijk_kg"] - r["n_toegestaan_dierlijk"])

        # P totaal (organisch + overige mest)
        p_tot = r["p_dierlijk_kg"] + r["p_overige_kg"]
        r["p_bemest_totaal"] = p_tot
        r["p_over"] = max(0.0, r["p_toegestaan"] - p_tot)
        r["p_af_te_voeren"] = max(0.0, p_tot - r["p_toegestaan"])

        # P organische mest saldo: organische mest krijgt als eerste de P-ruimte
        r["p_org_over"] = max(0.0, r["p_toegestaan"] - r["p_dierlijk_kg"])
        r["p_org_af_te_voeren"] = max(0.0, r["p_dierlijk_kg"] - r["p_toegestaan"])


    return rows




def _export_excel(rows):
    """
    Excel met:
    - N: ruimte, dierlijk, kunstmest, totaal, over, af te voeren, dierlijk over/afvoer
    - P: ruimte, dierlijk, kunstmest, totaal, over, af te voeren (geen P-dierlijke norm)
    """
    output = io.BytesIO()
    wb = xlsxwriter.Workbook(output, {"in_memory": True})
    ws = wb.add_worksheet("Rapport")

    headers = [
        "Bedrijf", "Jaar",
        # N
        "N ruimte", "N dierl. ruimte", "N organische mest", "N overige mest",
        "N totaal", "N over", "N af te voeren", "N org. over", "N org. af te voeren",
        # P
        "P ruimte", "P organisch", "P overige mest",
        "P totaal", "P over", "P af te voeren",
    ]

    for c, h in enumerate(headers):
        ws.write(0, c, h)

    for r_i, r in enumerate(rows, start=1):
        c = 0
        ws.write(r_i, c, r["bedrijf_naam"]); c += 1
        ws.write(r_i, c, r["jaar"]); c += 1

        # N
        ws.write(r_i, c, r["n_toegestaan"]); c += 1
        ws.write(r_i, c, r["n_toegestaan_dierlijk"]); c += 1
        ws.write(r_i, c, r["n_dierlijk_kg"]); c += 1         # organische mest
        ws.write(r_i, c, r["n_overige_kg"]); c += 1          # overige mest
        ws.write(r_i, c, r["n_bemest_totaal"]); c += 1
        ws.write(r_i, c, r["n_over"]); c += 1
        ws.write(r_i, c, r["n_af_te_voeren"]); c += 1
        ws.write(r_i, c, r["n_org_over"]); c += 1
        ws.write(r_i, c, r["n_org_af_te_voeren"]); c += 1

        # P
        ws.write(r_i, c, r.get("p_toegestaan", 0)); c += 1
        ws.write(r_i, c, r.get("p_dierlijk_kg", 0)); c += 1   # organisch
        ws.write(r_i, c, r.get("p_overige_kg", 0)); c += 1    # overige mest
        ws.write(r_i, c, r.get("p_bemest_totaal", 0)); c += 1
        ws.write(r_i, c, r.get("p_over", 0)); c += 1
        ws.write(r_i, c, r.get("p_af_te_voeren", 0)); c += 1

    wb.close()
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name="Rapportage Gebruiksruimte.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def _export_pdf(rows, selected_jaar, bedrijven, geselecteerde_bedrijf_ids,
                hoofd_bedrijf_id, kunstmest_mode):
    """
    Render de moderne PDF HTML-template naar een echte PDF met WeasyPrint.
    """
    # 1. HTML renderen
    html_string = render_template(
        "rapportage/pdf_modern.html",
        rows=rows,
        selected_jaar=selected_jaar,
        bedrijven=bedrijven,
        geselecteerde_bedrijf_ids=geselecteerde_bedrijf_ids,
        hoofd_bedrijf_id=hoofd_bedrijf_id,
        kunstmest_mode=kunstmest_mode
    )

    # 2. PDF genereren
    pdf_bytes = HTML(string=html_string).write_pdf()

    # 3. Download-response
    response = make_response(pdf_bytes)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "attachment; filename=rapportage.pdf"
    return response



# ---------------- ROUTES ----------------

@rapportage_bp.route("/", methods=["GET"])
@login_required
def rapportage():
    user_id = effective_user_id()

    jaren = _get_jaren(user_id)
    bedrijven = _get_bedrijven(user_id)

    # Is dit de allereerste keer (geen querystring)?
    args_present = bool(request.args)

    # ---- JAAR ----
    jaar = request.args.get("jaar", type=int)
    if jaar is None and jaren:
        jaar = jaren[0]

    # ---- BEDRIJVEN (checkboxen) ----
    # IDs komen als string (UUID) binnen
    geselecteerde_bedrijf_ids = request.args.getlist("bedrijf_ids")  # lijst van strings

    if not args_present:
        # Eerste pagina-load: alle bedrijven geselecteerd
        geselecteerde_bedrijf_ids = [str(b["id"]) for b in bedrijven]

    # Wat naar de SQL gaat
    if not args_present:
        # eerste load -> geen filter -> alle bedrijven
        bedrijf_ids_filter = None
    else:
        if len(geselecteerde_bedrijf_ids) == 0:
            # gebruiker heeft alles uitgezet -> 0 rijen
            bedrijf_ids_filter = []
        else:
            bedrijf_ids_filter = geselecteerde_bedrijf_ids

    # ---- HOOFD-BEDRIJF (radio) ----
    hoofd_bedrijf_id = request.args.get("hoofd_bedrijf_id", "")
    if not hoofd_bedrijf_id:
        hoofd_bedrijf_id = None  # geen hoofd-bedrijf

    if hoofd_bedrijf_id is not None:
        kunstmest_mode = "hoofd_bedrijf"
    else:
        kunstmest_mode = "per_bedrijf"

    # ---- ACTIE ----
    action = request.args.get("action", "view")

    # ---- DATA OPHALEN ----
    rows = []
    if jaar:
        normen = _query_normen(user_id, jaar, bedrijf_ids_filter)
        bemesting = _query_bemesting(user_id, jaar, bedrijf_ids_filter)
        rows = _combine(normen, bemesting, jaar, kunstmest_mode, hoofd_bedrijf_id)

    # ---- EXPORTS ----
    if action == "excel":
        return _export_excel(rows)
    elif action == "pdf": 
        return _export_pdf(rows)

    # ---- TEMPLATE ----
    return render_template(
        "rapportage/rapportage.html",
        jaren=jaren,
        bedrijven=bedrijven,
        selected_jaar=jaar,
        geselecteerde_bedrijf_ids=geselecteerde_bedrijf_ids,  # lijst van strings!
        hoofd_bedrijf_id=hoofd_bedrijf_id,                    # string of None
        rows=rows,
        pdf_mode=False
    )
