# app/routes/werkingscoefficienten.py
from flask import Blueprint, jsonify
from app.models.database_beheer import get_connection
import logging

werkingscoefficienten_bp = Blueprint('werkingscoefficienten_bp', __name__)
logger = logging.getLogger(__name__)

@werkingscoefficienten_bp.route('/api/werkingscoefficienten')
def get_werkingscoefficienten():
    """
    Genormaliseerde API:
    [
      { "jaar": 2023 | null, "meststof": "...", "toepassing": "...", "werking": 75.0 },
      ...
    ]
    Werkt met:
    - oude tabel: stikstof_werkingscoefficient_dierlijk (met kolom 'jaar')
    - nieuwe tabel: werkingscoefficienten (zonder 'jaar')
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        data = []

        # 1) Eerst oude tabel proberen
        try:
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
        except Exception:
            # als deze tabel niet bestaat of query faalt → door naar nieuwe structuur
            logger.info("stikstof_werkingscoefficient_dierlijk niet beschikbaar, probeer werkingscoefficienten")

        # 2) Nieuwe tabel (zonder jaar)
        try:
            cur.execute("""
                SELECT meststof_naam, toepassing, werking_pct
                FROM werkingscoefficienten
            """)
            rows = cur.fetchall()
            data = [
                {
                    "jaar": None,
                    "meststof": r[0] or "",
                    "toepassing": r[1] or "",
                    "werking": float(r[2] or 0.0),
                }
                for r in rows
            ]
            return jsonify(data)
        except Exception:
            logger.warning("Geen werkingscoefficienten-tabel gevonden (oud of nieuw).")
            return jsonify([])

    except Exception as e:
        logger.error(f"Fout in get_werkingscoefficienten: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn is not None:
            conn.close()
