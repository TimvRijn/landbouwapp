// werkingscoefficienten_utils.js

// Helper: meststofnaam correct mappen met herkomst
function mapMeststofNaam(naam, eigen) {
    if (!naam) return '';
    
    naam = naam.toLowerCase();
    
    // Drijfmest categorieën
    if (naam.includes("drijfmest") && naam.includes("varkens")) {
        return "Drijfmest van varkens";
    }
    if (naam.includes("drijfmest") && naam.includes("overige")) {
        return "Drijfmest van overige diersoorten";
    }
    if (naam.includes("drijfmest") && (naam.includes('geiten') || naam.includes('schapen') || naam.includes('rund'))) {
        return eigen ? "Drijfmest van graasdieren op het eigen bedrijf geproduceerd" : "Drijfmest van graasdieren aangevoerd";
    }
    
    // Vaste mest categorieën
    if (!naam.includes("drijfmest") && (naam.includes('geiten') || naam.includes('schapen') || naam.includes('rund'))) {
        return eigen ? "Vaste mest van graasdieren op het eigen bedrijf geproduceerd" : "Vaste mest van graasdieren aangevoerd";
    }
    if (!naam.includes("drijfmest") && (naam.includes("varkens") || naam.includes("kippen") || naam.includes("pluimvee") || naam.includes("nertsen") || naam.includes("leghennen"))) {
        return "Vaste mest van varkens, pluimvee en nertsen";
    }
    if (!naam.includes("drijfmest") && naam.includes("overige")) {
        return "Vaste mest van overige diersoorten";
    }
    
    // Andere organische meststoffen
    if (naam.includes("compost")) return "Compost";
    if (naam.includes("zuiveringsslib")) return "Zuiveringsslib";
    if (naam.includes("overige organische")) return "Overige organische meststoffen";
    if (naam.includes("mengsel") || naam.includes("meststoffen")) return "Mengsels van meststoffen";
    if (naam.includes("dunne fractie") || naam.includes("gier")) return "Dunne fractie na mestbewerking en gier";
    if (naam.includes("champost")) return "Champost";
    
    // Fallback: return original naam
    return naam;
}

function bepaalToepassing(mappedNaam, gewas, grondsoort, maand) {
    if (!mappedNaam) return '';
    
    gewas = (gewas || '').toLowerCase();
    grondsoort = (grondsoort || '').toLowerCase();
    
    // Zorg dat maand een getal is
    maand = parseInt(maand) || 0;

    // 1. Drijfmest van graasdieren op eigen bedrijf
    if (mappedNaam === "Drijfmest van graasdieren (eigen bedrijf)") {
        if (gewas.includes("met beweiden")) return "Op bedrijf met beweiding";
        return "Op bedrijf zonder beweiding";
    }
    
    // 2. Drijfmest van graasdieren aangevoerd
    if (mappedNaam === "Drijfmest van graasdieren aangevoerd") {
        return ""; // Geen nadere toepassing
    }
    
    // 3. Drijfmest van varkens
    if (mappedNaam === "Drijfmest van varkens") {
        if (grondsoort.includes("klei") || grondsoort.includes("veen")) return "Op klei en veen";
        if (grondsoort.includes("zand") || grondsoort.includes("löss") || grondsoort.includes("loss")) return "Op zand en löss";
        return "";
    }
    
    // 4. Drijfmest van overige diersoorten
    if (mappedNaam === "Drijfmest van overige diersoorten") return "";
    
    // 5. Dunne fractie na mestbewerking en gier
    if (mappedNaam === "Dunne fractie na mestbewerking en gier") {
        if (grondsoort.includes("klei") || grondsoort.includes("veen")) return "Op klei en veen";
        if (grondsoort.includes("zand") || grondsoort.includes("löss") || grondsoort.includes("loss")) return "Op zand en löss";
        return "";
    }

    // 6. Vaste mest van graasdieren op het eigen bedrijf geproduceerd
    if (mappedNaam === "Vaste mest van graasdieren op het eigen bedrijf geproduceerd") {
        // Check of het bouwland is op klei/veen tussen sept-jan
        if ((grondsoort.includes("klei") || grondsoort.includes("veen")) && 
            (maand >= 9 || maand <= 1)) {
            return "Op bouwland op klei en veen, van 1 september t/m 31 januari";
        }
        if (gewas.includes("met beweiden")) return "Overige toepassingen op bedrijf met beweiding";
        return "Overige toepassingen op bedrijf zonder beweiding";
    }
    
    // 7. Vaste mest van graasdieren aangevoerd
    if (mappedNaam === "Vaste mest van graasdieren aangevoerd") {
        if ((grondsoort.includes("klei") || grondsoort.includes("veen")) && 
            (maand >= 9 || maand <= 1)) {
            return "Op bouwland op klei en veen, van 1 september t/m 31 januari";
        }
        return "Overige toepassingen";
    }
    
    // 8. Vaste mest van varkens, pluimvee en nertsen
    if (mappedNaam === "Vaste mest van varkens, pluimvee en nertsen") {
        if ((grondsoort.includes("klei") || grondsoort.includes("veen")) && 
            (maand >= 9 || maand <= 1)) {
            return "Op bouwland op klei en veen, van 1 september t/m 31 januari";
        }
        return "Overige toepassingen";
    }
    
    // 9. Vaste mest van overige diersoorten
    if (mappedNaam === "Vaste mest van overige diersoorten") {
        if ((grondsoort.includes("klei") || grondsoort.includes("veen")) && 
            (maand >= 9 || maand <= 1)) {
            return "Op bouwland op klei en veen, van 1 september t/m 31 januari";
        }
        return "Overige toepassingen";
    }

    // Overige meststoffen (geen specifieke toepassing)
    if (["Compost", "Champost", "Zuiveringsslib", "Overige organische meststoffen", "Mengsels van meststoffen"].includes(mappedNaam)) {
        return "";
    }

    // Default
    return "";
}

// Hulpfunctie om datum te parsen
function parseDutchDate(datumStr) {
    if (!datumStr) return null;
    
    // Verwacht formaat: dd-mm-yyyy
    const parts = datumStr.split('-');
    if (parts.length !== 3) return null;
    
    const day = parseInt(parts[0], 10);
    const month = parseInt(parts[1], 10);
    const year = parseInt(parts[2], 10);
    
    if (isNaN(day) || isNaN(month) || isNaN(year)) return null;
    if (month < 1 || month > 12) return null;
    if (day < 1 || day > 31) return null;
    
    return new Date(year, month - 1, day);
}

function normalizeToepassing(value) {
    if (value == null) return '';
    const s = String(value).trim();

    // Alles wat 'NaN' / 'None' / leeg is → behandelen als "geen toepassing"
    if (!s || s.toLowerCase() === 'nan' || s.toLowerCase() === 'none') {
        return '';
    }
    return s;
}


// === HOOFDFUNCTIE voor berekening (geeft werking, toepassing en naam terug) ===
function berekenWerkingscoefficient(n, meststof, perceel, gewas, datum) {
    // Basis validatie
    if (!n || isNaN(n)) n = 0;
    if (!meststof) {
        console.warn('Geen meststof opgegeven voor werkingscoëfficiënt berekening');
        return { effectieveN: 0, werking: null, toepassing: null, mappedNaam: null };
    }

    // === Als het géén dierlijke mest is: werking altijd 100% ===
    if (!meststof.toepassing || meststof.toepassing.toLowerCase() !== "dierlijke mest") {
        return { 
            effectieveN: n, 
            werking: 100, 
            toepassing: null, 
            mappedNaam: meststof.naam || null 
        };
    }

    // Als het WEL dierlijke mest is: bereken werkingscoëfficiënt
    const jsDate = parseDutchDate(datum);
    if (!jsDate) {
        console.warn('Ongeldige datum voor werkingscoëfficiënt:', datum);
        return { effectieveN: 0, werking: null, toepassing: null, mappedNaam: meststof.naam };
    }

    const jaar = jsDate.getFullYear();
    const maand = jsDate.getMonth() + 1;

    const mappedNaam = mapMeststofNaam(meststof.naam, meststof.eigen_bedrijf);
    const toepassing = bepaalToepassing(mappedNaam, gewas, perceel.grondsoort, maand);
    const normToepassing = normalizeToepassing(toepassing);


    console.log('Zoeken naar werkingscoëfficiënt:', {
        jaar,
        mappedNaam,
        toepassing,
        beschikbaar: window.werkingscoefficienten?.length || 0
    });

    // Zoek in werkingscoëfficiënten
    if (!window.werkingscoefficienten || !Array.isArray(window.werkingscoefficienten)) {
        console.warn('Werkingscoëfficiënten niet beschikbaar');
        return { effectieveN: 0, werking: null, toepassing, mappedNaam };
    }

    // === Zoek in werkingscoëfficiënten ===

    // 1) Exacte match: jaar + meststof + toepassing
    let entry = window.werkingscoefficienten.find(w =>
        String(w.jaar) === String(jaar) &&
        w.meststof === mappedNaam &&
        normalizeToepassing(w.toepassing) === normToepassing
    );

    // 2) Geen exacte match → probeer zelfde jaar + meststof maar ZONDER toepassing
    if (!entry) {
        entry = window.werkingscoefficienten.find(w =>
            String(w.jaar) === String(jaar) &&
            w.meststof === mappedNaam &&
            normalizeToepassing(w.toepassing) === ''
        );
    }

    // 3) Nog steeds niets → probeer andere jaren met dezelfde meststof + toepassing
    if (!entry) {
        entry = window.werkingscoefficienten.find(w =>
            w.meststof === mappedNaam &&
            normalizeToepassing(w.toepassing) === normToepassing
        );
    }


    if (!entry) {
        console.warn("⚠️ Geen werkingscoëfficiënt gevonden voor:", {
            jaar,
            mappedNaam, 
            toepassing: normToepassing || "(geen toepassing)",
            beschikbareCoeff: window.werkingscoefficienten.map(w =>
                `${w.jaar}-${w.meststof}-${normalizeToepassing(w.toepassing) || 'geen'}`
            )
        });
        return { effectieveN: 0, werking: null, toepassing, mappedNaam };
    }


    const werking = parseFloat(entry.werking) || 0;
    const effectieveN = n * werking / 100;

    console.log('Werkingscoëfficiënt gevonden:', {
        werking: werking + '%',
        effectieveN: effectieveN.toFixed(2) + ' kg/ha'
    });

    return {
        effectieveN,
        werking,
        toepassing,
        mappedNaam
    };
}

// === Simpele variant voor alleen berekende waarde (voor backward compatibility) ===
window.getEffectieveN = function(n, meststof, perceel, gewas, datum) {
    return berekenWerkingscoefficient(n, meststof, perceel, gewas, datum).effectieveN;
};

// === Export functies naar global scope ===
window.mapMeststofNaam = mapMeststofNaam;
window.bepaalToepassing = bepaalToepassing;
window.berekenWerkingscoefficient = berekenWerkingscoefficient;

console.log('Werkingscoëfficiënten utilities geladen');

// === Export voor module systemen (indien beschikbaar) ===
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { 
        mapMeststofNaam, 
        bepaalToepassing, 
        berekenWerkingscoefficient 
    };
}