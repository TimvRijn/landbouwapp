# app/routes/werkingscoefficienten.py
from flask import Blueprint, jsonify
from app.models.database_beheer import get_connection
import logging

werkingscoefficienten_bp = Blueprint('werkingscoefficienten_bp', __name__)
logger = logging.getLogger(__name__)

@werkingscoefficienten_bp.route('/api/werkingscoefficienten')
def get_werkingscoefficienten():
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT jaar, meststof, toepassing, werking
            FROM stikstof_werkingscoefficient_dierlijk
        """)
        rows = cur.fetchall()

        data = [
            {
                "jaar": r[0],
                "meststof": r[1] or "",
                "toepassing": r[2] or "",
                "werking": float(r[3] or 0.0),
            }
            for r in rows
        ]
        return jsonify(data)

    except Exception as e:
        logger.error(f"Fout in get_werkingscoefficienten: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn is not None:
            conn.close()

