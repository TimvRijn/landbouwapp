# app/routes/werkingscoefficienten.py
from flask import Blueprint, jsonify, current_app
import sqlite3
import os

werkingscoefficienten_bp = Blueprint('werkingscoefficienten_bp', __name__)

@werkingscoefficienten_bp.route('/api/werkingscoefficienten')
def get_werkingscoefficienten():
    try:
        db_path = os.path.join(current_app.instance_path, 'database.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT jaar, meststof, toepassing, werking FROM stikstof_werkingscoefficient_dierlijk")
        rows = cursor.fetchall()
        conn.close()
        return jsonify([
            {"jaar": r[0], "meststof": r[1], "toepassing": r[2] or "", "werking": r[3] or 0}
            for r in rows
        ])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
