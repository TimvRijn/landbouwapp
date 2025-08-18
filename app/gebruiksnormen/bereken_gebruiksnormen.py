import sqlite3

DB_NAME = 'instance/database.db'

def get_connection():
    return sqlite3.connect(DB_NAME)

def get_best_year(table, jaar):
    conn = get_connection()
    c = conn.cursor()
    q = f"SELECT MAX(jaar) FROM {table} WHERE jaar <= ?"
    best_year = c.execute(q, (jaar,)).fetchone()[0]
    conn.close()
    return best_year

def bereken_fosfaatnorm(perceel_id, gewas_id, jaar=None):
    conn = get_connection()
    c = conn.cursor()
    perceel = c.execute(
        'SELECT grondsoort, p_al, p_cacl2 FROM percelen WHERE id=?',
        (perceel_id,)
    ).fetchone()
    if not perceel:
        conn.close()
        return None
    p_al, p_cacl2 = perceel[1], perceel[2]
    gewas_row = c.execute(
        'SELECT gewas, jaar FROM stikstof_gewassen_normen WHERE id=?',
        (gewas_id,)
    ).fetchone()
    if not gewas_row:
        conn.close()
        return None
    gewas_naam, gewas_jaar = gewas_row[0].lower(), gewas_row[1]
    lookup_jaar = jaar if jaar is not None else gewas_jaar
    best_year = get_best_year('fosfaat_normen', lookup_jaar)
    if best_year is None:
        conn.close()
        return None
    type_land = 'grasland' if 'gras' in gewas_naam.lower() else 'bouwland'
    norm_row = c.execute('''
        SELECT norm_kg FROM fosfaat_normen
        WHERE jaar=? AND type_land=?
        AND ? >= p_cacl2_van AND ? <= p_cacl2_tot
        AND ? >= p_al_van AND ? <= p_al_tot
        LIMIT 1
    ''', (best_year, type_land, p_cacl2, p_cacl2, p_al, p_al)).fetchone()
    conn.close()
    return float(norm_row[0]) if norm_row else None

def bereken_stikstofnorm(gewas_id, perceel_id, jaar=None):
    conn = get_connection()
    c = conn.cursor()
    perceel = c.execute('SELECT grondsoort, nv_gebied FROM percelen WHERE id=?', (perceel_id,)).fetchone()
    grondsoort = perceel[0].lower() if perceel else ''
    nv_gebied = perceel[1] if perceel else 0
    gewas = c.execute('SELECT * FROM stikstof_gewassen_normen WHERE id=?', (gewas_id,)).fetchone()
    if not gewas:
        conn.close()
        return None
    gewas_jaar = gewas[1]
    lookup_jaar = jaar if jaar is not None else gewas_jaar
    best_year = get_best_year('stikstof_gewassen_normen', lookup_jaar)
    if best_year is None:
        conn.close()
        return None
    norm_row = c.execute('SELECT * FROM stikstof_gewassen_normen WHERE jaar=? AND gewas=?', (best_year, gewas[2])).fetchone()
    if not norm_row:
        conn.close()
        return None
    if 'klei' in grondsoort:
        norm = norm_row[3]
    elif 'noord' in grondsoort or 'west' in grondsoort or 'centraal' in grondsoort:
        norm = norm_row[4]
    elif 'zuid' in grondsoort:
        norm = norm_row[5]
    elif 'löss' in grondsoort:
        norm = norm_row[6]
    elif 'veen' in grondsoort:
        norm = norm_row[7]
    else:
        norm = None
    if norm is not None and nv_gebied == 1:
        norm = norm * 0.8
    conn.close()
    return round(norm, 2) if norm is not None else None

def bereken_stikstof_dierlijk_kg_ha(bedrijf_id, perceel_id, gewas_id, derogatie, jaar=None):
    conn = get_connection()
    c = conn.cursor()
    perceel = c.execute('SELECT nv_gebied FROM percelen WHERE id=?', (perceel_id,)).fetchone()
    nv_gebied = perceel[0] if perceel else 0
    gewas = c.execute('SELECT jaar, gewas FROM stikstof_gewassen_normen WHERE id=?', (gewas_id,)).fetchone()
    if not gewas:
        conn.close()
        return None
    gewas_jaar, gewas_naam = gewas[0], gewas[1].lower()
    lookup_jaar = jaar if jaar is not None else gewas_jaar
    best_year = get_best_year('derogatie_normen', lookup_jaar)
    if best_year is None:
        conn.close()
        return None
    is_gras = 'gras' in gewas_naam
    derogatie_keuze = 1 if is_gras and derogatie else 0
    norm_row = c.execute(
        '''SELECT stikstof_norm_kg_ha FROM derogatie_normen
           WHERE jaar=? AND nv_gebied=? AND derogatie=? LIMIT 1
        ''',
        (best_year, nv_gebied, derogatie_keuze)
    ).fetchone()
    conn.close()
    return float(norm_row[0]) if norm_row else None
