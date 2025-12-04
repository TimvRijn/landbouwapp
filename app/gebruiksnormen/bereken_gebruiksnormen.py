import app.models.database_beheer as db


def get_best_year(c, table: str, jaar: int):
    """
    Zoek het hoogste jaar <= gegeven jaar in de opgegeven tabel.
    Let op: 'table' komt alleen uit vaste waardes in de code (geen user-input).
    """
    q = f"SELECT MAX(jaar) FROM {table} WHERE jaar <= %s"
    c.execute(q, (jaar,))
    row = c.fetchone()
    return row[0] if row else None


def bereken_fosfaatnorm(perceel_id, gewas_id, jaar=None):
    conn = db.get_connection()
    c = conn.cursor()
    try:
        # Perceel ophalen
        c.execute(
            'SELECT grondsoort, p_al, p_cacl2 FROM percelen WHERE id=%s',
            (perceel_id,)
        )
        perceel = c.fetchone()
        if not perceel:
            return None

        # p_al en p_cacl2 altijd als float
        try:
            p_al = float(str(perceel[1]).replace(',', '.')) if perceel[1] is not None else None
            p_cacl2 = float(str(perceel[2]).replace(',', '.')) if perceel[2] is not None else None
        except ValueError:
            return None

        if p_al is None or p_cacl2 is None:
            return None

        # Gewas ophalen
        c.execute(
            'SELECT gewas, jaar FROM stikstof_gewassen_normen WHERE id=%s',
            (gewas_id,)
        )
        gewas_row = c.fetchone()
        if not gewas_row:
            return None

        gewas_naam, gewas_jaar = gewas_row[0].lower(), gewas_row[1]
        lookup_jaar = jaar if jaar is not None else gewas_jaar

        # Beste jaar (hoogste jaar <= gekozen jaar)
        best_year = get_best_year(c, 'fosfaat_normen', lookup_jaar)
        if best_year is None:
            return None

        type_land = 'grasland' if 'gras' in gewas_naam else 'bouwland'

        # Zoek rij waarbij perceelwaarden TUSSEN van/tot liggen
        c.execute(
            '''
            SELECT norm_kg
            FROM fosfaat_normen
            WHERE jaar = %s
              AND LOWER(type_land) = LOWER(%s)
              AND %s BETWEEN LEAST(p_cacl2_van, p_cacl2_tot) 
                        AND GREATEST(p_cacl2_van, p_cacl2_tot)
              AND %s BETWEEN LEAST(p_al_van, p_al_tot)
                        AND GREATEST(p_al_van, p_al_tot)      
            ORDER BY p_cacl2_van, p_al_van
            LIMIT 1
            ''',
            (best_year, type_land, p_cacl2, p_al)
        )
        norm_row = c.fetchone()
        return float(norm_row[0]) if norm_row else None

    finally:
        conn.close()


def bereken_stikstofnorm(gewas_id, perceel_id, jaar=None):
    conn = db.get_connection()
    c = conn.cursor()
    try:
        # Perceel
        c.execute(
            'SELECT grondsoort, nv_gebied FROM percelen WHERE id=%s',
            (perceel_id,)
        )
        perceel = c.fetchone()
        grondsoort = perceel[0].lower() if perceel and perceel[0] else ''
        nv_gebied = perceel[1] if perceel else 0

        # Gewas
        c.execute(
            'SELECT * FROM stikstof_gewassen_normen WHERE id=%s',
            (gewas_id,)
        )
        gewas = c.fetchone()
        if not gewas:
            return None

        gewas_jaar = gewas[1]
        lookup_jaar = jaar if jaar is not None else gewas_jaar

        best_year = get_best_year(c, 'stikstof_gewassen_normen', lookup_jaar)
        if best_year is None:
            return None

        c.execute(
            'SELECT * FROM stikstof_gewassen_normen WHERE jaar=%s AND gewas=%s',
            (best_year, gewas[2])
        )
        norm_row = c.fetchone()
        if not norm_row:
            return None

        # Kolommen: [0]=id, [1]=jaar, [2]=gewas,
        # [3]=klei, [4]=noord/west/centraal zand, [5]=zuid zand,
        # [6]=löss, [7]=veen  (zelfde als je oude code)
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

        return round(norm, 2) if norm is not None else None

    finally:
        conn.close()


def bereken_stikstof_dierlijk_kg_ha(bedrijf_id, perceel_id, gewas_id, derogatie, jaar=None):
    conn = db.get_connection()
    c = conn.cursor()
    try:
        # NV-gebied
        c.execute(
            'SELECT nv_gebied FROM percelen WHERE id=%s',
            (perceel_id,)
        )
        perceel = c.fetchone()
        nv_gebied = perceel[0] if perceel else 0

        # Gewas
        c.execute(
            'SELECT jaar, gewas FROM stikstof_gewassen_normen WHERE id=%s',
            (gewas_id,)
        )
        gewas = c.fetchone()
        if not gewas:
            return None

        gewas_jaar, gewas_naam = gewas[0], gewas[1].lower()
        lookup_jaar = jaar if jaar is not None else gewas_jaar

        best_year = get_best_year(c, 'derogatie_normen', lookup_jaar)
        if best_year is None:
            return None

        is_gras = 'gras' in gewas_naam
        derogatie_keuze = 1 if is_gras and derogatie else 0

        c.execute(
            '''
            SELECT stikstof_norm_kg_ha FROM derogatie_normen
            WHERE jaar=%s AND nv_gebied=%s AND derogatie=%s
            LIMIT 1
            ''',
            (best_year, nv_gebied, derogatie_keuze)
        )
        norm_row = c.fetchone()
        return float(norm_row[0]) if norm_row else None

    finally:
        conn.close()
