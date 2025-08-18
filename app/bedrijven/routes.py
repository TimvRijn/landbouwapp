from flask import Blueprint, render_template, request, redirect, session, url_for, flash
import uuid
import app.models.database_beheer as db
import pandas as pd
from app.gebruikers.auth_utils import login_required

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
    if request.method == 'POST':
        naam = request.form['naam'].strip()
        plaats = request.form.get('plaats', '').strip()
        if not naam:
            flash("Naam is verplicht.", "danger")
            return redirect(url_for('bedrijven.bedrijven'))
        conn = db.get_connection()
        c = conn.cursor()
        # Dubbelcheck of bedrijf al bestaat voor deze user
        exists = c.execute("SELECT 1 FROM bedrijven WHERE naam=? AND user_id=?", (naam, session['user_id'])).fetchone()
        if exists:
            flash(f"Bedrijf '{naam}' bestaat al.", "warning")
        else:
            c.execute('INSERT INTO bedrijven (id, naam, plaats, user_id) VALUES (?, ?, ?, ?)', (
                str(uuid.uuid4()), naam, plaats or None, session['user_id']
            ))
            conn.commit()
            flash(f"Bedrijf '{naam}' toegevoegd.", "success")
        conn.close()
        return redirect(url_for('bedrijven.bedrijven'))

    conn = db.get_connection()
    bedrijven = conn.cursor().execute(
        'SELECT * FROM bedrijven WHERE user_id=?', (session['user_id'],)
    ).fetchall()
    conn.close()
    return render_template('bedrijven/bedrijven.html', bedrijven=bedrijven)

@bedrijven_bp.route('/bedrijven_delete/<id>', methods=['POST'])
@login_required
def bedrijven_delete(id):
    conn = db.get_connection()
    c = conn.cursor()
    bedrijf = c.execute('SELECT naam FROM bedrijven WHERE id=? AND user_id=?', (id, session['user_id'])).fetchone()
    if bedrijf:
        c.execute('DELETE FROM bedrijven WHERE id=? AND user_id=?', (id, session['user_id']))
        flash(f"Bedrijf '{bedrijf[0]}' verwijderd.", "success")
    else:
        flash("Niet gevonden of geen toegang.", "danger")
    conn.commit()
    conn.close()
    return redirect(url_for('bedrijven.bedrijven'))

@bedrijven_bp.route('/bedrijven_edit/<id>', methods=['GET', 'POST'])
@login_required
def bedrijven_edit(id):
    conn = db.get_connection()
    c = conn.cursor()
    if request.method == 'POST':
        naam = request.form['naam'].strip()
        plaats = request.form.get('plaats', '').strip()
        if not naam:
            flash("Naam is verplicht.", "danger")
            return redirect(url_for('bedrijven.bedrijven'))
        # Uniekheid bijwerken mag, zolang naam uniek blijft per user
        exists = c.execute(
            "SELECT 1 FROM bedrijven WHERE naam=? AND user_id=? AND id<>?", (naam, session['user_id'], id)
        ).fetchone()
        if exists:
            flash(f"Bedrijf '{naam}' bestaat al.", "warning")
            conn.close()
            return redirect(url_for('bedrijven.bedrijven'))
        c.execute('''
            UPDATE bedrijven SET naam=?, plaats=?
            WHERE id=? AND user_id=?
        ''', (naam, plaats or None, id, session['user_id']))
        conn.commit()
        conn.close()
        flash("Bedrijf bijgewerkt.", "success")
        return redirect(url_for('bedrijven.bedrijven'))

    bedrijf = c.execute('SELECT * FROM bedrijven WHERE id=? AND user_id=?', (id, session['user_id'])).fetchone()
    conn.close()
    if bedrijf is None:
        flash("Niet gevonden of geen toegang.", "danger")
        return redirect(url_for('bedrijven.bedrijven'))
    return render_template('bedrijven/bedrijven.html', bedrijf=bedrijf)

@bedrijven_bp.route('/import_bedrijven_excel', methods=['POST'])
@login_required
def import_bedrijven_excel():
    if 'excel_file' not in request.files:
        flash("Geen bestand gekozen.", "danger")
        return redirect(url_for('bedrijven.bedrijven'))
    file = request.files['excel_file']
    try:
        df = pd.read_excel(file)
    except Exception as e:
        flash(f"Excel-bestand niet leesbaar: {e}", "danger")
        return redirect(url_for('bedrijven.bedrijven'))
    conn = db.get_connection()
    c = conn.cursor()
    added = 0
    for _, row in df.iterrows():
        naam = str(row.get('Naam', '')).strip()
        plaats = str(row.get('Plaats', '')).strip()
        if not naam:
            continue
        # Check of bedrijf al bestaat voor deze user!
        exists = c.execute(
            "SELECT 1 FROM bedrijven WHERE naam=? AND user_id=?", (naam, session['user_id'])
        ).fetchone()
        if not exists:
            c.execute(
                'INSERT INTO bedrijven (id, naam, plaats, user_id) VALUES (?, ?, ?, ?)',
                (str(uuid.uuid4()), naam, plaats or None, session['user_id'])
            )
            added += 1
    conn.commit()
    conn.close()
    if added == 0:
        flash("Geen nieuwe bedrijven geïmporteerd (alles bestond al of naam ontbrak).", "warning")
    else:
        flash(f"{added} bedrijf{'ven' if added != 1 else ''} geïmporteerd!", "success")
    return redirect(url_for('bedrijven.bedrijven'))
