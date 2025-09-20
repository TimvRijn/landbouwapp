# app/gebruikers/auth_utils.py
from functools import wraps
from flask import session, redirect, url_for, flash
import sqlite3
import hashlib
import uuid

import app.models.database_beheer as db


# ---------------------------
# Helpers voor (impersonated) user
# ---------------------------
def effective_user_id():
    """De gebruiker waarvoor data getoond/berekend moet worden."""
    return session.get('view_as_user_id') or session.get('user_id')


def is_impersonating():
    return 'view_as_user_id' in session


def is_admin():
    # Zorg dat dit altijd een int/bool is
    return int(session.get('is_admin', 0)) == 1


def current_user_display_name():
    """
    Toonbare naam, met volgorde:
    1) view_as_user_name (admin bekijkt als)
    2) naam (volle naam uit DB)
    3) username
    """
    return (
        session.get('view_as_user_name')
        or session.get('naam')
        or session.get('username')
        or "Gebruiker"
    )


# ---------------------------
# Wachtwoord hashing (huidig: SHA256)
# ---------------------------
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# ---------------------------
# Decorators
# ---------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash("Log eerst in om verder te gaan.", "warning")
            return redirect(url_for('gebruikers.login'))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_admin():
            flash("Alleen voor admins!", "danger")
            # Val terug naar je dashboard (pas aan indien nodig)
            return redirect(url_for('dashboard.bedrijfsdashboard'))
        return f(*args, **kwargs)
    return wrapper


# ---------------------------
# DB helpers
# ---------------------------
def get_user_by_username(username: str):
    """
    Haal volledige user op (incl. naam) zodat we sessie goed kunnen vullen.
    """
    conn = db.get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    row = c.execute(
        """
        SELECT id, username, password_hash, email, naam, 
               COALESCE(is_admin, 0) AS is_admin
        FROM users
        WHERE username = ?
        """,
        (username,)
    ).fetchone()
    conn.close()
    return row  # Row of None


# ---------------------------
# Auth acties
# ---------------------------
def login_user(username: str, password: str) -> bool:
    """
    Valideer credentials en zet alle nuttige sessievelden,
    zodat je in je UI direct de naam kunt tonen.
    """
    row = get_user_by_username(username)
    if not row:
        return False

    if row["password_hash"] != hash_password(password):
        return False

    # Succes: sessie vullen
    session.clear()
    session['user_id'] = row['id']
    session['username'] = row['username']
    session['naam'] = row['naam'] or row['username']
    session['is_admin'] = int(row['is_admin'] or 0)

    # Altijd “bekijk als” resetten bij normale login
    session.pop('view_as_user_id', None)
    session.pop('view_as_user_name', None)

    return True


def logout_user():
    """
    Log uit en ruim impersonation op.
    """
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('naam', None)
    session.pop('is_admin', None)
    session.pop('view_as_user_id', None)
    session.pop('view_as_user_name', None)


def register_user(username: str, password: str, email: str, naam: str, is_admin: int = 0) -> bool:
    """
    Maak gebruiker aan. Houd je huidige SHA256-hash aan.
    """
    conn = db.get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            INSERT INTO users (id, username, password_hash, email, naam, is_admin)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                username.strip(),
                hash_password(password),
                (email or "").strip(),
                (naam or "").strip(),
                int(is_admin or 0),
            )
        )
        conn.commit()
        return True
    except Exception:
        # Kan bijv. UNIQUE constraint failure zijn
        conn.rollback()
        return False
    finally:
        conn.close()
