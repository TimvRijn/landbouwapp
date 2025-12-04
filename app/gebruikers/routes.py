from flask import Blueprint, render_template, request, redirect, flash, session, url_for, jsonify
import uuid

import app.models.database_beheer as db
from app.gebruikers.auth_utils import (
    hash_password,
    login_user,
    register_user,
    login_required,
    get_user_by_email,           # NEW
    create_reset_token,          # NEW
    verify_reset_token,          # NEW
    consume_reset_token,         # NEW
    update_user_password,        # NEW
)

gebruikers_bp = Blueprint(
    'gebruikers',
    __name__,
    template_folder='templates',   # => app/gebruikers/templates/
    static_folder='static',        # => app/gebruikers/static/ (optioneel)
    url_prefix='/gebruikers'
)


def is_admin():
    return session.get('is_admin', 0) == 1


@gebruikers_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Als je al ingelogd bent, terug naar dashboard
    if session.get('user_id'):
        return redirect(url_for('dashboard.bedrijfsdashboard'))

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        if not username or not password:
            flash("Vul gebruikersnaam en wachtwoord in.", "warning")
            return render_template('gebruikers/login.html')

        if login_user(username, password):
            # Zorg dat eventuele oude view-as context wordt opgeruimd
            session.pop('view_as_user_id', None)
            session.pop('view_as_user_name', None)
            flash("Succesvol ingelogd!", "success")
            return redirect(url_for('dashboard.bedrijfsdashboard'))
        else:
            flash("Verkeerde gebruikersnaam of wachtwoord!", "danger")
    return render_template('gebruikers/login.html')


@gebruikers_bp.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('is_admin', None)
    # Opruimen van view-as context bij uitloggen
    session.pop('view_as_user_id', None)
    session.pop('view_as_user_name', None)
    flash("Uitgelogd!", "info")
    return redirect(url_for('gebruikers.login'))


@gebruikers_bp.route('/register', methods=['GET', 'POST'])
def register():
    # Optioneel: blokkeer registreren als al ingelogd
    if session.get('user_id'):
        return redirect(url_for('dashboard.bedrijfsdashboard'))

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        email = (request.form.get('email') or '').strip()
        naam = (request.form.get('naam') or '').strip()

        if not username or not password:
            flash("Gebruikersnaam en wachtwoord zijn verplicht.", "warning")
            return render_template('gebruikers/register.html')

        if register_user(username, password, email, naam):
            flash("Account aangemaakt! Je kunt nu inloggen.", "success")
            return redirect(url_for('gebruikers.login'))
        else:
            flash("Gebruikersnaam bestaat al!", "danger")
    return render_template('gebruikers/register.html')


# Overzicht + beheer (alleen admin)
@gebruikers_bp.route('/', methods=['GET'])
@login_required
def gebruikers():
    if not is_admin():
        flash("Geen toegang!", "danger")
        return redirect(url_for('dashboard.bedrijfsdashboard'))

    conn, c = db.get_dict_cursor()
    try:
        c.execute("SELECT id, username, email, naam, is_admin FROM users")
        rows = c.fetchall()  # list van dicts
    finally:
        conn.close()

    current_user_id = session.get('user_id')
    return render_template('gebruikers/gebruikers.html', gebruikers=rows, current_user_id=current_user_id)


@gebruikers_bp.route('/add', methods=['POST'])
@login_required
def gebruikers_add():
    if not is_admin():
        flash("Geen toegang!", "danger")
        return redirect(url_for('dashboard.bedrijfsdashboard'))

    username = (request.form.get('username') or '').strip()
    password = request.form.get('password') or ''
    email = (request.form.get('email') or '').strip()
    naam = (request.form.get('naam') or '').strip()
    is_admin_val = 1 if request.form.get('is_admin') == '1' else 0

    if not username or not password:
        flash("Gebruikersnaam en wachtwoord zijn verplicht.", "warning")
        return redirect(url_for('gebruikers.gebruikers'))

    conn, c = db.get_dict_cursor()
    try:
        c.execute("SELECT id FROM users WHERE username=%s", (username,))
        exists = c.fetchone()
        if exists:
            flash("Gebruikersnaam bestaat al!", "danger")
        else:
            c.execute(
                '''
                INSERT INTO users (id, username, password_hash, email, naam, is_admin)
                VALUES (%s, %s, %s, %s, %s, %s)
                ''',
                (str(uuid.uuid4()), username, hash_password(password), email, naam, is_admin_val)
            )
            conn.commit()
            flash("Gebruiker toegevoegd!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Fout bij toevoegen gebruiker: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for('gebruikers.gebruikers'))


@gebruikers_bp.route('/delete/<user_id>', methods=['POST'])
@login_required
def gebruikers_delete(user_id):
    if not is_admin():
        flash("Geen toegang!", "danger")
        return redirect(url_for('dashboard.bedrijfsdashboard'))

    if user_id == str(session.get('user_id')):
        flash("Je kunt jezelf niet verwijderen.", "danger")
        return redirect(url_for('gebruikers.gebruikers'))

    conn, c = db.get_dict_cursor()
    try:
        c.execute('DELETE FROM users WHERE id=%s', (user_id,))
        conn.commit()

        # Als je de huidige view-as gebruiker verwijdert, reset de view-as context
        if session.get('view_as_user_id') == user_id:
            session.pop('view_as_user_id', None)
            session.pop('view_as_user_name', None)
        flash("Gebruiker verwijderd.", "info")
    except Exception as e:
        conn.rollback()
        flash(f"Fout bij verwijderen gebruiker: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for('gebruikers.gebruikers'))


@gebruikers_bp.route('/make_admin/<user_id>', methods=['POST'])
@login_required
def gebruikers_make_admin(user_id):
    if not is_admin():
        flash("Geen toegang!", "danger")
        return redirect(url_for('dashboard.bedrijfsdashboard'))

    conn, c = db.get_dict_cursor()
    try:
        c.execute('UPDATE users SET is_admin=1 WHERE id=%s', (user_id,))
        conn.commit()
        flash("Gebruiker is nu admin!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Fout bij admin maken: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for('gebruikers.gebruikers'))


@gebruikers_bp.route('/remove_admin/<user_id>', methods=['POST'])
@login_required
def gebruikers_remove_admin(user_id):
    if not is_admin():
        flash("Geen toegang!", "danger")
        return redirect(url_for('dashboard.bedrijfsdashboard'))

    if user_id == str(session.get('user_id')):
        flash("Je kunt je eigen adminrechten niet verwijderen.", "danger")
        return redirect(url_for('gebruikers.gebruikers'))

    conn, c = db.get_dict_cursor()
    try:
        c.execute('UPDATE users SET is_admin=0 WHERE id=%s', (user_id,))
        conn.commit()
        flash("Adminrechten verwijderd.", "info")
    except Exception as e:
        conn.rollback()
        flash(f"Fout bij adminrechten verwijderen: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for('gebruikers.gebruikers'))


@gebruikers_bp.route('/edit/<user_id>', methods=['POST'])
@login_required
def gebruikers_edit(user_id):
    if not is_admin():
        flash("Geen toegang!", "danger")
        return redirect(url_for('dashboard.bedrijfsdashboard'))

    username = (request.form.get('username') or '').strip()
    naam = (request.form.get('naam') or '').strip()
    email = (request.form.get('email') or '').strip()
    password = request.form.get('password') or ''

    if not username:
        flash("Gebruikersnaam mag niet leeg zijn.", "warning")
        return redirect(url_for('gebruikers.gebruikers'))

    conn, c = db.get_dict_cursor()
    try:
        c.execute(
            "SELECT id FROM users WHERE username=%s AND id!=%s",
            (username, user_id)
        )
        existing = c.fetchone()
        if existing:
            flash("Gebruikersnaam bestaat al!", "danger")
            return redirect(url_for('gebruikers.gebruikers'))

        if password:
            c.execute(
                '''
                UPDATE users
                SET username=%s, naam=%s, email=%s, password_hash=%s
                WHERE id=%s
                ''',
                (username, naam, email, hash_password(password), user_id)
            )
        else:
            c.execute(
                '''
                UPDATE users
                SET username=%s, naam=%s, email=%s
                WHERE id=%s
                ''',
                (username, naam, email, user_id)
            )

        conn.commit()
        flash("Gebruiker bijgewerkt!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Fout bij bijwerken gebruiker: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for('gebruikers.gebruikers'))


@gebruikers_bp.route('/view_as', methods=['POST'])
@login_required
def view_as():
    if not is_admin():
        flash("Geen toegang!", "danger")
        return redirect(url_for('dashboard.bedrijfsdashboard'))

    target_id = request.form.get('user_id')
    if not target_id:
        flash("Geen gebruiker gekozen.", "warning")
        return redirect(request.referrer or url_for('dashboard.bedrijfsdashboard'))

    conn, c = db.get_dict_cursor()
    try:
        c.execute(
            "SELECT id, COALESCE(naam, username) AS display FROM users WHERE id=%s",
            (target_id,)
        )
        row = c.fetchone()
    finally:
        conn.close()

    if not row:
        flash("Gebruiker niet gevonden.", "danger")
        return redirect(request.referrer or url_for('dashboard.bedrijfsdashboard'))

    session['view_as_user_id'] = row['id']
    session['view_as_user_name'] = row['display']
    flash(f"Je bekijkt nu als: {row['display']}", "info")
    return redirect(request.referrer or url_for('dashboard.bedrijfsdashboard'))


@gebruikers_bp.route('/view_as_clear', methods=['POST'])
@login_required
def view_as_clear():
    if not is_admin():
        flash("Geen toegang!", "danger")
        return redirect(url_for('dashboard.bedrijfsdashboard'))

    session.pop('view_as_user_id', None)
    session.pop('view_as_user_name', None)
    flash("Bekijk-als uitgeschakeld.", "info")
    return redirect(request.referrer or url_for('dashboard.bedrijfsdashboard'))


@gebruikers_bp.route('/list_json', methods=['GET'])
@login_required
def list_json():
    """Async lijst voor de selector in de navigatie (alleen admin)."""
    if not is_admin():
        return jsonify([]), 403

    conn, c = db.get_dict_cursor()
    try:
        c.execute(
            """
            SELECT
                id,
                COALESCE(naam, username) AS label
            FROM users
            ORDER BY LOWER(COALESCE(naam, username))
            """
        )

        rows = c.fetchall()
        data = [{"id": r["id"], "label": r["label"]} for r in rows]
    finally:
        conn.close()
    return jsonify(data)


# ---------------------------
# Wachtwoord vergeten
# ---------------------------
@gebruikers_bp.route('/forgot', methods=['GET', 'POST'])
def forgot():
    if request.method == 'POST':
        # We accepteren zowel e-mail als username in één veld:
        identifier = (request.form.get('email') or request.form.get('username') or '').strip()

        user_row = None
        if identifier:
            # Probeer eerst als e-mail, anders als username
            user_row = get_user_by_email(identifier) or None
            if not user_row:
                # fallback: username lookup
                conn, c = db.get_dict_cursor()
                try:
                    c.execute(
                        "SELECT id, username, email, naam FROM users WHERE username = %s",
                        (identifier,)
                    )
                    user_row = c.fetchone()
                finally:
                    conn.close()

        if user_row:
            token = create_reset_token(user_row['id'], ttl_minutes=60)
            reset_url = url_for('gebruikers.reset', token=token, _external=True)

            # TODO: verstuur mail met reset_url naar user_row['email'].
            #       In dev loggen we de link zodat je kunt testen:
            print(f"[DEV] Password reset link for {user_row['username']} -> {reset_url}")

        # Altijd dezelfde melding (geen user-enumeration)
        flash(('success', 'Als dit e-mailadres/gebruikersnaam bij ons bekend is, hebben we een herstel-link verstuurd.'))
        return redirect(url_for('gebruikers.forgot'))

    return render_template('gebruikers/forgot.html')


# ---------------------------
# Wachtwoord resetten met token
# ---------------------------
@gebruikers_bp.route('/reset/<token>', methods=['GET', 'POST'])
def reset(token):
    user_id = verify_reset_token(token)
    if not user_id:
        flash(('danger', 'De herstel-link is ongeldig of verlopen. Vraag een nieuwe aan.'))
        return redirect(url_for('gebruikers.forgot'))

    if request.method == 'POST':
        pw1 = request.form.get('password') or ''
        pw2 = request.form.get('password_confirm') or ''
        if not pw1 or len(pw1) < 8:
            flash(('warning', 'Kies een wachtwoord van minimaal 8 tekens.'))
            return render_template('gebruikers/reset.html', token=token)
        if pw1 != pw2:
            flash(('warning', 'Wachtwoorden komen niet overeen.'))
            return render_template('gebruikers/reset.html', token=token)

        update_user_password(user_id, pw1)
        consume_reset_token(token)
        flash(('success', 'Je wachtwoord is bijgewerkt. Je kunt nu inloggen.'))
        return redirect(url_for('gebruikers.login'))

    return render_template('gebruikers/reset.html', token=token)
