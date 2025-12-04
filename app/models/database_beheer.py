# app/models/database_beheer.py

import os
import uuid

import psycopg2
from psycopg2.extras import RealDictCursor

# Zorg dat je in Render / lokaal een DATABASE_URL hebt, bv:
# postgres://user:password@host:5432/dbnaam
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is niet gezet. "
        "Zet deze als environment variable (bijv. in .env of Render)."
    )


def get_connection():
    """
    Maak een nieuwe PostgreSQL-verbinding.
    In de rest van je code gebruik je deze via db.get_connection()
    of db.get_dict_cursor().
    """
    return psycopg2.connect(DATABASE_URL)


def get_dict_cursor():
    """
    Handige helper als je rows als dict wilt gebruiken:
    conn, cur = db.get_dict_cursor()
    cur.execute(...)
    rows = cur.fetchall()  # list van dicts
    """
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    return conn, cur


def init_db():
    """
    Maakt alle tabellen aan als ze nog niet bestaan.
    Draai je één keer bij startup (bijv. in app factory).
    """
    conn = get_connection()
    conn.autocommit = True
    c = conn.cursor()

    # Users eerst, omdat andere tabellen ernaar refereren
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            email TEXT,
            naam TEXT,
            is_admin INTEGER DEFAULT 0
        )
        """
    )

    # Bedrijven
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS bedrijven (
            id TEXT PRIMARY KEY,
            naam TEXT NOT NULL,
            plaats TEXT,
            user_id TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    # Percelen
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS percelen (
            id TEXT PRIMARY KEY,              -- UUID

            perceelnaam TEXT NOT NULL,        -- Naam in de UI

            oppervlakte REAL,                 -- Oppervlakte in ha
            grondsoort TEXT,                  -- Vrij veld bij handmatig toevoegen
            p_al REAL,                        -- Vrij veld
            p_cacl2 REAL,                     -- Vrij veld
            nv_gebied INTEGER,                -- 0/1

            latitude REAL,                    -- Centroid lat
            longitude REAL,                   -- Centroid lon
            adres TEXT,                       -- Adres (optioneel handmatig)

            polygon_coordinates TEXT,         -- Jouw bestaande [{lat,lng},...] lijst
            calculated_area REAL,             -- Eventueel berekende oppervlakte

            -- PDOK gerelateerd
            pdok_id TEXT,                     -- Unieke id van PDOK perceel (optioneel)
            pdok_category TEXT,               -- Alleen de category, voor filtering
            pdok_source TEXT,                 -- "PDOK_BRPGewaspercelen_OGC" of "manual"
            geometry_geojson TEXT,            -- Oorspronkelijke GeoJSON polygon

            user_id TEXT NOT NULL,            -- Welke gebruiker dit perceel heeft
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    # Gewassen + Stikstofnormen
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS stikstof_gewassen_normen (
            id TEXT PRIMARY KEY,
            jaar INTEGER NOT NULL,
            gewas TEXT NOT NULL,
            n_klei REAL,
            n_noordwestcentraal_zand REAL,
            n_zuid_zand REAL,
            n_loss REAL,
            n_veen REAL,
            UNIQUE(jaar, gewas)
        )
        """
    )

    # Fosfaatnormen (lookup)
    c.execute(
        """
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
        """
    )

    # Derogatie normen
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS derogatie_normen (
            id TEXT PRIMARY KEY,
            jaar INTEGER NOT NULL,
            derogatie INTEGER NOT NULL,        -- 0 = nee, 1 = ja
            stikstof_norm_kg_ha REAL NOT NULL,
            nv_gebied INTEGER NOT NULL         -- 0 = nee, 1 = ja
        )
        """
    )

    # GebruikNormen
    c.execute(
        """
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
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (fosfaatnorm_id) REFERENCES fosfaat_normen(id),
            FOREIGN KEY (derogatienorm_id) REFERENCES derogatie_normen(id)
        )
        """
    )

    # Werkingscoëfficiënten
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS stikstof_werkingscoefficient_dierlijk (
            id TEXT PRIMARY KEY,
            jaar INTEGER NOT NULL,
            meststof TEXT NOT NULL,
            toepassing TEXT,
            werking REAL NOT NULL
        )
        """
    )

    # Meststoffen
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS universal_fertilizers (
            id TEXT PRIMARY KEY,
            meststof TEXT NOT NULL,
            toepassing TEXT NOT NULL,
            leverancier TEXT,
            n REAL,
            p2o5 REAL,
            k2o REAL,
            b REAL,
            cao REAL,
            cu REAL,
            co REAL,
            cl REAL,
            fe REAL,
            mgo REAL,
            mn REAL,
            mo REAL,
            zn REAL,
            na2o REAL,
            se REAL,
            sio2 REAL,
            so3 REAL
        )
        """
    )

    # Bemestingen
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS bemestingen (
            id TEXT PRIMARY KEY,
            gebruiksnorm_id TEXT NOT NULL,
            bedrijf_id TEXT NOT NULL,
            perceel_id TEXT NOT NULL,
            meststof_id TEXT NOT NULL,
            datum DATE NOT NULL,
            hoeveelheid_kg_ha REAL NOT NULL,
            n_kg_ha REAL NOT NULL,
            p2o5_kg_ha REAL NOT NULL,
            k2o_kg_ha REAL NOT NULL,
            werkzame_n_kg_ha REAL DEFAULT 0,      -- NIEUW
            werkzame_p2o5_kg_ha REAL DEFAULT 0,   -- NIEUW
            n_dierlijk_kg_ha REAL DEFAULT 0,      -- NIEUW
            eigen_bedrijf INTEGER DEFAULT 0,
            notities TEXT
        )
        """
    )

    # Wachtwoorden reset tokens
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,     -- ISO8601
            expires_at TEXT NOT NULL,     -- ISO8601
            used INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )

    conn.close()


def delete_row(table: str, row_id: str):
    """
    Verwijder één rij op basis van id.
    LET OP: 'table' mag alleen uit je eigen code komen (niet uit user input),
    anders krijg je SQL-injectie.
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        query = f"DELETE FROM {table} WHERE id = %s"
        c.execute(query, (row_id,))
        conn.commit()
    finally:
        conn.close()


def update_row(table: str, row_id: str, updates: dict):
    """
    Algemene update helper:
    update_row('users', user_id, {'naam': 'Tim', 'email': 'x@y.nl'})
    """
    if not updates:
        return

    conn = get_connection()
    c = conn.cursor()
    try:
        set_clause = ", ".join(f"{col} = %s" for col in updates.keys())
        values = list(updates.values()) + [row_id]
        query = f"UPDATE {table} SET {set_clause} WHERE id = %s"
        c.execute(query, values)
        conn.commit()
    finally:
        conn.close()
