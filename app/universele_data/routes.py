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

def read_uploaded_spreadsheet(upload_file):
    """
    Leest een geüpload Excel/ODS-bestand in als DataFrame.
    Ondersteunt .xlsx, .xls en .ods.
    Gooit een ValueError bij een niet-ondersteunde extensie.
    Gooit de originele Exception bij leesfouten.
    """
    filename = (upload_file.filename or "").lower()
    content = upload_file.read()

    if filename.endswith('.ods'):
        # Vereist: pip install odfpy
        return pd.read_excel(BytesIO(content), engine="odf")
    elif filename.endswith('.xlsx') or filename.endswith('.xls'):
        return pd.read_excel(BytesIO(content))
    else:
        raise ValueError("Bestandstype niet ondersteund. Gebruik .xlsx, .xls of .ods.")
    
def to_int_safe(value, default=None):
    try:
        s = str(value).strip()
        if s == "" or s.lower() == "nan":
            return default
        # eerst naar float -> dan int, om 2025.0 ook goed te pakken
        return int(float(s))
    except Exception:
        return default

def to_float_safe(value, default=None):
    try:
        s = str(value).strip().replace(",", ".")
        if s == "" or s.lower() == "nan":
            return default
        return float(s)
    except Exception:
        return default


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

            # 👇 hier expliciet
            c.execute('''
                SELECT
                    id,
                    meststof,
                    toepassing,
                    leverancier,
                    n,
                    p2o5,
                    k2o,
                    b,
                    cao,
                    cu,
                    co,
                    cl,
                    fe,
                    mgo,
                    mn,
                    mo,
                    zn,
                    na2o,
                    se,
                    sio2,
                    so3
                FROM universal_fertilizers
            ''')

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
                    to_float_safe(request.form.get('n_klei', 0) or 0, 0),
                    to_float_safe(request.form.get('n_noordwestcentraal_zand', 0) or 0, 0),
                    to_float_safe(request.form.get('n_zuid_zand', 0) or 0, 0),
                    to_float_safe(request.form.get('n_loss', 0) or 0, 0),
                    to_float_safe(request.form.get('n_veen', 0) or 0, 0)
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

    flash("Start import gewassen (route geraakt).", "info")
    print("[DEBUG] gewassen_import_excel aangeroepen")

    if 'excel_file' not in request.files:
        flash("Geen bestand gekozen (key 'excel_file' niet in request.files).", "danger")
        print("[DEBUG] request.files keys:", list(request.files.keys()))
        return redirect(url_for('universele_data.universele_data'))

    file = request.files['excel_file']
    if not file or file.filename == '':
        flash("Geen bestand gekozen (leeg bestand).", "danger")
        return redirect(url_for('universele_data.universele_data'))

    try:
        df = read_uploaded_spreadsheet(file)
    except ValueError as ve:
        flash(f"Bestandstype fout: {ve}", "danger")
        print("[DEBUG] ValueError bij inlezen:", ve)
        return redirect(url_for('universele_data.universele_data'))
    except Exception as e:
        flash(f"Fout bij inlezen bestand: {e}", "danger")
        print("[DEBUG] Exception bij inlezen:", e)
        return redirect(url_for('universele_data.universele_data'))

    flash(f"Excel gelezen: {len(df)} rijen, kolommen: {', '.join(df.columns)}", "info")
    print("[DEBUG] df.shape:", df.shape)
    print("[DEBUG] df.columns:", df.columns.tolist())
    print("[DEBUG] eerste regels:")
    print(df.head())

    required_cols = [
        'Jaar',
        'Gewas',
        'Klei',
        'Noordelijk, westelijk en centraal zand',
        'Zuidelijk zand',
        'Löss',
        'Veen'
    ]
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        msg = f"Kolommen ontbreken in Excel: {', '.join(missing)}"
        flash(msg, "danger")
        print("[DEBUG]", msg)
        return redirect(url_for('universele_data.universele_data'))

    df = df.dropna(how="all")

    numeric_cols = ['Jaar', 'Klei', 'Noordelijk, westelijk en centraal zand',
                    'Zuidelijk zand', 'Löss', 'Veen']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    conn = db.get_connection()
    success_count = 0
    error_rows = []

    try:
        with conn.cursor() as c:
            for row_idx, (_, row) in enumerate(df.iterrows(), start=2):
                try:
                    jaar = to_int_safe(row['Jaar'])
                    gewas = (str(row['Gewas']) or "").strip()

                    if jaar is None or gewas == "":
                        msg = "Lege of ongeldige Jaar/Gewas"
                        error_rows.append((row_idx, msg))
                        print(f"[DEBUG] rij {row_idx}: {msg}")
                        continue

                    n_klei = to_float_safe(row['Klei'])
                    n_nwcz = to_float_safe(row['Noordelijk, westelijk en centraal zand'])
                    n_zz = to_float_safe(row['Zuidelijk zand'])
                    n_loss = to_float_safe(row['Löss'])
                    n_veen = to_float_safe(row['Veen'])

                    c.execute(
                        '''
                        INSERT INTO stikstof_gewassen_normen
                        (id, jaar, gewas, n_klei, n_noordwestcentraal_zand, n_zuid_zand, n_loss, n_veen)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ''',
                        (
                            str(uuid.uuid4()),
                            jaar,
                            gewas,
                            n_klei,
                            n_nwcz,
                            n_zz,
                            n_loss,
                            n_veen
                        )
                    )
                    success_count += 1
                except Exception as row_exc:
                    error_rows.append((row_idx, str(row_exc)))
                    print(f"[DEBUG] fout bij rij {row_idx}:", row_exc)

        conn.commit()
    finally:
        conn.close()

    if success_count > 0:
        flash(f"{success_count} gewas-rij(en) succesvol geïmporteerd.", "success")
        print(f"[DEBUG] {success_count} rijen succesvol geïmporteerd.")
    if error_rows:
        detail = "; ".join([f"rij {r}: {msg}" for r, msg in error_rows[:5]])
        if len(error_rows) > 5:
            detail += f" (en nog {len(error_rows) - 5} rijen met fouten)"
        flash(f"Er zijn {len(error_rows)} rijen overgeslagen vanwege fouten: {detail}", "danger")
        print("[DEBUG] fouten bij rijen:", error_rows)

    if success_count == 0 and not error_rows:
        flash("Geen rijen gevonden om te importeren.", "warning")
        print("[DEBUG] Geen rijen gevonden om te importeren.")

    return redirect(url_for('universele_data.universele_data'))

@universele_data_bp.route('/universele_data/update_gewas', methods=['POST'])
def update_gewas():
    if not is_admin():
        flash("Alleen admin mag bewerken.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    row_id = request.form.get('id')
    if not row_id:
        flash("Geen ID meegegeven voor gewas.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    jaar = request.form.get('jaar')
    gewas = request.form.get('gewas')

    try:
        n_klei      = to_float_safe(request.form.get('klei') or 0, 0)
        n_nwc_zand  = to_float_safe(request.form.get('nwc_zand') or 0, 0)
        n_zuid_zand = to_float_safe(request.form.get('zuid_zand') or 0, 0)
        n_loss      = to_float_safe(request.form.get('loss') or 0, 0)
        n_veen      = to_float_safe(request.form.get('veen') or 0, 0)
    except ValueError:
        flash("Ongeldige numerieke waarde bij bewerken gewas.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                '''
                UPDATE stikstof_gewassen_normen
                SET jaar = %s,
                    gewas = %s,
                    n_klei = %s,
                    n_noordwestcentraal_zand = %s,
                    n_zuid_zand = %s,
                    n_loss = %s,
                    n_veen = %s
                WHERE id = %s
                ''',
                (
                    int(jaar),
                    gewas,
                    n_klei,
                    n_nwc_zand,
                    n_zuid_zand,
                    n_loss,
                    n_veen,
                    row_id
                )
            )
            conn.commit()
    finally:
        conn.close()

    flash("Gewas bijgewerkt.", "success")
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
                    to_float_safe(request.form.get('p_cacl2_van', 0) or 0, 0),
                    to_float_safe(request.form.get('p_cacl2_tot', 0) or 0, 0),
                    to_float_safe(request.form.get('p_al_van', 0) or 0, 0),
                    to_float_safe(request.form.get('p_al_tot', 0) or 0, 0),
                    request.form['norm_omschrijving'],
                    to_float_safe(request.form.get('norm_kg', 0) or 0, 0)
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
        flash("Geen bestand gekozen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    file = request.files['excel_file']
    if not file or file.filename == '':
        flash("Geen bestand gekozen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    try:
        df = read_uploaded_spreadsheet(file)
    except ValueError as ve:
        flash(str(ve), "danger")
        return redirect(url_for('universele_data.universele_data'))
    except Exception as e:
        flash(f"Fout bij inlezen bestand: {e}", "danger")
        return redirect(url_for('universele_data.universele_data'))

    required_cols = [
        'Jaar',
        'Type land',
        'P-CaCl2 van',
        'P-CaCl2 tot',
        'P-AL van',
        'P-AL tot',
        'Omschrijving',
        'Norm (kg/ha)'
    ]
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        flash(f"Kolommen ontbreken in Excel: {', '.join(missing)}", "danger")
        return redirect(url_for('universele_data.universele_data'))

    df = df.dropna(how="all")

    conn = db.get_connection()
    last_excel_row = None
    success_count = 0
    try:
        with conn.cursor() as c:
            for row_idx, (_, row) in enumerate(df.iterrows(), start=2):
                last_excel_row = row_idx

                jaar = to_int_safe(row['Jaar'])
                if jaar is None:
                    continue

                c.execute(
                    '''
                    INSERT INTO fosfaat_normen
                    (id, jaar, type_land, p_cacl2_van, p_cacl2_tot, p_al_van, p_al_tot, norm_omschrijving, norm_kg)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''',
                    (
                        str(uuid.uuid4()),
                        jaar,
                        row['Type land'],
                        to_float_safe(row['P-CaCl2 van'], 0),
                        to_float_safe(row['P-CaCl2 tot'], 0),
                        to_float_safe(row['P-AL van'], 0),
                        to_float_safe(row['P-AL tot'], 0),
                        row['Omschrijving'],
                        to_float_safe(row['Norm (kg/ha)'], 0)
                    )
                )
                success_count += 1

            conn.commit()
    except Exception as e:
        conn.rollback()
        if last_excel_row is not None:
            flash(f"Import fosfaatnormen mislukt bij Excel-rij {last_excel_row}: {e}", "danger")
        else:
            flash(f"Import fosfaatnormen mislukt: {e}", "danger")
        return redirect(url_for('universele_data.universele_data'))
    finally:
        conn.close()

    flash(f"Fosfaatnormen geïmporteerd ({success_count} rijen).", "success")
    return redirect(url_for('universele_data.universele_data'))

@universele_data_bp.route('/universele_data/update_fosfaat', methods=['POST'])
def update_fosfaat():
    if not is_admin():
        flash("Alleen admin mag bewerken.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    row_id = request.form.get('id')
    if not row_id:
        flash("Geen ID meegegeven voor fosfaatnorm.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    jaar = request.form.get('jaar')
    type_land = request.form.get('type_land')
    omschrijving = request.form.get('omschrijving')

    try:
        p_cacl2_van = to_float_safe(request.form.get('pca_from') or 0, 0)
        p_cacl2_tot = to_float_safe(request.form.get('pca_to') or 0, 0)
        p_al_van    = to_float_safe(request.form.get('pal_from') or 0, 0)
        p_al_tot    = to_float_safe(request.form.get('pal_to') or 0, 0)
        norm_kg     = to_float_safe(request.form.get('norm') or 0, 0)
    except ValueError:
        flash("Ongeldige numerieke waarde bij bewerken fosfaatnorm.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                '''
                UPDATE fosfaat_normen
                SET jaar = %s,
                    type_land = %s,
                    p_cacl2_van = %s,
                    p_cacl2_tot = %s,
                    p_al_van = %s,
                    p_al_tot = %s,
                    norm_omschrijving = %s,
                    norm_kg = %s
                WHERE id = %s
                ''',
                (
                    int(jaar),
                    type_land,
                    p_cacl2_van,
                    p_cacl2_tot,
                    p_al_van,
                    p_al_tot,
                    omschrijving,
                    norm_kg,
                    row_id
                )
            )
            conn.commit()
    finally:
        conn.close()

    flash("Fosfaatnorm bijgewerkt.", "success")
    return redirect(url_for('universele_data.universele_data'))

# ===== DEROGATIENORMEN =====

@universele_data_bp.route('/universele_data/add_derogatie', methods=['POST'])
def add_derogatie():
    if not is_admin():
        flash("Alleen admin mag toevoegen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    try:
        jaar      = int(request.form['jaar'])
        derogatie = int(request.form['derogatie'])
        stikstof_norm_kg_ha = to_float_safe(request.form.get('n_norm') or 0, 0)
        nv_gebied = int(request.form['nv_gebied'])
    except KeyError as e:
        flash(f"Formulierveld ontbreekt: {e}", "danger")
        return redirect(url_for('universele_data.universele_data'))
    except ValueError:
        flash("Ongeldige numerieke waarde bij toevoegen derogatie-norm.", "danger")
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
                    jaar,
                    derogatie,
                    stikstof_norm_kg_ha,
                    nv_gebied
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

@universele_data_bp.route('/universele_data/update_derogatie', methods=['POST'])
def update_derogatie():
    if not is_admin():
        flash("Alleen admin mag bewerken.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    row_id = request.form.get('id')
    if not row_id:
        flash("Geen ID meegegeven voor derogatie-norm.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    jaar = request.form.get('jaar')
    derogatie = request.form.get('derogatie')
    nv_gebied = request.form.get('nv_gebied')

    try:
        stikstof_norm_kg_ha = to_float_safe(request.form.get('n_norm') or 0, 0)
    except ValueError:
        flash("Ongeldige numerieke waarde bij bewerken derogatie-norm.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                '''
                UPDATE derogatie_normen
                SET jaar = %s,
                    derogatie = %s,
                    stikstof_norm_kg_ha = %s,
                    nv_gebied = %s
                WHERE id = %s
                ''',
                (
                    int(jaar),
                    int(derogatie),
                    stikstof_norm_kg_ha,
                    int(nv_gebied),
                    row_id
                )
            )
            conn.commit()
    finally:
        conn.close()

    flash("Derogatie-norm bijgewerkt.", "success")
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
                    to_float_safe(request.form.get('werking') or 0, 0)
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
        flash("Geen bestand gekozen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    file = request.files['excel_file']
    if not file or file.filename == '':
        flash("Geen bestand gekozen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    try:
        df = read_uploaded_spreadsheet(file)
    except ValueError as ve:
        flash(str(ve), "danger")
        return redirect(url_for('universele_data.universele_data'))
    except Exception as e:
        flash(f"Fout bij inlezen bestand: {e}", "danger")
        return redirect(url_for('universele_data.universele_data'))

    required_cols = ['jaar', 'meststof', 'toepassing', 'werking']
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        flash(f"Kolommen ontbreken in Excel: {', '.join(missing)}", "danger")
        return redirect(url_for('universele_data.universele_data'))

    df = df.dropna(how="all")

    conn = db.get_connection()
    last_excel_row = None
    success_count = 0
    try:
        with conn.cursor() as c:
            for row_idx, (_, row) in enumerate(df.iterrows(), start=2):
                last_excel_row = row_idx

                jaar = to_int_safe(row['jaar'])
                if jaar is None:
                    continue

                c.execute(
                    '''
                    INSERT INTO stikstof_werkingscoefficient_dierlijk
                    (id, jaar, meststof, toepassing, werking)
                    VALUES (%s, %s, %s, %s, %s)
                    ''',
                    (
                        str(uuid.uuid4()),
                        jaar,
                        row['meststof'],
                        row['toepassing'],
                        to_float_safe(row['werking'], 0)
                    )
                )
                success_count += 1

            conn.commit()
    except Exception as e:
        conn.rollback()
        if last_excel_row is not None:
            flash(f"Import werkingscoëfficiënten mislukt bij Excel-rij {last_excel_row}: {e}", "danger")
        else:
            flash(f"Import werkingscoëfficiënten mislukt: {e}", "danger")
        return redirect(url_for('universele_data.universele_data'))
    finally:
        conn.close()

    flash(f"Werkingscoëfficiënten geïmporteerd ({success_count} rijen).", "success")
    return redirect(url_for('universele_data.universele_data'))

@universele_data_bp.route('/universele_data/update_werkingscoefficient', methods=['POST'])
def update_werkingscoefficient():
    if not is_admin():
        flash("Alleen admin mag bewerken.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    row_id = request.form.get('id')
    if not row_id:
        flash("Geen ID meegegeven voor werkingscoëfficiënt.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    jaar = request.form.get('jaar')
    meststof = request.form.get('meststof')
    toepassing = request.form.get('toepassing')

    try:
        werking = to_float_safe(request.form.get('coefficient') or 0, 0)
    except ValueError:
        flash("Ongeldige numerieke waarde bij bewerken werkingscoëfficiënt.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                '''
                UPDATE stikstof_werkingscoefficient_dierlijk
                SET jaar = %s,
                    meststof = %s,
                    toepassing = %s,
                    werking = %s
                WHERE id = %s
                ''',
                (
                    int(jaar),
                    meststof,
                    toepassing,
                    werking,
                    row_id
                )
            )
            conn.commit()
    finally:
        conn.close()

    flash("Werkingscoëfficiënt bijgewerkt.", "success")
    return redirect(url_for('universele_data.universele_data'))

# ===== UNIVERSELE MESTSTOFFEN =====

# ===== UNIVERSELE MESTSTOFFEN ===== 

@universele_data_bp.route('/universele_data/add_universal_fertilizer', methods=['POST'])
def add_universal_fertilizer():
    if not is_admin():
        flash("Alleen admin mag toevoegen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    # Zowel "meststof" als "naam" ondersteunen (template gebruikt 'naam')
    meststof_naam = request.form.get('meststof') or request.form.get('naam')
    toepassing = request.form.get('toepassing')
    leverancier = request.form.get('leverancier')  # kan nog ontbreken in formulier, dan None

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                '''
                INSERT INTO universal_fertilizers
                (id, meststof, toepassing, leverancier,
                 n, p2o5, k2o,
                 b, cao, cu, co, cl, fe, mgo, mn, mo, zn, na2o, se, sio2, so3)
                VALUES
                (%s, %s, %s, %s,
                 %s, %s, %s,
                 %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''',
                (
                    str(uuid.uuid4()),
                    meststof_naam,
                    toepassing,
                    leverancier,
                    to_float_safe(request.form.get('n', 0) or 0, 0),
                    to_float_safe(request.form.get('p2o5', 0) or 0, 0),
                    to_float_safe(request.form.get('k2o', 0) or 0, 0),

                    to_float_safe(request.form.get('b', 0) or 0, 0),
                    to_float_safe(request.form.get('cao', 0) or 0, 0),
                    to_float_safe(request.form.get('cu', 0) or 0, 0),
                    to_float_safe(request.form.get('co', 0) or 0, 0),
                    to_float_safe(request.form.get('cl', 0) or 0, 0),
                    to_float_safe(request.form.get('fe', 0) or 0, 0),
                    to_float_safe(request.form.get('mgo', 0) or 0, 0),
                    to_float_safe(request.form.get('mn', 0) or 0, 0),
                    to_float_safe(request.form.get('mo', 0) or 0, 0),
                    to_float_safe(request.form.get('zn', 0) or 0, 0),
                    to_float_safe(request.form.get('na2o', 0) or 0, 0),
                    to_float_safe(request.form.get('se', 0) or 0, 0),
                    to_float_safe(request.form.get('sio2', 0) or 0, 0),
                    to_float_safe(request.form.get('so3', 0) or 0, 0),
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
        flash("Geen bestand gekozen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    file = request.files['excel_file']
    if not file or file.filename == '':
        flash("Geen bestand gekozen.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    try:
        df = read_uploaded_spreadsheet(file)
    except ValueError as ve:
        flash(str(ve), "danger")
        return redirect(url_for('universele_data.universele_data'))
    except Exception as e:
        flash(f"Fout bij inlezen bestand: {e}", "danger")
        return redirect(url_for('universele_data.universele_data'))

    # Excel moet AL deze kolommen als header hebben (waarden mogen leeg zijn)
    required_cols = [
        'meststof', 'toepassing', 'leverancier',
        'n', 'p2o5', 'k2o',
        'b', 'cao', 'cu', 'co', 'cl', 'fe', 'mgo', 'mn', 'mo',
        'zn', 'na2o', 'se', 'sio2', 'so3'
    ]
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        flash(f"Kolommen ontbreken in Excel: {', '.join(missing)}", "danger")
        return redirect(url_for('universele_data.universele_data'))

    df = df.dropna(how="all")

    conn = db.get_connection()
    last_excel_row = None
    success_count = 0
    try:
        with conn.cursor() as c:
            for row_idx, (_, row) in enumerate(df.iterrows(), start=2):
                last_excel_row = row_idx

                c.execute(
                    '''
                    INSERT INTO universal_fertilizers
                    (id, meststof, toepassing, leverancier,
                     n, p2o5, k2o,
                     b, cao, cu, co, cl, fe, mgo, mn, mo, zn, na2o, se, sio2, so3)
                    VALUES
                    (%s, %s, %s, %s,
                     %s, %s, %s,
                     %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''',
                    (
                        str(uuid.uuid4()),
                        str(row['meststof']),
                        str(row['toepassing']),
                        str(row['leverancier']) if not pd.isna(row['leverancier']) else None,

                        to_float_safe(row.get('n', 0) or 0, 0),
                        to_float_safe(row.get('p2o5', 0) or 0, 0),
                        to_float_safe(row.get('k2o', 0) or 0, 0),

                        to_float_safe(row.get('b', 0) or 0, 0),
                        to_float_safe(row.get('cao', 0) or 0, 0),
                        to_float_safe(row.get('cu', 0) or 0, 0),
                        to_float_safe(row.get('co', 0) or 0, 0),
                        to_float_safe(row.get('cl', 0) or 0, 0),
                        to_float_safe(row.get('fe', 0) or 0, 0),
                        to_float_safe(row.get('mgo', 0) or 0, 0),
                        to_float_safe(row.get('mn', 0) or 0, 0),
                        to_float_safe(row.get('mo', 0) or 0, 0),
                        to_float_safe(row.get('zn', 0) or 0, 0),
                        to_float_safe(row.get('na2o', 0) or 0, 0),
                        to_float_safe(row.get('se', 0) or 0, 0),
                        to_float_safe(row.get('sio2', 0) or 0, 0),
                        to_float_safe(row.get('so3', 0) or 0, 0),
                    )
                )
                success_count += 1

            conn.commit()
    except Exception as e:
        conn.rollback()
        if last_excel_row is not None:
            flash(f"Import meststoffen mislukt bij Excel-rij {last_excel_row}: {e}", "danger")
        else:
            flash(f"Import meststoffen mislukt: {e}", "danger")
        return redirect(url_for('universele_data.universele_data'))
    finally:
        conn.close()

    flash(f"Meststoffen geïmporteerd ({success_count} rijen).", "success")
    return redirect(url_for('universele_data.universele_data'))


@universele_data_bp.route('/universele_data/update_universal_fertilizer', methods=['POST'])
def update_universal_fertilizer():
    if not is_admin():
        flash("Alleen admin mag bewerken.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    row_id = request.form.get('id')
    if not row_id:
        flash("Geen ID meegegeven voor meststof.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    naam        = request.form.get('naam') or request.form.get('meststof')
    toepassing  = request.form.get('toepassing')
    leverancier = request.form.get('leverancier')

    try:
        n    = to_float_safe(request.form.get('n') or 0, 0)
        p2o5 = to_float_safe(request.form.get('p2o5') or 0, 0)
        k2o  = to_float_safe(request.form.get('k2o') or 0, 0)

        b    = to_float_safe(request.form.get('b') or 0, 0)
        cao  = to_float_safe(request.form.get('cao') or 0, 0)
        cu   = to_float_safe(request.form.get('cu') or 0, 0)
        co   = to_float_safe(request.form.get('co') or 0, 0)
        cl   = to_float_safe(request.form.get('cl') or 0, 0)
        fe   = to_float_safe(request.form.get('fe') or 0, 0)
        mgo  = to_float_safe(request.form.get('mgo') or 0, 0)
        mn   = to_float_safe(request.form.get('mn') or 0, 0)
        mo   = to_float_safe(request.form.get('mo') or 0, 0)
        zn   = to_float_safe(request.form.get('zn') or 0, 0)
        na2o = to_float_safe(request.form.get('na2o') or 0, 0)
        se   = to_float_safe(request.form.get('se') or 0, 0)
        sio2 = to_float_safe(request.form.get('sio2') or 0, 0)
        so3  = to_float_safe(request.form.get('so3') or 0, 0)
    except ValueError:
        flash("Ongeldige numerieke waarde bij bewerken meststof.", "danger")
        return redirect(url_for('universele_data.universele_data'))

    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(
                '''
                UPDATE universal_fertilizers
                SET meststof = %s,
                    toepassing = %s,
                    leverancier = %s,
                    n = %s,
                    p2o5 = %s,
                    k2o = %s,
                    b = %s,
                    cao = %s,
                    cu = %s,
                    co = %s,
                    cl = %s,
                    fe = %s,
                    mgo = %s,
                    mn = %s,
                    mo = %s,
                    zn = %s,
                    na2o = %s,
                    se = %s,
                    sio2 = %s,
                    so3 = %s
                WHERE id = %s
                ''',
                (
                    naam,
                    toepassing,
                    leverancier,
                    n,
                    p2o5,
                    k2o,
                    b,
                    cao,
                    cu,
                    co,
                    cl,
                    fe,
                    mgo,
                    mn,
                    mo,
                    zn,
                    na2o,
                    se,
                    sio2,
                    so3,
                    row_id
                )
            )
            conn.commit()
    finally:
        conn.close()

    flash("Meststof bijgewerkt.", "success")
    return redirect(url_for('universele_data.universele_data'))
