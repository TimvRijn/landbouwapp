# app/rapportage/rapportage.py
from __future__ import annotations
from flask import (
    Blueprint, render_template, request, redirect,
    session, url_for, flash, send_file
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
    if not ids:
        return "", params
    placeholders = []
    for _id in ids:
        placeholders.append("%s")
        params.append(_id)
    return f" AND {column} IN ({', '.join(placeholders)}) ", params


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
                SUM(g.stikstof_norm_kg_ha * COALESCE(p.oppervlakte,0)) AS n_toegestaan,
                SUM(g.stikstof_dierlijk_kg_ha * COALESCE(p.oppervlakte,0)) AS n_toegestaan_dierlijk,
                -- P (fosfaat) -> alleen totale gebruiksruimte
                SUM(g.fosfaat_norm_kg_ha * COALESCE(p.oppervlakte,0)) AS p_toegestaan
            FROM gebruiksnormen g
            JOIN percelen p ON g.perceel_id = p.id
            JOIN bedrijven b ON g.bedrijf_id = b.id
            WHERE g.user_id = %s AND g.jaar = %s
            {clause}
            GROUP BY g.bedrijf_id, b.naam
        """, params)

        data = {}
        for r in cur.fetchall():
            data[r["bedrijf_id"]] = {
                "bedrijf_id": r["bedrijf_id"],
                "bedrijf_naam": r["bedrijf_naam"],
                # N
                "n_toegestaan": float(r["n_toegestaan"] or 0),
                "n_toegestaan_dierlijk": float(r["n_toegestaan_dierlijk"] or 0),
                # P (alleen totaal)
                "p_toegestaan": float(r["p_toegestaan"] or 0),
            }
        return data

    finally:
        conn.close()



def _query_bemesting(user_id, jaar, bedrijf_ids):
    """
    Haalt per bedrijf:
    - N dierlijk + N kunstmest
    - P dierlijk + P kunstmest (afgeleid uit werkzame_p2o5_kg_ha)
    """
    conn, cur = db.get_dict_cursor()
    try:
        params = [user_id, jaar]
        clause, params = _build_in_clause("b.bedrijf_id", bedrijf_ids, params)

        cur.execute(f"""
            SELECT
                b.bedrijf_id,
                br.naam AS bedrijf_naam,
                -- N
                SUM(b.n_dierlijk_kg_ha * COALESCE(p.oppervlakte,0)) AS n_dierlijk_kg,
                SUM(GREATEST(b.werkzame_n_kg_ha - b.n_dierlijk_kg_ha, 0) * COALESCE(p.oppervlakte,0))
                    AS n_kunstmest_kg,
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
                ) AS p_kunstmest_kg
            FROM bemestingen b
            JOIN gebruiksnormen g ON b.gebruiksnorm_id = g.id
            JOIN percelen p ON b.perceel_id = p.id
            JOIN bedrijven br ON b.bedrijf_id = br.id
            WHERE g.user_id = %s
              AND EXTRACT(YEAR FROM b.datum)::INT = %s
              {clause}
            GROUP BY b.bedrijf_id, br.naam
        """, params)

        data = {}
        for r in cur.fetchall():
            data[r["bedrijf_id"]] = {
                "bedrijf_id": r["bedrijf_id"],
                "bedrijf_naam": r["bedrijf_naam"],
                # N
                "n_dierlijk_kg": float(r["n_dierlijk_kg"] or 0),
                "n_kunstmest_kg": float(r["n_kunstmest_kg"] or 0),
                # P
                "p_dierlijk_kg": float(r["p_dierlijk_kg"] or 0),
                "p_kunstmest_kg": float(r["p_kunstmest_kg"] or 0),
            }
        return data

    finally:
        conn.close()



def _combine(normen, bemesting, jaar, mode, hoofd_bedrijf_id):
    """
    Combineert normen + bemesting per bedrijf en rekent:
    - N: totaal, over, af te voeren, dierlijk over/af te voeren
    - P: totaal, over, af te voeren (geen aparte P-dierlijke norm)
    """
    bedrijven = set(normen.keys()) | set(bemesting.keys())
    rows = []

    for bedrijf_id in bedrijven:
        n = normen.get(bedrijf_id, {})
        b = bemesting.get(bedrijf_id, {})

        row = {
            "bedrijf_id": bedrijf_id,
            "bedrijf_naam": n.get("bedrijf_naam") or b.get("bedrijf_naam"),
            "jaar": jaar,

            # N-ruimte
            "n_toegestaan": n.get("n_toegestaan", 0),
            "n_toegestaan_dierlijk": n.get("n_toegestaan_dierlijk", 0),
            # N-bemesting
            "n_dierlijk_kg": b.get("n_dierlijk_kg", 0),
            "n_kunstmest_kg": b.get("n_kunstmest_kg", 0),

            # P-ruimte (alleen totaal)
            "p_toegestaan": n.get("p_toegestaan", 0),
            # P-bemesting
            "p_dierlijk_kg": b.get("p_dierlijk_kg", 0),
            "p_kunstmest_kg": b.get("p_kunstmest_kg", 0),
        }
        rows.append(row)

    # kunstmest verdelen (N én P) op hoofd-bedrijf
    if mode == "hoofd_bedrijf" and hoofd_bedrijf_id:
        totaal_n = sum(r["n_kunstmest_kg"] for r in rows)
        totaal_p = sum(r["p_kunstmest_kg"] for r in rows)

        for r in rows:
            if r["bedrijf_id"] == hoofd_bedrijf_id:
                r["n_kunstmest_kg"] = totaal_n
                r["p_kunstmest_kg"] = totaal_p
            else:
                r["n_kunstmest_kg"] = 0
                r["p_kunstmest_kg"] = 0

    # berekeningen N + P
    for r in rows:
        # N totaal
        n_tot = r["n_dierlijk_kg"] + r["n_kunstmest_kg"]
        r["n_bemest_totaal"] = n_tot
        r["n_over"] = max(0, r["n_toegestaan"] - n_tot)
        r["n_af_te_voeren"] = max(0, n_tot - r["n_toegestaan"])

        r["n_dierlijk_over"] = max(0, r["n_toegestaan_dierlijk"] - r["n_dierlijk_kg"])
        r["n_dierlijk_af_te_voeren"] = max(0, r["n_dierlijk_kg"] - r["n_toegestaan_dierlijk"])

        # P totaal (dierlijk + kunstmest vallen in dezelfde norm)
        p_tot = r["p_dierlijk_kg"] + r["p_kunstmest_kg"]
        r["p_bemest_totaal"] = p_tot
        r["p_over"] = max(0, r["p_toegestaan"] - p_tot)
        r["p_af_te_voeren"] = max(0, p_tot - r["p_toegestaan"])

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
        "N ruimte", "N dierl. ruimte", "N dierlijk", "N kunstmest",
        "N totaal", "N over", "N af te voeren", "N dierl. over", "N dierl. af te voeren",
        # P
        "P ruimte", "P dierlijk", "P kunstmest",
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
        ws.write(r_i, c, r["n_dierlijk_kg"]); c += 1
        ws.write(r_i, c, r["n_kunstmest_kg"]); c += 1
        ws.write(r_i, c, r["n_bemest_totaal"]); c += 1
        ws.write(r_i, c, r["n_over"]); c += 1
        ws.write(r_i, c, r["n_af_te_voeren"]); c += 1
        ws.write(r_i, c, r["n_dierlijk_over"]); c += 1
        ws.write(r_i, c, r["n_dierlijk_af_te_voeren"]); c += 1

        # P
        ws.write(r_i, c, r.get("p_toegestaan", 0)); c += 1
        ws.write(r_i, c, r.get("p_dierlijk_kg", 0)); c += 1
        ws.write(r_i, c, r.get("p_kunstmest_kg", 0)); c += 1
        ws.write(r_i, c, r.get("p_bemest_totaal", 0)); c += 1
        ws.write(r_i, c, r.get("p_over", 0)); c += 1
        ws.write(r_i, c, r.get("p_af_te_voeren", 0)); c += 1

    wb.close()
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name="gebruiksruimte.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def _export_pdf(rows):
    """
    Maak een simpele PDF-rapportage vanuit rows.
    Zelfde info als in Excel: N- en P-ruimte/bemesting.
    """
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=10)

    headers = [
        "Bedrijf", "Jaar",
        # N
        "N ruimte", "N dierl. ruimte", "N dierlijk", "N kunstmest",
        "N totaal", "N over", "N af te voeren", "N dierl. over", "N dierl. af te voeren",
        # P
        "P ruimte", "P dierlijk", "P kunstmest",
        "P totaal", "P over", "P af te voeren",
    ]

    # Eenvoudige tabel-layout
    line_height = 6
    col_width = pdf.w / len(headers) - 1  # heel basic verdeling

    # Header
    for h in headers:
        pdf.cell(col_width, line_height, h, border=1)
    pdf.ln(line_height)

    # Data-rijen
    for r in rows:
        values = [
            str(r["bedrijf_naam"]),
            str(r["jaar"]),
            # N
            f"{r['n_toegestaan']:.1f}",
            f"{r['n_toegestaan_dierlijk']:.1f}",
            f"{r['n_dierlijk_kg']:.1f}",
            f"{r['n_kunstmest_kg']:.1f}",
            f"{r['n_bemest_totaal']:.1f}",
            f"{r['n_over']:.1f}",
            f"{r['n_af_te_voeren']:.1f}",
            f"{r['n_dierlijk_over']:.1f}",
            f"{r['n_dierlijk_af_te_voeren']:.1f}",
            # P
            f"{r.get('p_toegestaan', 0):.1f}",
            f"{r.get('p_dierlijk_kg', 0):.1f}",
            f"{r.get('p_kunstmest_kg', 0):.1f}",
            f"{r.get('p_bemest_totaal', 0):.1f}",
            f"{r.get('p_over', 0):.1f}",
            f"{r.get('p_af_te_voeren', 0):.1f}",
        ]

        for v in values:
            pdf.cell(col_width, line_height, v, border=1)
        pdf.ln(line_height)

    pdf_bytes = pdf.output(dest="S")

    buffer = io.BytesIO(pdf_bytes)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="gebruiksruimte.pdf",
        mimetype="application/pdf"
    )



# ---------------- ROUTES ----------------

@rapportage_bp.route("/", methods=["GET"])
@login_required
def rapportage():
    user_id = effective_user_id()

    jaren = _get_jaren(user_id)
    bedrijven = _get_bedrijven(user_id)

    jaar = request.args.get("jaar", type=int) or (jaren[0] if jaren else None)
    bedrijf_ids = request.args.getlist("bedrijf_ids") or [b["id"] for b in bedrijven]
    mode = request.args.get("kunstmest_mode", "per_bedrijf")
    hoofd_bedrijf_id = request.args.get("hoofd_bedrijf_id")
    action = request.args.get("action", "view")

    rows = []
    if jaar:
        normen = _query_normen(user_id, jaar, bedrijf_ids)
        bemesting = _query_bemesting(user_id, jaar, bedrijf_ids)
        rows = _combine(normen, bemesting, jaar, mode, hoofd_bedrijf_id)

    # EXPORT EXCEL
    if action == "excel" and rows:
        return _export_excel(rows)

    # EXPORT PDF
    if action == "pdf" and rows:
        return _export_pdf(rows)



    # NORMALE PAGINA
    return render_template(
        "rapportage/rapportage.html",
        jaren=jaren,
        bedrijven=bedrijven,
        selected_jaar=jaar,
        geselecteerde_bedrijf_ids=bedrijf_ids,
        kunstmest_mode=mode,
        hoofd_bedrijf_id=hoofd_bedrijf_id,
        rows=rows,
        pdf_mode=False
    )
