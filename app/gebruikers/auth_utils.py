from functools import wraps
from flask import session, redirect, url_for, flash, request
import app.models.database_beheer as db
import hashlib
import uuid

# Wachtwoord hashen
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Login-required decorator
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash("Log eerst in om verder te gaan.", "warning")
            return redirect(url_for('gebruikers.login'))
        return f(*args, **kwargs)
    return wrapper

# Check of gebruiker admin is
def is_admin():
    return session.get('is_admin') == 1

# Functie om een gebruiker te zoeken
def get_user_by_username(username):
    conn = db.get_connection()
    c = conn.cursor()
    user = c.execute("SELECT id, password_hash, is_admin FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    return user

# Login helper
def login_user(username, password):
    user = get_user_by_username(username)
    if user and user[1] == hash_password(password):
        session['user_id'] = user[0]
        session['is_admin'] = user[2] if user[2] is not None else 0
        return True
    return False

# Register helper
def register_user(username, password, email, naam, is_admin=0):
    conn = db.get_connection()
    c = conn.cursor()
    try:
        c.execute('INSERT INTO users (id, username, password_hash, email, naam, is_admin) VALUES (?, ?, ?, ?, ?, ?)',
                  (str(uuid.uuid4()), username, hash_password(password), email, naam, is_admin))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()

# Optioneel: decorator voor alleen-admin
def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('is_admin'):
            flash("Alleen voor admins!", "danger")
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return wrapper
