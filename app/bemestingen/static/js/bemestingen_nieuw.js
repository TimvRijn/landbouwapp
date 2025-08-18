// app/static/js/bemestingen_nieuw.js
document.addEventListener('DOMContentLoaded', function () {
    // ===== DATA ophalen =====
    const gebruiksnormen = window.gebruiksnormen || [];
    const bedrijven = window.bedrijven || [];
    const percelen = window.percelen || [];
    const meststoffen = window.meststoffen || [];
    window.werkingscoefficienten = [];

    // Werkingscoëfficiënten ophalen (API uit blueprint)
    fetch('/bemestingen/api/werkingscoefficienten')
        .then(res => res.json())
        .then(data => { 
            window.werkingscoefficienten = data || []; 
            console.log('Werkingscoëfficiënten geladen:', window.werkingscoefficienten.length);
        })
        .catch(err => {
            console.error('Fout bij laden werkingscoëfficiënten:', err);
            window.werkingscoefficienten = [];
        });

    // ===== Choices.js =====
    const jaarChoices = new Choices('#jaar', { 
        searchEnabled: false, 
        shouldSort: false, 
        itemSelectText: '', 
        position: 'auto' 
    });

    let bedrijfChoices = new Choices('#bedrijf_id_select', {
        searchEnabled: true,
        shouldSort: false,
        itemSelectText: '',
        position: 'auto',
        removeItemButton: false
    });

    // Start met 'Kies bedrijf'
    bedrijfChoices.setChoices([{ value: '', label: 'Kies bedrijf', selected: true, disabled: true }], 'value', 'label', true);

    // ===== Datepicker =====
    flatpickr("#datum_bemesting", { 
        dateFormat: "d-m-Y", 
        locale: "nl",
        defaultDate: new Date()
    });

    // ===== Wizard Tabs =====
    const tabs = Array.from(document.querySelectorAll('.wizard-tab'));
    let currentTab = 0;

    function showTab(idx) {
        tabs.forEach((tab, i) => {
            tab.style.display = (i === idx) ? '' : 'none';
            tab.classList.toggle('active', i === idx);
        });
        currentTab = idx;
        if (idx === 2) {
            toggleHandmatigeNPKVelden();
            updateHandmatigeNPKEenheid();
            updateHandmatigeNPKFeedback();
        }
    }
    showTab(0);

    // ===== STAP 1: Jaar selectie handler =====
    document.getElementById('jaar').addEventListener('change', function () {
        const jaar = this.value;
        console.log('Jaar geselecteerd:', jaar);

        // Reset bedrijf selectie
        bedrijfChoices.clearStore();
        document.getElementById('bedrijf_id_select').value = '';

        if (!jaar) {
            bedrijfChoices.setChoices([{ value: '', label: 'Kies bedrijf', selected: true, disabled: true }], 'value', 'label', true);
            renderPercelenCheckboxes();
            return;
        }

        // Alle bedrijf_ids die in gebruiksnormen voor dit jaar voorkomen
        const bedrijfIds = new Set(
            gebruiksnormen
                .filter(g => String(g.jaar) === String(jaar))
                .map(g => String(g.bedrijf_id))
        );

        console.log('Beschikbare bedrijf IDs voor jaar', jaar, ':', Array.from(bedrijfIds));

        // Bouw nieuwe keuzelijst
        const nieuweOpties = [
            { value: '', label: 'Kies bedrijf', selected: true, disabled: true },
            ...bedrijven
                .filter(b => bedrijfIds.has(String(b.id)))
                .map(b => ({ value: String(b.id), label: b.naam }))
        ];

        console.log('Nieuwe bedrijf opties:', nieuweOpties);

        // Reset en vul nieuwe opties
        bedrijfChoices.setChoices(nieuweOpties, 'value', 'label', true);

        // Render percelen (zal leeg zijn omdat geen bedrijf geselecteerd)
        renderPercelenCheckboxes();
    });

    // ===== STAP 1: Bedrijf selectie handler =====
    document.getElementById('bedrijf_id_select').addEventListener('change', function() {
        console.log('Bedrijf geselecteerd:', this.value);
        renderPercelenCheckboxes();
    });

    // ===== STAP 1: Percelen rendering =====
    function renderPercelenCheckboxes() {
        const jaar = document.getElementById('jaar').value;
        const bedrijf_id = document.getElementById('bedrijf_id_select').value;
        const lijstDiv = document.getElementById('percelenCheckboxList');
        const emptyMsg = document.getElementById('perceel-empty-msg');

        console.log('Rendering percelen voor jaar:', jaar, 'bedrijf:', bedrijf_id);

        if (!jaar || !bedrijf_id) {
            lijstDiv.innerHTML = "";
            emptyMsg.style.display = "block";
            updatePercelenCount();
            return;
        }

        // Filter gebruiksnormen voor dit jaar en bedrijf
        const norms = gebruiksnormen.filter(g =>
            String(g.jaar) === String(jaar) && String(g.bedrijf_id) === String(bedrijf_id)
        );

        console.log('Gevonden gebruiksnormen:', norms.length);

        // Maak mapping van perceel_id naar norm info
        let perceelIdToInfo = {};
        norms.forEach(g => {
            perceelIdToInfo[g.perceel_id] = {
                norm_id: g.id,
                gewas: g.gewas,
                oppervlakte: g.oppervlakte
            };
        });

        // Haal perceel details op en combineer met norm info
        let filteredPercelen = Object.keys(perceelIdToInfo).map(pid => {
            const p = percelen.find(pp => String(pp.id) === String(pid));
            return {
                id: pid,
                naam: p ? p.naam : 'Perceel ' + pid,
                gewas: perceelIdToInfo[pid].gewas,
                oppervlakte: perceelIdToInfo[pid].oppervlakte,
                norm_id: perceelIdToInfo[pid].norm_id,
                grondsoort: p ? p.grondsoort : 'Onbekend'
            };
        });

        filteredPercelen.sort((a, b) => a.naam.localeCompare(b.naam));

        console.log('Gefilterde percelen:', filteredPercelen);

        if (filteredPercelen.length === 0) {
            lijstDiv.innerHTML = "";
            emptyMsg.style.display = "block";
            updatePercelenCount();
            return;
        }

        // Render checkboxes
        lijstDiv.innerHTML = filteredPercelen.map(p =>
            `<label class="perc-checkbox-label">
                <input type="checkbox" class="perc-checkbox" value="${p.id}"
                    data-ha="${p.oppervlakte}"
                    data-naam="${p.naam}"
                    data-gewas="${p.gewas}"
                    data-norm="${p.norm_id}"
                    data-grondsoort="${p.grondsoort}"
                    onchange="onPercelenSelectChanged()" />
                <span>
                    <b>${p.naam}</b>
                    <span class="perceel-extra">${p.gewas}, ${Number(p.oppervlakte).toFixed(2)} ha</span>
                </span>
            </label>`
        ).join('');

        emptyMsg.style.display = "none";
        updatePercelenCount();
    }

    // Initial render (leeg)
    renderPercelenCheckboxes();

    // ===== Percelen zoeken =====
    document.getElementById('searchPercelen').addEventListener('input', function () {
        const q = this.value.trim().toLowerCase();
        document.querySelectorAll('.perc-checkbox-label').forEach(label => {
            const text = label.innerText.toLowerCase();
            label.style.display = (!q || text.includes(q)) ? '' : 'none';
        });
    });

    // ===== Percelen selectie handlers =====
    window.onPercelenSelectChanged = function () {
        updatePercelenCount();
        updateHandmatigeNPKFeedback();
    };

    function updatePercelenCount() {
        const checked = Array.from(document.querySelectorAll('.perc-checkbox:checked'));
        let total = checked.length;
        let totalHa = checked.reduce((sum, cb) => sum + parseFloat(cb.getAttribute('data-ha') || 0), 0);
        
        document.getElementById('selectedCount').innerText =
            total + (total === 1 ? ' perceel geselecteerd – ' : ' percelen geselecteerd – ') +
            (isFinite(totalHa) ? totalHa.toFixed(2) : '0.00') + ' ha';

        const overview = document.getElementById('selectedOverview');
        const list = document.getElementById('selectedList');
        const totalHaSpan = document.getElementById('selectedTotalHa');

        if (total > 0) {
            overview.style.display = 'block';
            list.innerHTML = checked.map(cb =>
                `<li><b>${cb.getAttribute('data-naam')}</b> (${cb.getAttribute('data-gewas')}) – ${parseFloat(cb.getAttribute('data-ha') || 0).toFixed(2)} ha</li>`
            ).join('');
            totalHaSpan.innerText = totalHa.toFixed(2);
        } else {
            overview.style.display = 'none';
            list.innerHTML = '';
            totalHaSpan.innerText = '0.00';
        }
    }

    // ===== STAP 2: Meststof autocomplete =====
    const input = document.getElementById('meststof_autocomplete');
    const hidden = document.getElementById('meststof_id');
    const lijst = document.getElementById('meststof_suggesties');
    const meststofPercInfo = document.getElementById('meststofPercInfo');

    input.addEventListener('input', function () {
        const val = this.value.trim().toLowerCase();
        lijst.innerHTML = "";
        hidden.value = "";
        meststofPercInfo.style.display = "none";
        
        if (!val) {
            lijst.style.display = "none";
            return;
        }
        
        const matches = meststoffen.filter(m => (m.naam || '').toLowerCase().includes(val));
        if (!matches.length) {
            lijst.style.display = "none";
            return;
        }
        
        lijst.innerHTML = matches.map(m => `
            <li data-id="${m.id}" data-naam="${m.naam}" data-n="${m.n}" data-p2o5="${m.p2o5}" data-k2o="${m.k2o}" data-toepassing="${m.toepassing || ''}">
                ${m.naam}
            </li>
        `).join('');
        
        lijst.style.display = "block";
    });

    // Meststof selectie handler
    lijst.addEventListener('click', function(e) {
        if (e.target.tagName === 'LI') {
            const li = e.target;
            const meststof = {
                id: li.getAttribute('data-id'),
                naam: li.getAttribute('data-naam'),
                n: parseFloat(li.getAttribute('data-n')) || 0,
                p2o5: parseFloat(li.getAttribute('data-p2o5')) || 0,
                k2o: parseFloat(li.getAttribute('data-k2o')) || 0,
                toepassing: li.getAttribute('data-toepassing') || ''
            };
            
            input.value = meststof.naam;
            hidden.value = meststof.id;
            lijst.style.display = "none";
            showMeststofPerc(meststof);
            meststofKeuzeHook();
        }
    });

    input.addEventListener('focus', function () {
        if (this.value) {
            this.dispatchEvent(new Event('input'));
        }
    });

    input.addEventListener('blur', function () {
        setTimeout(() => lijst.style.display = "none", 200);
    });

    function showMeststofPerc(m) {
        if (m.toepassing && m.toepassing.toLowerCase() === "dierlijke mest") {
            meststofPercInfo.innerHTML = "Dierlijke mest – vul N, P₂O₅ en K₂O handmatig in";
        } else {
            meststofPercInfo.innerHTML =
                `Stikstof (N): <b>${m.n}%</b> – Fosfaat (P₂O₅): <b>${m.p2o5}%</b> – Kalium (K₂O): <b>${m.k2o}%</b>`;
        }
        meststofPercInfo.style.display = "block";
    }

    // ===== STAP 3: Details en berekeningen =====
    const radioKgHa = document.getElementById('type_ha');
    const radioKgTot = document.getElementById('type_tot');
    const divHa = document.getElementById('hoeveelheid_kg_ha_wrap');
    const divTot = document.getElementById('hoeveelheid_kg_totaal_wrap');
    const inputTot = document.getElementById('hoeveelheid_kg_totaal');
    const inputHa = document.getElementById('hoeveelheid_kg_ha');
    const haError = document.getElementById('haError');
    const kgTotaalError = document.getElementById('kgTotaalError');
    const kgPerHaShow = document.getElementById('kgPerHaShow');
    const infoTot = document.getElementById('totaalOppervlakteInfo');
    const datumInput = document.getElementById('datum_bemesting');
    const datumError = document.getElementById('datumError');

    // NPK invoer elementen
    const nInvoer = document.getElementById('n_invoer');
    const pInvoer = document.getElementById('p2o5_invoer');
    const kInvoer = document.getElementById('k2o_invoer');
    const nEenheidTxt = document.getElementById('n_eenheid_txt');
    const pEenheidTxt = document.getElementById('p2o5_eenheid_txt');
    const kEenheidTxt = document.getElementById('k2o_eenheid_txt');
    const nPerHaRes = document.getElementById('n_per_ha_result');
    const pPerHaRes = document.getElementById('p2o5_per_ha_result');
    const kPerHaRes = document.getElementById('k2o_per_ha_result');

    function getSelectedTotalHa() {
        return Array.from(document.querySelectorAll('.perc-checkbox:checked'))
            .reduce((sum, cb) => sum + parseFloat(cb.getAttribute('data-ha') || 0), 0);
    }

    function updateHoeveelheidTypeCards() {
        document.getElementById('lbl_ha').classList.toggle('selected', radioKgHa.checked);
        document.getElementById('lbl_tot').classList.toggle('selected', radioKgTot.checked);
    }

    // Radio button handlers
    radioKgHa.addEventListener('change', () => {
        if (radioKgHa.checked) {
            divHa.style.display = 'block';
            divTot.style.display = 'none';
            inputHa.required = true;
            inputTot.required = false;
            haError.style.display = 'none';
        }
        updateHoeveelheidTypeCards();
        updateHandmatigeNPKEenheid();
        updateHandmatigeNPKFeedback();
        calcAndShowNutrients();
    });

    radioKgTot.addEventListener('change', () => {
        if (radioKgTot.checked) {
            divHa.style.display = 'none';
            divTot.style.display = 'block';
            inputHa.required = false;
            inputTot.required = true;
            infoTot.innerHTML = (getSelectedTotalHa() || 0).toFixed(2);
            kgTotaalError.style.display = 'none';
        }
        updateHoeveelheidTypeCards();
        updateHandmatigeNPKEenheid();
        updateHandmatigeNPKFeedback();
        updateKgPerHaShow();
        calcAndShowNutrients();
    });

    updateHoeveelheidTypeCards();

    function updateKgPerHaShow() {
        const kgTotaal = parseFloat(inputTot.value) || 0;
        const opp = getSelectedTotalHa();
        if (kgTotaal > 0 && opp > 0) {
            const result = kgTotaal / opp;
            kgPerHaShow.style.display = 'block';
            kgPerHaShow.innerHTML = 'Dat is <b>' + result.toFixed(2) + ' kg/ha</b>';
        } else {
            kgPerHaShow.style.display = 'none';
            kgPerHaShow.innerHTML = '';
        }
    }

    function updateHandmatigeNPKFeedback() {
        const opp = getSelectedTotalHa();
        if (meststofIsDierlijk() && radioKgTot.checked && opp > 0) {
            const n = parseFloat(nInvoer.value) || 0;
            nPerHaRes.innerHTML = (n !== 0) ? `Dat is <b>${(n/opp).toFixed(2)} kg/ha</b>` : '';
            const p = parseFloat(pInvoer.value) || 0;
            pPerHaRes.innerHTML = (p !== 0) ? `Dat is <b>${(p/opp).toFixed(2)} kg/ha</b>` : '';
            const k = parseFloat(kInvoer.value) || 0;
            kPerHaRes.innerHTML = (k !== 0) ? `Dat is <b>${(k/opp).toFixed(2)} kg/ha</b>` : '';
        } else {
            nPerHaRes.innerHTML = '';
            pPerHaRes.innerHTML = '';
            kPerHaRes.innerHTML = '';
        }
    }

    function updateHandmatigeNPKEenheid() {
        const eenheid = radioKgHa.checked ? "kg/ha" : "kg totaal";
        nEenheidTxt.textContent = eenheid;
        pEenheidTxt.textContent = eenheid;
        kEenheidTxt.textContent = eenheid;
    }

    // Input event listeners
    inputTot.addEventListener('input', function () {
        updateKgPerHaShow();
        updateHandmatigeNPKFeedback();
        calcAndShowNutrients();
    });
    
    inputHa.addEventListener('input', function () {
        updateHandmatigeNPKFeedback();
        calcAndShowNutrients();
    });

    ['n_invoer', 'p2o5_invoer', 'k2o_invoer'].forEach(id => {
        const element = document.getElementById(id);
        if (element) {
            element.addEventListener('input', function () {
                updateHandmatigeNPKFeedback();
                calcAndShowNutrients();
            });
        }
    });

    // Helper functions
    function meststofIsDierlijk() {
        const meststof = getSelectedMeststof();
        return meststof && meststof.toepassing && meststof.toepassing.toLowerCase() === "dierlijke mest";
    }

    function toggleHandmatigeNPKVelden() {
        const handmatigDiv = document.getElementById('handmatig_npk');
        if (handmatigDiv) {
            handmatigDiv.style.display = meststofIsDierlijk() ? 'block' : 'none';
        }
    }

    function meststofKeuzeHook() {
        const meststof = getSelectedMeststof();
        if (meststof) {
            showMeststofPerc(meststof);
        }
        toggleHandmatigeNPKVelden();
        updateHandmatigeNPKEenheid();
        updateHandmatigeNPKFeedback();
        calcAndShowNutrients();
    }

    function getSelectedMeststof() {
        const meststof_id = document.getElementById('meststof_id').value;
        return meststoffen.find(m => String(m.id) === String(meststof_id));
    }

    function calcAndShowNutrients() {
        const meststof = getSelectedMeststof();
        let hoeveelheid = 0;
        let n = 0, p2o5 = 0, k2o = 0;
        const opp = getSelectedTotalHa() || 1;

        if (meststofIsDierlijk()) {
            // Dierlijke mest: handmatige NPK invoer
            if (radioKgHa.checked) {
                n = parseFloat(nInvoer.value) || 0;
                p2o5 = parseFloat(pInvoer.value) || 0;
                k2o = parseFloat(kInvoer.value) || 0;
            } else {
                // kg totaal -> omrekenen naar kg/ha
                n = (parseFloat(nInvoer.value) || 0) / opp;
                p2o5 = (parseFloat(pInvoer.value) || 0) / opp;
                k2o = (parseFloat(kInvoer.value) || 0) / opp;
            }
        } else {
            // Kunstmest: berekenen op basis van percentages
            if (radioKgHa.checked) {
                hoeveelheid = parseFloat(inputHa.value) || 0;
            } else if (radioKgTot.checked) {
                hoeveelheid = (parseFloat(inputTot.value) || 0) / opp;
            }
            
            if (meststof) {
                n = hoeveelheid * (parseFloat(meststof.n) || 0) / 100;
                p2o5 = hoeveelheid * (parseFloat(meststof.p2o5) || 0) / 100;
                k2o = hoeveelheid * (parseFloat(meststof.k2o) || 0) / 100;
            }
        }

        // Update hidden fields
        document.getElementById('n_kg_ha_hidden').value = n.toFixed(2);
        document.getElementById('p2o5_kg_ha_hidden').value = p2o5.toFixed(2);
        document.getElementById('k2o_kg_ha_hidden').value = k2o.toFixed(2);
    }

    // ===== Navigatie tussen tabs =====
    document.getElementById('toStep2').addEventListener('click', function () {
        const jaar = document.getElementById('jaar').value;
        const bedrijf = document.getElementById('bedrijf_id_select').value;
        const percelen = document.querySelectorAll('.perc-checkbox:checked');

        if (!jaar) {
            alert("Selecteer eerst een jaar.");
            document.getElementById('jaar').focus();
            return;
        }
        if (!bedrijf) {
            alert("Selecteer eerst een bedrijf.");
            return;
        }
        if (!percelen.length) {
            alert("Selecteer minimaal één perceel.");
            return;
        }

        document.getElementById('hidden_bedrijf_id').value = bedrijf;
        showTab(1);
    });

    document.getElementById('backTo1').addEventListener('click', function () { 
        showTab(0); 
    });

    document.getElementById('toStep3').addEventListener('click', function () {
        if (!document.getElementById('meststof_id').value) {
            alert("Kies eerst een meststof.");
            document.getElementById('meststof_autocomplete').focus();
            return;
        }
        showTab(2);
        toggleHandmatigeNPKVelden();
        updateHandmatigeNPKEenheid();
        updateHandmatigeNPKFeedback();
    });

    document.getElementById('backTo2').addEventListener('click', function () { 
        showTab(1); 
    });

    document.getElementById('toStep4').addEventListener('click', function () {
        // Reset error states
        haError.style.display = 'none';
        kgTotaalError.style.display = 'none';
        datumError.style.display = 'none';
        let error = false;

        // Valideer datum
        if (!datumInput.value) {
            datumError.style.display = 'block';
            datumError.innerText = "Vul een datum in.";
            datumInput.focus();
            error = true;
        }

        // Valideer hoeveelheid
        if (radioKgHa.checked) {
            const ha = parseFloat(inputHa.value);
            if (!ha || ha <= 0) {
                haError.style.display = 'block';
                haError.innerText = "Vul een geldige hoeveelheid per ha in.";
                inputHa.focus();
                error = true;
            }
        } else if (radioKgTot.checked) {
            const kgTotaal = parseFloat(inputTot.value);
            const oppervlakte = getSelectedTotalHa();
            if (!kgTotaal || kgTotaal <= 0) {
                kgTotaalError.style.display = 'block';
                kgTotaalError.innerText = "Vul een geldige totale hoeveelheid in.";
                inputTot.focus();
                error = true;
            } else if (oppervlakte <= 0) {
                kgTotaalError.style.display = 'block';
                kgTotaalError.innerText = "Geen geldige oppervlakte geselecteerd.";
                error = true;
            } else {
                // Backfill kg/ha voor overzicht en server
                const kgPerHa = kgTotaal / oppervlakte;
                inputHa.value = kgPerHa.toFixed(2);
            }
        }

        if (error) return;
        
        fillOverzichtTab();
        showTab(3);
    });

    document.getElementById('backTo3').addEventListener('click', function () { 
        showTab(2); 
    });

    // ===== Helper functies =====
    function parseDutchDateToJSDate(ddmmyyyy) {
        const parts = (ddmmyyyy || '').split('-');
        if (parts.length !== 3) return null;
        const d = parseInt(parts[0], 10);
        const m = parseInt(parts[1], 10);
        const y = parseInt(parts[2], 10);
        if (!d || !m || !y) return null;
        return new Date(y, m - 1, d);
    }

    // ===== Overzicht tab vulling =====
    function fillOverzichtTab() {
        const meststof = getSelectedMeststof();
        const isEigenBedrijf = document.getElementById('eigen_bedrijf_checkbox').checked;

        // Basis info
        document.getElementById('ovz_meststof').innerText = meststof ? meststof.naam : '';
        document.getElementById('ovz_datum').innerText = datumInput.value;
        document.getElementById('ovz_kg_ha').innerText = Number(inputHa.value || 0).toFixed(2);

        // Bereken en toon NPK
        calcAndShowNutrients();
        document.getElementById('ovz_n_kg_ha').innerText = document.getElementById('n_kg_ha_hidden').value;
        document.getElementById('ovz_p2o5_kg_ha').innerText = document.getElementById('p2o5_kg_ha_hidden').value;
        document.getElementById('ovz_k2o_kg_ha').innerText = document.getElementById('k2o_kg_ha_hidden').value;

        // Jaar en bedrijf info
        const jaar = document.getElementById('jaar').value;
        const bedrijfId = document.getElementById('bedrijf_id_select').value;
        const bedrijf = bedrijven.find(b => String(b.id) === String(bedrijfId));
        document.getElementById('ovz_jaren').innerText = jaar;
        document.getElementById('ovz_bedrijf').innerText = bedrijf ? bedrijf.naam : "";

        // Percelen info
        const selectedPercelen = Array.from(document.querySelectorAll('.perc-checkbox:checked'));
        const perceelNamen = selectedPercelen.map(cb => cb.getAttribute('data-naam'));
        document.getElementById('ovz_percelen').innerText = perceelNamen.join(', ');

        // Herkomst
        document.getElementById('ovz_herkomst').innerText = isEigenBedrijf ? 'Eigen bedrijf' : 'Aangevoerd';

        // Effectieve N berekening
        const kgNperHa = parseFloat(document.getElementById('n_kg_ha_hidden').value) || 0;
        const datum = datumInput.value;
        const jsDate = parseDutchDateToJSDate(datum);
        const maand = jsDate ? (jsDate.getMonth() + 1) : null;

        let totalEffN = 0;
        let nCards = 0;

        // Genereer cards per perceel
        const cardsHTML = selectedPercelen.map(cb => {
            const naam = cb.getAttribute('data-naam') || '';
            const oppervlakte = parseFloat(cb.getAttribute('data-ha')) || 0;
            const gewas = cb.getAttribute('data-gewas') || '';
            const grondsoort = cb.getAttribute('data-grondsoort') || '';

            let effectieveN = kgNperHa;
            let werking = 100;
            let toepassing = '';
            let mappedNaam = meststof?.naam || '';

            // Alleen voor dierlijke mest: werkingscoëfficiënt berekenen
            if (window.berekenWerkingscoefficient && meststof && meststof.toepassing && 
                meststof.toepassing.toLowerCase() === 'dierlijke mest') {
                const perceel = { grondsoort };
                const berekening = window.berekenWerkingscoefficient(
                    kgNperHa,
                    { ...meststof, eigen_bedrijf: isEigenBedrijf },
                    perceel,
                    gewas,
                    datum
                );
                effectieveN = berekening.effectieveN || 0;
                werking = berekening.werking;
                toepassing = berekening.toepassing || '';
                mappedNaam = berekening.mappedNaam || meststof.naam;
            }

            totalEffN += effectieveN;
            nCards++;

            return `
                <div class="nutrient-card">
                    <div><span class="nutrient-label">Perceel:</span> <span class="nutrient-value">${naam}</span></div>
                    <div><span class="nutrient-label">Oppervlakte:</span> <span class="nutrient-value">${oppervlakte.toFixed(2)} ha</span></div>
                    <div><span class="nutrient-label">Grondsoort:</span> <span class="nutrient-value">${grondsoort}</span></div>
                    <div><span class="nutrient-label">Gewas:</span> <span class="nutrient-value">${gewas}</span></div>
                    <div><span class="nutrient-label">Meststofnaam:</span> <span class="nutrient-value">${mappedNaam}</span></div>
                    <div><span class="nutrient-label">Toepassing:</span> <span class="nutrient-value">${toepassing || '-'}</span></div>
                    <div><span class="nutrient-label">Werkingscoëfficiënt:</span> <span class="nutrient-value">${(werking !== null && werking !== undefined) ? werking.toFixed(1) + "%" : '–'}</span></div>
                    <div><span class="nutrient-label">Effectieve N:</span> <span class="nutrient-value">${effectieveN.toFixed(2)} kg/ha</span></div>
                </div>
            `;
        }).join('');

        document.getElementById('effectieveN_perceel_cards_container').innerHTML = cardsHTML;
        document.getElementById('ovz_effectieve_n').innerText = nCards ? (totalEffN / nCards).toFixed(2) : '-';
    }

    // ===== Form submit: norm-ids toevoegen =====
    document.getElementById('wizardForm').addEventListener('submit', function (e) {
        // Verwijder oude hidden inputs
        document.querySelectorAll('input[name="gebruiksnorm_ids[]"]').forEach(el => el.remove());

        const checked = Array.from(document.querySelectorAll('.perc-checkbox:checked'));
        let errors = [];

        // Voeg hidden inputs toe voor elke geselecteerde gebruiksnorm
        checked.forEach(cb => {
            const norm_id = cb.getAttribute('data-norm');
            if (norm_id) {
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'gebruiksnorm_ids[]';
                input.value = norm_id;
                this.appendChild(input);
            } else {
                errors.push(cb.getAttribute('data-naam') || cb.value);
            }
        });

        if (errors.length > 0) {
            alert(`Let op: voor de volgende percelen ontbreekt een gebruiksnorm: ${errors.join(', ')}. Controleer je data.`);
            e.preventDefault();
            showTab(0);
            return false;
        }

        // Zorg dat NPK waarden up-to-date zijn
        calcAndShowNutrients();
        
        console.log('Form wordt verzonden met NPK waarden:', {
            n: document.getElementById('n_kg_ha_hidden').value,
            p2o5: document.getElementById('p2o5_kg_ha_hidden').value,
            k2o: document.getElementById('k2o_kg_ha_hidden').value
        });

        return true;
    });

    // ===== Perceel selectie change listener =====
    document.addEventListener('change', function(e) {
        if (e.target.classList.contains('perc-checkbox')) {
            const totalOpp = getSelectedTotalHa();
            infoTot.innerHTML = totalOpp.toFixed(2);
            updateKgPerHaShow();
            updateHandmatigeNPKFeedback();
            calcAndShowNutrients();
        }
    });

    // ===== Export functies voor global scope =====
    window.mapMeststofNaam = window.mapMeststofNaam || function(naam, eigen) {
        // Fallback implementatie als werkingscoefficienten_utils.js niet geladen is
        return naam;
    };

    window.bepaalToepassing = window.bepaalToepassing || function(mappedNaam, gewas, grondsoort, maand) {
        // Fallback implementatie
        return '';
    };

    window.berekenWerkingscoefficient = window.berekenWerkingscoefficient || function(n, meststof, perceel, gewas, datum) {
        // Fallback implementatie: geen werkingscoëfficiënt, gewoon 100% effectiviteit
        return {
            effectieveN: n,
            werking: 100,
            toepassing: '',
            mappedNaam: meststof?.naam || ''
        };
    };

    console.log('Bemestingen nieuw script geladen');
});
                