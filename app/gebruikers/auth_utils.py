# app/gebruikers/auth_utils.py
from functools import wraps
from flask import session, redirect, url_for, flash
import hashlib
import uuid
from datetime import datetime, timedelta, timezone   # NEW

import app.models.database_beheer as db


# ---------------------------
# Helpers voor (impersonated) user
# ---------------------------
def effective_user_id():
    return session.get('view_as_user_id') or session.get('user_id')


def is_impersonating():
    return 'view_as_user_id' in session


def is_admin():
    return int(session.get('is_admin', 0)) == 1


def current_user_display_name():
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
            return redirect(url_for('dashboard.bedrijfsdashboard'))
        return f(*args, **kwargs)
    return wrapper


# ---------------------------
# DB helpers
# ---------------------------
def get_user_by_username(username: str):
    conn, c = db.get_dict_cursor()
    try:
        c.execute(
            """
            SELECT id, username, password_hash, email, naam,
                   COALESCE(is_admin, 0) AS is_admin
            FROM users
            WHERE username = %s
            """,
            (username,)
        )
        row = c.fetchone()
    finally:
        conn.close()
    return row


# NEW: ook lookup op e-mail
def get_user_by_email(email: str):
    conn, c = db.get_dict_cursor()
    try:
        c.execute(
            """
            SELECT id, username, password_hash, email, naam,
                   COALESCE(is_admin, 0) AS is_admin
            FROM users
            WHERE lower(email) = lower(%s)
            """,
            (email,)
        )
        row = c.fetchone()
    finally:
        conn.close()
    return row


# NEW: wachtwoord bijwerken
def update_user_password(user_id: str, new_password: str) -> None:
    conn = db.get_connection()
    c = conn.cursor()
    try:
        c.execute(
            "UPDATE users SET password_hash=%s WHERE id=%s",
            (hash_password(new_password), user_id)
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------
# Auth acties
# ---------------------------
def login_user(username: str, password: str) -> bool:
    row = get_user_by_username(username)
    if not row:
        return False
    if row["password_hash"] != hash_password(password):
        return False

    session.clear()
    session['user_id'] = row['id']
    session['username'] = row['username']
    session['naam'] = row['naam'] or row['username']
    session['is_admin'] = int(row['is_admin'] or 0)
    session.pop('view_as_user_id', None)
    session.pop('view_as_user_name', None)
    return True


def logout_user():
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('naam', None)
    session.pop('is_admin', None)
    session.pop('view_as_user_id', None)
    session.pop('view_as_user_name', None)


def register_user(username: str, password: str, email: str, naam: str, is_admin: int = 0) -> bool:
    conn = db.get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            INSERT INTO users (id, username, password_hash, email, naam, is_admin)
            VALUES (%s, %s, %s, %s, %s, %s)
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
        conn.rollback()
        return False
    finally:
        conn.close()


# ---------------------------
# NEW: Reset token helpers
# ---------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _in_iso(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()


def create_reset_token(user_id: str, ttl_minutes: int = 60) -> str:
    """Maak een eenmalige reset-token aan voor de gebruiker."""
    token = uuid.uuid4().hex  # 32 hex chars
    conn = db.get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            INSERT INTO password_reset_tokens (token, user_id, created_at, expires_at, used)
            VALUES (%s, %s, %s, %s, 0)
            """,
            (token, user_id, _now_iso(), _in_iso(ttl_minutes))
        )
        conn.commit()
        return token
    finally:
        conn.close()


def verify_reset_token(token: str):
    """
    Return user_id als token geldig is (bestaat, niet gebruikt, niet verlopen).
    Anders None.
    """
    conn, c = db.get_dict_cursor()
    try:
        c.execute(
            """
            SELECT token, user_id, used, expires_at
            FROM password_reset_tokens
            WHERE token = %s
            """,
            (token,)
        )
        row = c.fetchone()
        if not row:
            return None
        if int(row.get("used") or 0) == 1:
            return None

        exp_val = row.get("expires_at")
        if isinstance(exp_val, str):
            try:
                exp = datetime.fromisoformat(exp_val)
            except Exception:
                return None
        elif isinstance(exp_val, datetime):
            exp = exp_val
        else:
            return None

        if datetime.now(timezone.utc) > exp:
            return None

        return row["user_id"]
    finally:
        conn.close()


def consume_reset_token(token: str) -> None:
    """Markeer token als gebruikt."""
    conn = db.get_connection()
    c = conn.cursor()
    try:
        c.execute("UPDATE password_reset_tokens SET used=1 WHERE token=%s", (token,))
        conn.commit()
    finally:
        conn.close()
