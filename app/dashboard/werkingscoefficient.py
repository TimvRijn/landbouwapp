# app/dashboard/werkingscoefficient.py

def is_dierlijk_meststof(meststof_naam):
    """Check of een meststof dierlijk is"""
    if not meststof_naam:
        return False
    dierlijk = [
        'drijfmest', 'vaste mest', 'gier', 'stal', 'kip', 'varkens', 'rund',
        'geiten', 'schapen', 'pluimvee', 'nertsen', 'leghennen', 'mest', 'compost'
    ]
    return any(d in meststof_naam.lower() for d in dierlijk)


def is_kunstmest(meststof_type, meststof_naam):
    """Check of een meststof kunstmest is"""
    if meststof_type and meststof_type.lower() == "kunstmest":
        return True
    if meststof_naam and "kunstmest" in meststof_naam.lower():
        return True
    return False


def bereken_werking(meststof_naam):
    """
    Bereken werkingscoefficient voor een meststof
    Vereenvoudigde versie die alleen meststof_naam nodig heeft
    """
    if not meststof_naam:
        return 60.0

    meststof_lower = meststof_naam.lower()

    # Kunstmest krijgt altijd 100% werking
    if 'kunstmest' in meststof_lower:
        return 100.0

    # Dierlijke meststoffen
    if is_dierlijk_meststof(meststof_naam):
        # Drijfmest heeft meestal hogere werking
        if 'drijfmest' in meststof_lower:
            return 75.0
        # Vaste mest heeft lagere werking
        elif 'vaste' in meststof_lower and 'mest' in meststof_lower:
            return 25.0
        # Compost heeft lage werking
        elif 'compost' in meststof_lower:
            return 20.0
        # Gier heeft hoge werking
        elif 'gier' in meststof_lower:
            return 80.0
        # Andere dierlijke mest default
        else:
            return 65.0

    # Alle andere meststoffen (kunstmest, etc.)
    return 100.0


# Legacy functies voor backward compatibility (niet gebruikt in dashboard)
def map_meststof_naam(naam, eigen_bedrijf):
    if not naam:
        return ""
    naam = naam.lower()
    if "drijfmest" in naam and "varkens" in naam:
        return "Drijfmest van varkens"
    if "drijfmest" in naam and "overige" in naam:
        return "Drijfmest van overige diersoorten"
    if "drijfmest" in naam and any(x in naam for x in ['geiten', 'schapen', 'rund']):
        return "Drijfmest van graasdieren op het eigen bedrijf geproduceerd" if eigen_bedrijf else "Drijfmest van graasdieren aangevoerd"
    if "drijfmest" not in naam and any(x in naam for x in ['geiten', 'schapen', 'rund']):
        return "Vaste mest van graasdieren op het eigen bedrijf geproduceerd" if eigen_bedrijf else "Vaste mest van graasdieren aangevoerd"
    if "drijfmest" not in naam and any(x in naam for x in ["varken", "kippen", "pluimvee", "nertsen", "leghennen"]):
        return "Vaste mest van varkens, pluimvee en nertsen"
    if "drijfmest" not in naam and "overige" in naam:
        return "Vaste mest van overige diersoorten"
    if "compost" in naam:
        return "Compost"
    if "zuiveringsslib" in naam:
        return "Zuiveringsslib"
    if "overige organische" in naam:
        return "Overige organische meststoffen"
    return naam


def bepaal_toepassing(mapped_naam, gewas, grondsoort, maand):
    gewas = (gewas or '').lower()
    grondsoort = (grondsoort or '').lower()
    maand = int(maand) if maand else 0

    if mapped_naam == "Drijfmest van graasdieren op het eigen bedrijf geproduceerd":
        if "met beweiden" in gewas:
            return "Op bedrijf met beweiding"
        return "Op bedrijf zonder beweiding"
    if mapped_naam == "Drijfmest van graasdieren aangevoerd":
        return ""
    if mapped_naam == "Drijfmest van varkens":
        if "klei" in grondsoort or "veen" in grondsoort:
            return "Op klei en veen"
        if "zand" in grondsoort or "löss" in grondsoort or "loss" in grondsoort:
            return "Op zand en löss"
        return ""
    return ""


def fetch_werkingscoefficient(conn, jaar, mapped_naam, toepassing=None):
    """
    Haal werking uit oude tabel.
    Als toepassing 'NaN' is (string), behandel het als None.
    Ook in de database wordt 'NaN' gelijkgesteld aan NULL.
    """
    cur = conn.cursor()

    # === 1. Normaliseer de toepassing-parameter ===
    if toepassing and str(toepassing).strip().lower() == "nan":
        toepassing = None

    if toepassing:
        # === 2. Query met toepassing ===
        cur.execute(
            """
            SELECT werking
            FROM stikstof_werkingscoefficient_dierlijk
            WHERE jaar = %s
              AND meststof = %s
              AND (
                    NULLIF(toepassing, 'NaN') = %s 
                    OR NULLIF(toepassing, 'NaN') IS NULL
                  )
            ORDER BY toepassing DESC
            LIMIT 1
            """,
            (jaar, mapped_naam, toepassing),
        )
    else:
        # === 3. Query zonder toepassing (alleen NULL/NaN toep.) ===
        cur.execute(
            """
            SELECT werking
            FROM stikstof_werkingscoefficient_dierlijk
            WHERE jaar = %s
              AND meststof = %s
              AND (NULLIF(toepassing, 'NaN') IS NULL)
            LIMIT 1
            """,
            (jaar, mapped_naam),
        )

    row = cur.fetchone()
    if row:
        return float(row[0])
    return None
