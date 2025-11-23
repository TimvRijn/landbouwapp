from flask import Blueprint, render_template, request, redirect, url_for, send_file, session, flash
import uuid
import app.models.database_beheer as db
import os
import pandas as pd
from io import BytesIO

universele_data_bp = Blueprint(
    'universele_data',
    __name__,
    template_folder='templates',
    static_folder='statica',
    url_prefix='/universele_data'
)

def is_admin():
    return session.get('is_admin', 0) == 1

@universele_data_bp.before_request
def restrict_universele_data_bp():
    # Sta alleen static files van dit blueprint toe zonder admin
    if (request.endpoint or "") == "universele_data.static":
        return
    if not is_admin():
        flash("Geen toegang!", "danger")
        return redirect(url_for("dashboard.bedrijfsdashboard"))


@universele_data_bp.route('/universele_data', methods=['GET'])
def universele_data():
    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute('SELECT * FROM stikstof_gewassen_normen')
            gewassen = c.fetchall()

            c.execute('SELECT * FROM fosfaat_normen')
            fosfaatnormen = c.fetchall()

            c.execute('SELECT * FROM derogatie_normen')
            derogatienormen = c.fetchall()

            c.execute('SELECT * FROM stikstof_werkingscoefficient_dierlijk')
            werkingscoefs = c.fetchall()

            c.execute('SELECT * FROM universal_fertilizers')
            universele_meststoffen = c.fetchall()
    finally:
        conn.close()

    return render_template(
        'universele_data/universele_data.html',
        gewassen=gewassen,
        fosfaatnormen=fosfaatnormen,
        derogatienormen=derogatienormen,
        werkingscoefs=werkingscoefs,
        universele_meststoffen=universele_meststoffen,
        is_admin=is_admin()
    )

# ===== GEWASSEN =====

@universele_data_bp.route('/universele_data/add_gewas', methods=['POST'])
def add_gewas():
    if not is_admin():
        flash("Alleen admin mag toevoegen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                '''
                INSERT INTO stikstof_gewassen_normen
                (id, jaar, gewas, n_klei, n_noordwestcentraal_zand, n_zuid_zand, n_loss, n_veen)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ''',
                (
                    str(uuid.uuid4()),
                    int(request.form['jaar']),
                    request.form['gewas'],
                    float(request.form.get('n_klei', 0) or 0),
                    float(request.form.get('n_noordwestcentraal_zand', 0) or 0),
                    float(request.form.get('n_zuid_zand', 0) or 0),
                    float(request.form.get('n_loss', 0) or 0),
                    float(request.form.get('n_veen', 0) or 0)
                )
            )
            conn.commit()
    finally:
        conn.close()

    return redirect(url_for('universele_data.universele_data'))


@universele_data_bp.route('/universele_data/delete_gewas/<id>', methods=['POST'])
def delete_gewas(id):
    if not is_admin():
        flash("Alleen admin mag verwijderen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                'DELETE FROM stikstof_gewassen_normen WHERE id = %s',
                (id,)
            )
            conn.commit()
    finally:
        conn.close()

    return redirect(url_for('universele_data.universele_data'))


@universele_data_bp.route('/universele_data/delete_gewas_year', methods=['POST'])
def delete_gewas_year():
    if not is_admin():
        flash("Alleen admin mag verwijderen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    jaar = request.form.get('jaar')
    if not jaar:
        return redirect(url_for('universele_data.universele_data'))

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                'DELETE FROM stikstof_gewassen_normen WHERE jaar = %s',
                (jaar,)
            )
            conn.commit()
    finally:
        conn.close()

    return redirect(url_for('universele_data.universele_data'))


@universele_data_bp.route('/universele_data/gewassen_import_excel', methods=['POST'])
def gewassen_import_excel():
    if not is_admin():
        flash("Alleen admin mag importeren.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    if 'excel_file' not in request.files:
        flash("Geen bestand gekozen", "danger")
        return redirect(url_for('universele_data.universele_data'))
    file = request.files['excel_file']
    if not file or file.filename == '':
        flash("Geen bestand gekozen", "danger")
        return redirect(url_for('universele_data.universele_data'))

    df = pd.read_excel(BytesIO(file.read()))
    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            for _, row in df.iterrows():
                gewas_id = str(uuid.uuid4())
                c.execute(
                    '''
                    INSERT INTO stikstof_gewassen_normen
                    (id, jaar, gewas, n_klei, n_noordwestcentraal_zand, n_zuid_zand, n_loss, n_veen)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ''',
                    (
                        gewas_id,
                        int(row['Jaar']),
                        row['Gewas'],
                        float(row.get('Klei', 0) or 0),
                        float(row.get('Noordelijk, westelijk en centraal zand', 0) or 0),
                        float(row.get('Zuidelijk zand', 0) or 0),
                        float(row.get('Löss', 0) or 0),
                        float(row.get('Veen', 0) or 0)
                    )
                )
            conn.commit()
    finally:
        conn.close()

    flash("Excel-import voltooid.", "success")
    return redirect(url_for('universele_data.universele_data'))

# ===== FOSFAATNORMEN =====

@universele_data_bp.route('/universele_data/add_fosfaat', methods=['POST'])
def add_fosfaat():
    if not is_admin():
        flash("Alleen admin mag toevoegen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                '''
                INSERT INTO fosfaat_normen
                (id, jaar, type_land, p_cacl2_van, p_cacl2_tot, p_al_van, p_al_tot, norm_omschrijving, norm_kg)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''',
                (
                    str(uuid.uuid4()),
                    int(request.form['jaar']),
                    request.form['type_land'],
                    float(request.form.get('p_cacl2_van', 0) or 0),
                    float(request.form.get('p_cacl2_tot', 0) or 0),
                    float(request.form.get('p_al_van', 0) or 0),
                    float(request.form.get('p_al_tot', 0) or 0),
                    request.form['norm_omschrijving'],
                    float(request.form.get('norm_kg', 0) or 0)
                )
            )
            conn.commit()
    finally:
        conn.close()

    return redirect(url_for('universele_data.universele_data'))


@universele_data_bp.route('/universele_data/delete_fosfaat/<id>', methods=['POST'])
def delete_fosfaat(id):
    if not is_admin():
        flash("Alleen admin mag verwijderen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                'DELETE FROM fosfaat_normen WHERE id = %s',
                (id,)
            )
            conn.commit()
    finally:
        conn.close()

    return redirect(url_for('universele_data.universele_data'))


@universele_data_bp.route('/universele_data/delete_fosfaat_year', methods=['POST'])
def delete_fosfaat_year():
    if not is_admin():
        flash("Alleen admin mag verwijderen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    jaar = request.form.get('jaar')
    if not jaar:
        return redirect(url_for('universele_data.universele_data'))

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                'DELETE FROM fosfaat_normen WHERE jaar = %s',
                (jaar,)
            )
            conn.commit()
    finally:
        conn.close()

    return redirect(url_for('universele_data.universele_data'))


@universele_data_bp.route('/universele_data/fosfaatnorm_import_excel', methods=['POST'])
def fosfaatnorm_import_excel():
    if not is_admin():
        flash("Alleen admin mag importeren.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    if 'excel_file' not in request.files:
        flash("Geen bestand gekozen", "danger")
        return redirect(url_for('universele_data.universele_data'))
    file = request.files['excel_file']
    if not file or file.filename == '':
        flash("Geen bestand gekozen", "danger")
        return redirect(url_for('universele_data.universele_data'))

    df = pd.read_excel(BytesIO(file.read()))
    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            for _, row in df.iterrows():
                c.execute(
                    '''
                    INSERT INTO fosfaat_normen
                    (id, jaar, type_land, p_cacl2_van, p_cacl2_tot, p_al_van, p_al_tot, norm_omschrijving, norm_kg)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''',
                    (
                        str(uuid.uuid4()),
                        int(row['Jaar']),
                        row['Type land'],
                        float(row['P-CaCl2 van']),
                        float(row['P-CaCl2 tot']),
                        float(row['P-AL van']),
                        float(row['P-AL tot']),
                        row['Omschrijving'],
                        float(row['Norm (kg/ha)'])
                    )
                )
            conn.commit()
    finally:
        conn.close()

    flash("Fosfaatnormen geïmporteerd.", "success")
    return redirect(url_for('universele_data.universele_data'))

# ===== DEROGATIENORMEN =====

@universele_data_bp.route('/universele_data/add_derogatie', methods=['POST'])
def add_derogatie():
    if not is_admin():
        flash("Alleen admin mag toevoegen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                '''
                INSERT INTO derogatie_normen
                (id, jaar, derogatie, stikstof_norm_kg_ha, nv_gebied)
                VALUES (%s, %s, %s, %s, %s)
                ''',
                (
                    str(uuid.uuid4()),
                    int(request.form['jaar']),
                    int(request.form['derogatie']),
                    float(request.form['stikstof_norm_kg_ha']),
                    int(request.form['nv_gebied'])
                )
            )
            conn.commit()
    finally:
        conn.close()

    return redirect(url_for('universele_data.universele_data'))


@universele_data_bp.route('/universele_data/delete_derogatie/<id>', methods=['POST'])
def delete_derogatie(id):
    if not is_admin():
        flash("Alleen admin mag verwijderen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                'DELETE FROM derogatie_normen WHERE id = %s',
                (id,)
            )
            conn.commit()
    finally:
        conn.close()

    return redirect(url_for('universele_data.universele_data'))


@universele_data_bp.route('/universele_data/delete_derogatie_year', methods=['POST'])
def delete_derogatie_year():
    if not is_admin():
        flash("Alleen admin mag verwijderen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    jaar = request.form.get('jaar')
    if not jaar:
        return redirect(url_for('universele_data.universele_data'))

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                'DELETE FROM derogatie_normen WHERE jaar = %s',
                (jaar,)
            )
            conn.commit()
    finally:
        conn.close()

    return redirect(url_for('universele_data.universele_data'))

# ===== WERKINGSCOEFFICIENT DIERLIJK =====

@universele_data_bp.route('/universele_data/add_werkingscoefficient', methods=['POST'])
def add_werkingscoefficient():
    if not is_admin():
        flash("Alleen admin mag toevoegen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                '''
                INSERT INTO stikstof_werkingscoefficient_dierlijk
                (id, jaar, meststof, toepassing, werking)
                VALUES (%s, %s, %s, %s, %s)
                ''',
                (
                    str(uuid.uuid4()),
                    int(request.form['jaar']),
                    request.form['meststof'],
                    request.form['toepassing'],
                    float(request.form['werking'])
                )
            )
            conn.commit()
    finally:
        conn.close()

    return redirect(url_for('universele_data.universele_data'))


@universele_data_bp.route('/universele_data/delete_werkingscoefficient/<id>', methods=['POST'])
def delete_werkingscoefficient(id):
    if not is_admin():
        flash("Alleen admin mag verwijderen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                'DELETE FROM stikstof_werkingscoefficient_dierlijk WHERE id = %s',
                (id,)
            )
            conn.commit()
    finally:
        conn.close()

    return redirect(url_for('universele_data.universele_data'))


@universele_data_bp.route('/universele_data/delete_werkingscoefficient_year', methods=['POST'])
def delete_werkingscoefficient_year():
    if not is_admin():
        flash("Alleen admin mag verwijderen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    jaar = request.form.get('jaar')
    if not jaar:
        return redirect(url_for('universele_data.universele_data'))

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                'DELETE FROM stikstof_werkingscoefficient_dierlijk WHERE jaar = %s',
                (jaar,)
            )
            conn.commit()
    finally:
        conn.close()

    return redirect(url_for('universele_data.universele_data'))


@universele_data_bp.route('/universele_data/werkingscoefficient_dierlijk_import_excel', methods=['POST'])
def werkingscoefficient_dierlijk_import_excel():
    if not is_admin():
        flash("Alleen admin mag importeren.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    if 'excel_file' not in request.files:
        flash("Geen bestand gekozen", "danger")
        return redirect(url_for('universele_data.universele_data'))
    file = request.files['excel_file']
    if not file or file.filename == '':
        flash("Geen bestand gekozen", "danger")
        return redirect(url_for('universele_data.universele_data'))

    df = pd.read_excel(BytesIO(file.read()))
    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            for _, row in df.iterrows():
                c.execute(
                    '''
                    INSERT INTO stikstof_werkingscoefficient_dierlijk
                    (id, jaar, meststof, toepassing, werking)
                    VALUES (%s, %s, %s, %s, %s)
                    ''',
                    (
                        str(uuid.uuid4()),
                        int(row['jaar']),
                        row['meststof'],
                        row['toepassing'],
                        float(row['werking'])
                    )
                )
            conn.commit()
    finally:
        conn.close()

    flash("Werkingscoëfficiënten geïmporteerd.", "success")
    return redirect(url_for('universele_data.universele_data'))

# ===== UNIVERSELE MESTSTOFFEN =====

@universele_data_bp.route('/universele_data/add_universal_fertilizer', methods=['POST'])
def add_universal_fertilizer():
    if not is_admin():
        flash("Alleen admin mag toevoegen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                '''
                INSERT INTO universal_fertilizers
                (id, meststof, toepassing, n, p2o5, k2o)
                VALUES (%s, %s, %s, %s, %s, %s)
                ''',
                (
                    str(uuid.uuid4()),
                    request.form['meststof'],
                    request.form['toepassing'],
                    float(request.form.get('n', 0) or 0),
                    float(request.form.get('p2o5', 0) or 0),
                    float(request.form.get('k2o', 0) or 0)
                )
            )
            conn.commit()
    finally:
        conn.close()

    return redirect(url_for('universele_data.universele_data'))


@universele_data_bp.route('/universele_data/delete_universal_fertilizer/<id>', methods=['POST'])
def delete_universal_fertilizer(id):
    if not is_admin():
        flash("Alleen admin mag verwijderen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                'DELETE FROM universal_fertilizers WHERE id = %s',
                (id,)
            )
            conn.commit()
    finally:
        conn.close()

    return redirect(url_for('universele_data.universele_data'))


@universele_data_bp.route('/universele_data/universal_fertilizers_import_excel', methods=['POST'])
def universal_fertilizers_import_excel():
    if not is_admin():
        flash("Alleen admin mag importeren.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    if 'excel_file' not in request.files:
        flash("Geen bestand gekozen", "danger")
        return redirect(url_for('universele_data.universele_data'))
    file = request.files['excel_file']
    if not file or file.filename == '':
        flash("Geen bestand gekozen", "danger")
        return redirect(url_for('universele_data.universele_data'))

    df = pd.read_excel(BytesIO(file.read()))
    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            for _, row in df.iterrows():
                c.execute(
                    '''
                    INSERT INTO universal_fertilizers
                    (id, meststof, toepassing, n, p2o5, k2o)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ''',
                    (
                        str(uuid.uuid4()),
                        str(row['meststof']),
                        str(row['toepassing']),
                        float(row.get('n', 0) or 0),
                        float(row.get('p2o5', 0) or 0),
                        float(row.get('k2o', 0) or 0)
                    )
                )
            conn.commit()
    finally:
        conn.close()

    flash("Meststoffen geïmporteerd.", "success")
    return redirect(url_for('universele_data.universele_data'))
