from flask import Blueprint, render_template, request, redirect, session, url_for, flash
import uuid
import app.models.database_beheer as db
import pandas as pd
from app.gebruikers.auth_utils import login_required, effective_user_id

bedrijven_bp = Blueprint(
    'bedrijven',
    __name__,
    template_folder='templates',
    static_folder='static',
    url_prefix='/bedrijven'
)

@bedrijven_bp.route('/', methods=['GET', 'POST'])
@login_required
def bedrijven():
    eff_uid = effective_user_id()

    if request.method == 'POST':
        naam = request.form['naam'].strip()
        plaats = request.form.get('plaats', '').strip()

        if not naam:
            flash("Naam is verplicht.", "danger")
            return redirect(url_for('bedrijven.bedrijven'))

        conn = db.get_connection()
        try:
            with conn.cursor() as c:
                # Dubbelcheck of bedrijf al bestaat voor deze user
                c.execute(
                    "SELECT 1 FROM bedrijven WHERE naam = %s AND user_id = %s",
                    (naam, eff_uid)
                )
                exists = c.fetchone()

                if exists:
                    flash(f"Bedrijf '{naam}' bestaat al.", "warning")
                else:
                    c.execute(
                        """
                        INSERT INTO bedrijven (id, naam, plaats, user_id)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (str(uuid.uuid4()), naam, plaats or None, eff_uid)
                    )
                    conn.commit()
                    flash(f"Bedrijf '{naam}' toegevoegd.", "success")
        finally:
            conn.close()

        return redirect(url_for('bedrijven.bedrijven'))

    # GET
    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            # 1) Alle bedrijven voor deze user
            c.execute(
                "SELECT * FROM bedrijven WHERE user_id = %s",
                (eff_uid,)
            )
            bedrijven = c.fetchall()

            # 2) Aantal percelen voor deze user
            c.execute(
                "SELECT COUNT(*) FROM percelen WHERE user_id = %s",
                (eff_uid,)
            )
            row = c.fetchone()
            percelen_count = row[0] if row else 0
    finally:
        conn.close()

    return render_template(
        'bedrijven/bedrijven.html',
        bedrijven=bedrijven,
        percelen_count=percelen_count  # 👈 deze heb je nodig in de template
    )


@bedrijven_bp.route('/bedrijven_delete/<id>', methods=['POST'])
@login_required
def bedrijven_delete(id):
    eff_uid = effective_user_id()
    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                "SELECT naam FROM bedrijven WHERE id = %s AND user_id = %s",
                (id, eff_uid)
            )
            bedrijf = c.fetchone()

            if bedrijf:
                c.execute(
                    "DELETE FROM bedrijven WHERE id = %s AND user_id = %s",
                    (id, eff_uid)
                )
                flash(f"Bedrijf '{bedrijf[0]}' verwijderd.", "success")
            else:
                flash("Niet gevonden of geen toegang.", "danger")

            conn.commit()
    finally:
        conn.close()

    return redirect(url_for('bedrijven.bedrijven'))


@bedrijven_bp.route('/bedrijven_edit/<id>', methods=['GET', 'POST'])
@login_required
def bedrijven_edit(id):
    eff_uid = effective_user_id()
    conn = db.get_connection()

    if request.method == 'POST':
        naam = request.form['naam'].strip()
        plaats = request.form.get('plaats', '').strip()

        if not naam:
            flash("Naam is verplicht.", "danger")
            conn.close()
            return redirect(url_for('bedrijven.bedrijven'))

        try:
            with conn.cursor() as c:
                # Uniekheid bijwerken mag, zolang naam uniek blijft per user
                c.execute(
                    """
                    SELECT 1
                    FROM bedrijven
                    WHERE naam = %s AND user_id = %s AND id <> %s
                    """,
                    (naam, eff_uid, id)
                )
                exists = c.fetchone()

                if exists:
                    flash(f"Bedrijf '{naam}' bestaat al.", "warning")
                    return redirect(url_for('bedrijven.bedrijven'))

                c.execute(
                    """
                    UPDATE bedrijven
                    SET naam = %s, plaats = %s
                    WHERE id = %s AND user_id = %s
                    """,
                    (naam, plaats or None, id, eff_uid)
                )
                conn.commit()
                flash("Bedrijf bijgewerkt.", "success")
        finally:
            conn.close()

        return redirect(url_for('bedrijven.bedrijven'))

    # GET: bestaand bedrijf ophalen
    try:
        with conn.cursor() as c:
            c.execute(
                "SELECT * FROM bedrijven WHERE id = %s AND user_id = %s",
                (id, eff_uid)
            )
            bedrijf = c.fetchone()
    finally:
        conn.close()

    if bedrijf is None:
        flash("Niet gevonden of geen toegang.", "danger")
        return redirect(url_for('bedrijven.bedrijven'))

    return render_template('bedrijven/bedrijven.html', bedrijf=bedrijf)


