from flask import Flask
from app.bedrijven.routes import bedrijven_bp
from app.percelen.routes import percelen_bp
from app.gebruiksnormen.routes import gebruiksnormen_bp
from app.universele_data.routes import universele_data_bp
from app.gebruikers.routes import gebruikers_bp
from app.bemestingen.routes import bemestingen_bp
from app.bemestingen.werkingscoefficienten import werkingscoefficienten_bp
from app.dashboard.routes import dashboard_bp


import app.models.database_beheer as db
import uuid

app = Flask(__name__)

app.secret_key = 'geheim123'  # Zet hier je eigen geheime key!

db.init_db()

# Register Blueprints
app.register_blueprint(bedrijven_bp)
app.register_blueprint(percelen_bp)
app.register_blueprint(gebruiksnormen_bp)
app.register_blueprint(universele_data_bp)
app.register_blueprint(gebruikers_bp)
app.register_blueprint(bemestingen_bp)
app.register_blueprint(werkingscoefficienten_bp)
app.register_blueprint(dashboard_bp)


if __name__ == '__main__':
    app.run(debug=True)
