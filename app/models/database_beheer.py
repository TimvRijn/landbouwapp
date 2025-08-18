import sqlite3
import uuid

DB_NAME = 'instance/database.db'

def get_connection():
    return sqlite3.connect(DB_NAME)

def init_db():
    conn = get_connection()
    c = conn.cursor()

    # Bedrijven
    c.execute('''
CREATE TABLE IF NOT EXISTS bedrijven (
    id TEXT PRIMARY KEY,
    naam TEXT NOT NULL,
    plaats TEXT,
    user_id TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
)
    ''')

    # Percelen
    c.execute('''
CREATE TABLE IF NOT EXISTS percelen (
    id TEXT PRIMARY KEY,
    perceelnaam TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    polygon_coordinates TEXT,  -- JSON string met coördinaten
    calculated_area REAL,  -- Automatisch berekende oppervlakte uit polygon
    adres TEXT,
    oppervlakte REAL,
    grondsoort TEXT,
    p_al REAL,
    p_cacl2 REAL,
    nv_gebied INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
)
    ''')

    # Gewassen + Stikstofnormen
    c.execute('''
        CREATE TABLE IF NOT EXISTS stikstof_gewassen_normen (
            id TEXT PRIMARY KEY,
            jaar INTEGER NOT NULL,
            gewas TEXT NOT NULL,
            n_klei REAL,
            n_noordwestcentraal_zand REAL,
            n_zuid_zand REAL,
            n_loss REAL,
            n_veen REAL,
            UNIQUE(jaar, gewas) ON CONFLICT REPLACE
        )
    ''')

    # GebruikNormen
    c.execute('''
CREATE TABLE IF NOT EXISTS gebruiksnormen (
    id TEXT PRIMARY KEY,
    jaar INTEGER NOT NULL,
    bedrijf_id TEXT NOT NULL,
    perceel_id TEXT NOT NULL,
    gewas_id TEXT NOT NULL,
    fosfaatnorm_id TEXT,
    derogatienorm_id TEXT,
    stikstof_norm_kg_ha REAL,
    stikstof_dierlijk_kg_ha REAL,
    fosfaat_norm_kg_ha REAL,
    derogatie INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    FOREIGN KEY (bedrijf_id) REFERENCES bedrijven(id),
    FOREIGN KEY (perceel_id) REFERENCES percelen(id),
    FOREIGN KEY (gewas_id) REFERENCES stikstof_gewassen_normen(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
    FOREIGN KEY (fosfaatnorm_id) REFERENCES fosfaatnormen(id),
    FOREIGN KEY (derogatienorm_id) REFERENCES derogatie_normen(id)
)

    ''')

    # Fosfaatnormen (lookup)
    c.execute('''
        CREATE TABLE IF NOT EXISTS fosfaat_normen (
            id TEXT PRIMARY KEY,
            jaar INTEGER NOT NULL,
            type_land TEXT NOT NULL,            -- 'grasland' of 'bouwland'
            p_cacl2_van REAL NOT NULL,
            p_cacl2_tot REAL NOT NULL,
            p_al_van INTEGER NOT NULL,
            p_al_tot INTEGER NOT NULL,
            norm_omschrijving TEXT,
            norm_kg INTEGER NOT NULL
        )
    ''')

    # Derogatie normen
    c.execute('''
        CREATE TABLE IF NOT EXISTS derogatie_normen (
            id TEXT PRIMARY KEY,
            jaar INTEGER NOT NULL,
            derogatie INTEGER NOT NULL,        -- 0 = nee, 1 = ja
            stikstof_norm_kg_ha REAL NOT NULL,
            nv_gebied INTEGER NOT NULL   -- 0 = nee, 1 = ja
        )
    ''')

     # Werkingscoëfficiënten
    c.execute('''
        CREATE TABLE IF NOT EXISTS stikstof_werkingscoefficient_dierlijk (
            id TEXT PRIMARY KEY,
            jaar INTEGER NOT NULL,
            meststof TEXT NOT NULL,
            toepassing TEXT,
            werking REAL NOT NULL
        )
    ''')
    # meststoffen
    c.execute('''
        CREATE TABLE IF NOT EXISTS universal_fertilizers (
            id TEXT PRIMARY KEY,
            meststof TEXT NOT NULL,
            toepassing TEXT NOT NULL,
            n REAL,
            p2o5 REAL,
            k2o REAL
        )
    ''')
    # meststoffen
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            email TEXT,
            naam TEXT,
            is_admin INTEGER DEFAULT 0 
        )
    ''')
    # Bemestingen
    c.execute('''
CREATE TABLE IF NOT EXISTS bemestingen (
    id TEXT PRIMARY KEY,                -- UUID van deze bemesting
    gebruiksnorm_id TEXT NOT NULL,      -- UUID uit gebruiksnormen (gebruiksnormen.id)
    bedrijf_id TEXT NOT NULL,           -- UUID uit bedrijven
    perceel_id TEXT NOT NULL,           -- UUID uit percelen
    meststof_id TEXT NOT NULL,          -- UUID uit universal_fertilizers
    datum DATE NOT NULL,
    hoeveelheid_kg_ha REAL NOT NULL,
    n_kg_ha REAL NOT NULL,        -- Stikstof hoeveelheid in kg/ha
    p2o5_kg_ha REAL NOT NULL,  -- Fosfaat hoeveelheid in kg/ha
    k2o_kg_ha REAL NOT NULL,  -- Kalium hoeveelheid in kg/ha
    eigen_bedrijf INTEGER DEFAULT 0,    -- 1 = ja, 0 = nee
    notities TEXT
)
    ''')



    conn.commit()
    conn.close()

def delete_row(table, row_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute(f'DELETE FROM {table} WHERE id = ?', (row_id,))
    conn.commit()
    conn.close()

def update_row(table, row_id, updates: dict):
    conn = get_connection()
    c = conn.cursor()
    set_clause = ', '.join(f"{col}=?" for col in updates.keys())
    values = list(updates.values()) + [row_id]
    c.execute(f'UPDATE {table} SET {set_clause} WHERE id=?', values)
    conn.commit()
    conn.close()
