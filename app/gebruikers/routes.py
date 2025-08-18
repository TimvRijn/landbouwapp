from flask import Blueprint, render_template, request, redirect, flash, session, url_for
import sqlite3
import uuid

import app.models.database_beheer as db
from app.gebruikers.auth_utils import hash_password, login_user, register_user

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
        username = request.form['username'].strip()
        password = request.form['password']
        if login_user(username, password):
            flash("Succesvol ingelogd!", "success")
            return redirect(url_for('dashboard.bedrijfsdashboard'))
        else:
            flash("Verkeerde gebruikersnaam of wachtwoord!", "danger")
    return render_template('gebruikers/login.html')

@gebruikers_bp.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('is_admin', None)
    flash("Uitgelogd!", "info")
    return redirect(url_for('gebruikers.login'))

@gebruikers_bp.route('/register', methods=['GET', 'POST'])
def register():
    # Optioneel: blokkeer registreren als al ingelogd
    if session.get('user_id'):
        return redirect(url_for('dashboard.bedrijfsdashboard'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        email = request.form.get('email', '').strip()
        naam = request.form.get('naam', '').strip()

        if register_user(username, password, email, naam):
            flash("Account aangemaakt! Je kunt nu inloggen.", "success")
            return redirect(url_for('gebruikers.login'))
        else:
            flash("Gebruikersnaam bestaat al!", "danger")
    return render_template('gebruikers/register.html')

# Overzicht + beheer (alleen admin)
@gebruikers_bp.route('/', methods=['GET'])
# @login_required  # als je beheer alleen ingelogd wilt
def gebruikers():
    if not is_admin():
        flash("Geen toegang!", "danger")
        return redirect(url_for('dashboard.bedrijfsdashboard'))

    conn = db.get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    rows = c.execute("SELECT id, username, email, naam, is_admin FROM users").fetchall()
    conn.close()

    current_user_id = session.get('user_id')
    return render_template('gebruikers/gebruikers.html', gebruikers=rows, current_user_id=current_user_id)

@gebruikers_bp.route('/add', methods=['POST'])
def gebruikers_add():
    if not is_admin():
        flash("Geen toegang!", "danger")
        return redirect(url_for('dashboard.bedrijfsdashboard'))

    username = request.form['username'].strip()
    password = request.form['password']
    email = request.form.get('email', '').strip()
    naam = request.form.get('naam', '').strip()
    is_admin_val = 1 if request.form.get('is_admin') == '1' else 0

    conn = db.get_connection()
    c = conn.cursor()
    try:
        exists = c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if exists:
            flash("Gebruikersnaam bestaat al!", "danger")
        else:
            c.execute(
                'INSERT INTO users (id, username, password_hash, email, naam, is_admin) VALUES (?, ?, ?, ?, ?, ?)',
                (str(uuid.uuid4()), username, hash_password(password), email, naam, is_admin_val)
            )
            conn.commit()
            flash("Gebruiker toegevoegd!", "success")
    except Exception as e:
        flash(f"Fout bij toevoegen gebruiker: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for('gebruikers.gebruikers'))

@gebruikers_bp.route('/delete/<user_id>', methods=['POST'])
def gebruikers_delete(user_id):
    if not is_admin():
        flash("Geen toegang!", "danger")
        return redirect(url_for('dashboard.bedrijfsdashboard'))

    if user_id == str(session.get('user_id')):
        flash("Je kunt jezelf niet verwijderen.", "danger")
        return redirect(url_for('gebruikers.gebruikers'))

    conn = db.get_connection()
    c = conn.cursor()
    c.execute('DELETE FROM users WHERE id=?', (user_id,))
    conn.commit()
    conn.close()
    flash("Gebruiker verwijderd.", "info")
    return redirect(url_for('gebruikers.gebruikers'))

@gebruikers_bp.route('/make_admin/<user_id>', methods=['POST'])
def gebruikers_make_admin(user_id):
    if not is_admin():
        flash("Geen toegang!", "danger")
        return redirect(url_for('dashboard.bedrijfsdashboard'))
    conn = db.get_connection()
    c = conn.cursor()
    c.execute('UPDATE users SET is_admin=1 WHERE id=?', (user_id,))
    conn.commit()
    conn.close()
    flash("Gebruiker is nu admin!", "success")
    return redirect(url_for('gebruikers.gebruikers'))

@gebruikers_bp.route('/remove_admin/<user_id>', methods=['POST'])
def gebruikers_remove_admin(user_id):
    if not is_admin():
        flash("Geen toegang!", "danger")
        return redirect(url_for('dashboard.bedrijfsdashboard'))

    if user_id == str(session.get('user_id')):
        flash("Je kunt je eigen adminrechten niet verwijderen.", "danger")
        return redirect(url_for('gebruikers.gebruikers'))

    conn = db.get_connection()
    c = conn.cursor()
    c.execute('UPDATE users SET is_admin=0 WHERE id=?', (user_id,))
    conn.commit()
    conn.close()
    flash("Adminrechten verwijderd.", "info")
    return redirect(url_for('gebruikers.gebruikers'))

@gebruikers_bp.route('/edit/<user_id>', methods=['POST'])
def gebruikers_edit(user_id):
    if not is_admin():
        flash("Geen toegang!", "danger")
        return redirect(url_for('dashboard.bedrijfsdashboard'))

    username = request.form.get('username', '').strip()
    naam = request.form.get('naam', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')

    conn = db.get_connection()
    c = conn.cursor()

    existing = c.execute(
        "SELECT id FROM users WHERE username=? AND id!=?",
        (username, user_id)
    ).fetchone()
    if existing:
        flash("Gebruikersnaam bestaat al!", "danger")
        conn.close()
        return redirect(url_for('gebruikers.gebruikers'))

    if password:
        c.execute('''
            UPDATE users SET username=?, naam=?, email=?, password_hash=?
            WHERE id=?
        ''', (username, naam, email, hash_password(password), user_id))
    else:
        c.execute('''
            UPDATE users SET username=?, naam=?, email=?
            WHERE id=?
        ''', (username, naam, email, user_id))

    conn.commit()
    conn.close()
    flash("Gebruiker bijgewerkt!", "success")
    return redirect(url_for('gebruikers.gebruikers'))
