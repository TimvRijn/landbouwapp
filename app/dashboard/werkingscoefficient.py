# werkingscoefficient_utils.py

def map_meststof_naam(naam, eigen_bedrijf):
    if not naam: return ""
    naam = naam.lower()
    if "drijfmest" in naam and "varkens" in naam:
        return "Drijfmest van varkens"
    if "drijfmest" in naam and "overige" in naam:
        return "Drijfmest van overige diersoorten"
    if "drijfmest" in naam and any(x in naam for x in ['geiten', 'schapen', 'rund']):
        return "Drijfmest van graasdieren (eigen bedrijf)" if eigen_bedrijf else "Drijfmest van graasdieren (aangevoerd)"
    if "drijfmest" not in naam and any(x in naam for x in ['geiten', 'schapen', 'rund']):
        return "Vaste mest van graasdieren (eigen bedrijf)" if eigen_bedrijf else "Vaste mest van graasdieren (aangevoerd)"
    if "drijfmest" not in naam and any(x in naam for x in ["varkens", "kippen", "pluimvee", "nertsen", "leghennen"]):
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

    if mapped_naam == "Drijfmest van graasdieren (eigen bedrijf)":
        if "met beweiden" in gewas:
            return "Op bedrijf met beweiding"
        return "Op bedrijf zonder beweiding"
    if mapped_naam == "Drijfmest van graasdieren (aangevoerd)":
        return ""
    if mapped_naam == "Drijfmest van varkens":
        if "klei" in grondsoort or "veen" in grondsoort:
            return "Op klei en veen"
        if "zand" in grondsoort or "löss" in grondsoort or "loss" in grondsoort:
            return "Op zand en löss"
        return ""
    if mapped_naam == "Drijfmest van overige diersoorten":
        return ""
    if mapped_naam == "Dunne fractie na mestbewerking en gier":
        if "klei" in grondsoort or "veen" in grondsoort:
            return "Op klei en veen"
        if "zand" in grondsoort or "löss" in grondsoort or "loss" in grondsoort:
            return "Op zand en löss"
        return ""
    if mapped_naam == "Vaste mest van graasdieren (eigen bedrijf)":
        if ("klei" in grondsoort or "veen" in grondsoort) and (maand == 9 or maand == 10 or maand == 11 or maand == 12 or maand == 1):
            return "Op bouwland op klei en veen, van 1 september t/m 31 januari"
        if "met beweiden" in gewas:
            return "Overige toepassingen op bedrijf met beweiding"
        return "Overige toepassingen op bedrijf zonder beweiding"
    if mapped_naam == "Vaste mest van graasdieren (aangevoerd)":
        if ("klei" in grondsoort or "veen" in grondsoort) and (maand == 9 or maand == 10 or maand == 11 or maand == 12 or maand == 1):
            return "Op bouwland op klei en veen, van 1 september t/m 31 januari"
        return "Overige toepassingen"
    if mapped_naam == "Vaste mest van varkens, pluimvee en nertsen":
        if ("klei" in grondsoort or "veen" in grondsoort) and (maand == 9 or maand == 10 or maand == 11 or maand == 12 or maand == 1):
            return "Op bouwland op klei en veen, van 1 september t/m 31 januari"
        return "Overige toepassingen"
    if mapped_naam == "Vaste mest van overige diersoorten":
        if ("klei" in grondsoort or "veen" in grondsoort) and (maand == 9 or maand == 10 or maand == 11 or maand == 12 or maand == 1):
            return "Op bouwland op klei en veen, van 1 september t/m 31 januari"
        return "Overige toepassingen"
    if mapped_naam in ["Compost", "Champost", "Zuiveringsslib", "Overige organische meststoffen"]:
        return ""
    if mapped_naam == "Mengsels van meststoffen":
        return ""
    return ""

def is_dierlijk_meststof(meststof_naam):
    if not meststof_naam: return False
    dierlijk = ['drijfmest', 'vaste mest', 'gier', 'stal', 'kip', 'varkens', 'rund', 'geiten', 'schapen', 'pluimvee', 'nertsen', 'leghennen']
    return any(d in meststof_naam.lower() for d in dierlijk)

def is_kunstmest(meststof_type, meststof_naam):
    if meststof_type and meststof_type.lower() == "kunstmest":
        return True
    if meststof_naam and "kunstmest" in meststof_naam.lower():
        return True
    return False

def fetch_werkingscoefficient(conn, jaar, mapped_naam, toepassing=None):
    # Haal werking uit tabel, return None als niet gevonden
    if toepassing:
        row = conn.execute("""
            SELECT werking FROM stikstof_werkingscoefficient_dierlijk
            WHERE jaar = ? AND meststof = ? AND (toepassing = ? OR toepassing IS NULL)
            ORDER BY toepassing DESC LIMIT 1
        """, (jaar, mapped_naam, toepassing)).fetchone()
    else:
        row = conn.execute("""
            SELECT werking FROM stikstof_werkingscoefficient_dierlijk
            WHERE jaar = ? AND meststof = ? AND toepassing IS NULL
            LIMIT 1
        """, (jaar, mapped_naam)).fetchone()
    if row:
        return float(row["werking"])
    return None

def bereken_werking(conn, jaar, meststof_naam, meststof_type, eigen_bedrijf, gewas, grondsoort, maand):
    mapped_naam = map_meststof_naam(meststof_naam, eigen_bedrijf)
    toepassing = bepaal_toepassing(mapped_naam, gewas, grondsoort, maand)
    # Kunstmest altijd 100%
    if is_kunstmest(meststof_type, meststof_naam):
        werking = 100.0
    elif is_dierlijk_meststof(meststof_naam):
        werking = fetch_werkingscoefficient(conn, jaar, mapped_naam, toepassing) or 65.0
    else:
        werking = 100.0
    return werking, toepassing, mapped_naam
