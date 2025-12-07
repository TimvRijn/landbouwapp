# app/__init__.py

from dotenv import load_dotenv
load_dotenv()  # <-- moet als allereerste regel!

import os
from flask import Flask

from app.bedrijven.routes import bedrijven_bp
from app.percelen.routes import percelen_bp
from app.gebruiksnormen.routes import gebruiksnormen_bp
from app.universele_data.routes import universele_data_bp
from app.gebruikers.routes import gebruikers_bp
from app.bemestingen.routes import bemestingen_bp
from app.bemestingen.werkingscoefficienten import werkingscoefficienten_bp
from app.dashboard.routes import dashboard_bp
from app.rapportage.routes import rapportage_bp

import app.models.database_beheer as db


def create_app():
    # Maak de Flask app
    app = Flask(__name__)

    # Secret key (haal vanuit .env)
    app.secret_key = os.getenv("SECRET_KEY", "dev_key_change_me")

    # Lees Google Maps API key
    app.config["GOOGLE_MAPS_API_KEY"] = os.getenv("GOOGLE_MAPS_API_KEY")

    # DB init
    db.init_db()

    # API KEY beschikbaar maken in Jinja templates
    @app.context_processor
    def inject_google_maps_key():
        return {
            "GOOGLE_MAPS_API_KEY": app.config.get("GOOGLE_MAPS_API_KEY")
        }

    # Register alle blueprints
    app.register_blueprint(bedrijven_bp)
    app.register_blueprint(percelen_bp)
    app.register_blueprint(gebruiksnormen_bp)
    app.register_blueprint(universele_data_bp)
    app.register_blueprint(gebruikers_bp)
    app.register_blueprint(bemestingen_bp)
    app.register_blueprint(werkingscoefficienten_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(rapportage_bp)

    return app


# Zorg dat app beschikbaar is voor gunicorn / render
app = create_app()
