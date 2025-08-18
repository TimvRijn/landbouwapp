/* =========================================================================
 * FilterManager – herbruikbare filterlogica met Choices.js, chips, stats & CSV
 * + Collapsible filter card (naadloos met de CSS)
 * ========================================================================= */
(function (global) {
  class FilterManager {
    /**
     * @param {Object} options
     * @param {string} options.gridSelector               - container van cards
     * @param {string} options.cardSelector               - selector voor kaartjes
     * @param {Array}  options.selects                    - [{id, label, type: 'string'|'range', dataAttr, ranges?}]
     * @param {string} [options.chipContainer]            - selector voor chips container
     * @param {string} [options.filterSectionSelector]    - selector van filterkaart (voor stats + collapsible)
     * @param {string} [options.statsSelector]            - bestaand element om stats in te tonen (optioneel)
     * @param {boolean}[options.populateFromGrid=false]   - vul string-selects o.b.v. unieke waarden in grid
     * @param {string} [options.totalAttribute]           - data-* attribuut om op te sommeren (bijv. 'oppervlakte')
     * @param {Object} [options.choicesOptions]           - extra opties voor Choices
     * @param {Object} [options.exportFields]             - { 'data-attr': 'Kolom naam', ... }
     * @param {Function} [options.rowBuilder]             - (cardEl)=>object voor CSV; override default
     * @param {Function} [options.onAfterFilter]          - (visibleCards)=>void
     *
     * @param {Object} [options.collapsible]              - instellingen voor uitklapbare filterkaart
     *  - enabled: true                                   - aan/uit
     *  - defaultCollapsed: false                         - startstand
     *  - persist: true                                   - bewaar open/dicht in localStorage
     *  - storageKey: 'filters:collapsed:{path}'          - sleutel voor opslag
     *  - selectors: { header, title, toggle, body }      - subselectors (optioneel)
     *  - labels: { show: 'Toon filters', hide:'Verberg filters' }
     */
    constructor(options = {}) {
      this.opt = Object.assign({
        gridSelector: null,
        cardSelector: '.data-card',
        selects: [],
        chipContainer: null,
        filterSectionSelector: null,
        statsSelector: null,
        populateFromGrid: false,
        totalAttribute: null,
        choicesOptions: {},
        exportFields: null,
        rowBuilder: null,
        onAfterFilter: null,
        collapsible: {
          enabled: true,
          defaultCollapsed: false,
          persist: true,
          storageKey: null,
          selectors: {
            header: '.filter-header',
            title:  '.filter-title',
            toggle: '.filter-toggle',
            body:   '.filter-body'
          },
          labels: {
            show:  'Toon filters',
            hide:  'Verberg filters'
          }
        }
      }, options);

      this.grid = document.querySelector(this.opt.gridSelector);
      if (!this.grid) {
        console.error('FilterManager: gridSelector niet gevonden:', this.opt.gridSelector);
        return;
      }
      this.cards = Array.from(this.grid.querySelectorAll(this.opt.cardSelector));
      this.choicesInstances = {};
      this._statsEl = null;

      // Filter section resolve: expliciete selector > dichtstbijzijnde ouder
      this.section = this.opt.filterSectionSelector
        ? document.querySelector(this.opt.filterSectionSelector)
        : this.grid.closest('.filter-section');

      // Collapsible config (merge veilig)
      this._coll = Object.assign({}, this.opt.collapsible || {});
      this._coll.selectors = Object.assign({
        header: '.filter-header',
        title:  '.filter-title',
        toggle: '.filter-toggle',
        body:   '.filter-body'
      }, (this._coll.selectors || {}));
      this._coll.labels = Object.assign({
        show: 'Toon filters',
        hide: 'Verberg filters'
      }, (this._coll.labels || {}));

      // Storage key (per pagina)
      if (this._coll.persist && !this._coll.storageKey) {
        const path = (location && location.pathname) ? location.pathname : 'default';
        this._coll.storageKey = `filters:collapsed:${path}`;
      }
    }

    /* ------------------- PUBLIC ------------------- */
    init() {
      // Collapsible eerst opzetten, zodat layout meteen goed is
      this._setupCollapsible();

      // Init selects + eventueel vullen met opties
      this.opt.selects.forEach(conf => {
        const select = document.getElementById(conf.id);
        if (!select) return;

        if (this.opt.populateFromGrid && conf.type === 'string') {
          this._populateSelectFromGrid(select, conf.dataAttr);
        }
        // zorg dat er een lege "alle" optie is (als die er niet is)
        if (![...select.options].some(o => o.value === '')) {
          const opt = document.createElement('option');
          opt.value = '';
          opt.textContent = select.dataset.placeholder || 'Alle';
          select.insertBefore(opt, select.firstChild);
        }

        const inst = new Choices(select, Object.assign({
          searchEnabled: true,
          shouldSort: false,
          removeItemButton: true,
          placeholderValue: select.dataset.placeholder || 'Kies...',
          noResultsText: 'Geen resultaten gevonden',
          itemSelectText: ''
        }, this.opt.choicesOptions || {}));

        this.choicesInstances[conf.id] = inst;

        select.addEventListener('change', () => {
          this.applyFilters();
          this._updateFilterIndicators();
          this._renderChips();
        });
      });

      // Eerste render
      this.applyFilters();
      this._renderChips();
      this._updateFilterIndicators();
      this._ensureStatsEl();
      this._updateStats();

      // ESC: reset filters als er geen modals open zijn
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
          this.reset();
        }
      });
    }

    reset() {
      Object.entries(this.choicesInstances).forEach(([id, inst]) => {
        inst.removeActiveItems();
        inst.setChoiceByValue('');
      });
      // toon alles
      this.cards.forEach(card => card.style.display = '');
      this._hideNoResultsMessage();
      this._updateStats();
      this._updateFilterIndicators();
      this._renderChips();
    }

    applyFilters() {
      const activeFilters = this._getActiveFilterState();

      let visibleCount = 0;
      let total = 0;

      this.cards.forEach(card => {
        let show = true;

        for (const f of activeFilters) {
          const dv = card.dataset[this._dataKey(f.conf.dataAttr)];
          if (f.conf.type === 'string') {
            if (f.value && (dv ?? '') !== f.value) show = false;
          } else if (f.conf.type === 'range') {
            const num = parseFloat(dv);
            const match = f.range && isFinite(num) ? f.range.test(num) : true;
            if (!match) show = false;
          }
          if (!show) break;
        }

        if (show) {
          card.style.display = '';
          visibleCount++;
          if (this.opt.totalAttribute) {
            const t = parseFloat(card.dataset[this._dataKey(this.opt.totalAttribute)]);
            if (!isNaN(t)) total += t;
          }
        } else {
          card.style.display = 'none';
        }
      });

      this._updateStats(visibleCount, total);
      this._showNoResultsMessage(visibleCount);

      if (typeof this.opt.onAfterFilter === 'function') {
        const visibleCards = this.cards.filter(c => c.style.display !== 'none');
        this.opt.onAfterFilter(visibleCards);
      }
    }

    exportCSV(filename = 'export') {
      const visible = this.cards.filter(c => c.style.display !== 'none');
      if (visible.length === 0) {
        alert('Geen data om te exporteren. Pas je filters aan.');
        return;
      }

      let rows = [];
      if (typeof this.opt.rowBuilder === 'function') {
        rows = visible.map(card => this.opt.rowBuilder(card));
      } else {
        // standaard: verzamel datasets, gefilterd op exportFields (of alles)
        rows = visible.map(card => {
          const obj = {};
          const fields = this.opt.exportFields;
          if (fields) {
            Object.keys(fields).forEach(attr => {
              obj[fields[attr]] = card.dataset[this._dataKey(attr)] ?? '';
            });
          } else {
            // alle data-attrs (ruwer)
            Object.keys(card.dataset).forEach(k => {
              obj[k] = card.dataset[k];
            });
          }
          return obj;
        });
      }

      const csv = this._toCSV(rows);
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${filename}_${new Date().toISOString().split('T')[0]}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }

    /* ------------------- PRIVATE ------------------- */

    _setupCollapsible() {
      if (!this._coll.enabled || !this.section) return;

      // Vind of bouw header/toggle/body
      let header = this.section.querySelector(this._coll.selectors.header);
      let title  = this.section.querySelector(this._coll.selectors.title);
      let toggle = this.section.querySelector(this._coll.selectors.toggle);
      let body   = this.section.querySelector(this._coll.selectors.body);

      // Als er geen body-wrapper is, wrap de bestaande inhoud (behalve header) in .filter-body > .filter-body-inner
      if (!body) {
        body = document.createElement('div');
        body.className = 'filter-body';
        const inner = document.createElement('div');
        inner.className = 'filter-body-inner';

        // verplaats alles behalve bestaande header naar inner
        const children = Array.from(this.section.children);
        children.forEach(ch => {
          if (ch === header) return;
          if (ch === body) return;
          inner.appendChild(ch);
        });
        body.appendChild(inner);
        this.section.appendChild(body);
      } else {
        // zorg dat inner bestaat
        if (!body.querySelector('.filter-body-inner')) {
          const inner = document.createElement('div');
          inner.className = 'filter-body-inner';
          while (body.firstChild) inner.appendChild(body.firstChild);
          body.appendChild(inner);
        }
      }

      // Als er geen header is, maak er één
      if (!header) {
        header = document.createElement('div');
        header.className = 'filter-header';
        // Plaats bovenaan section
        this.section.insertBefore(header, this.section.firstChild);
      }

      // Titel?
      if (!title) {
        title = document.createElement('h3');
        title.className = 'filter-title';
        title.textContent = '🔍 Filter';
        header.appendChild(title);
      }

      // Toggle?
      if (!toggle) {
        toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'filter-toggle';
        toggle.innerHTML = `<span class="label"></span><span class="caret" aria-hidden="true"></span>`;
        header.appendChild(toggle);
      }

      // ID + ARIA
      if (!body.id) body.id = `filter-body-${Math.random().toString(36).slice(2, 8)}`;
      toggle.setAttribute('aria-controls', body.id);
      toggle.setAttribute('aria-expanded', 'true'); // init; wordt direct gezet op basis van state

      // Lees persistente staat
      const collapsedStored = this._coll.persist ? this._readCollapsedState() : null;
      const startCollapsed = (collapsedStored != null) ? collapsedStored : !!this._coll.defaultCollapsed;
      this._setCollapsed(startCollapsed, { announce: false, skipPersist: true });

      // Click handler
      toggle.addEventListener('click', () => {
        const willCollapse = !this.section.classList.contains('is-collapsed');
        this._setCollapsed(willCollapse);
      });

      // Toetsenbord: Enter/Space gelijk aan click
      toggle.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          toggle.click();
        }
      });

      // Expose voor devs
      this.collapse = (bool) => this._setCollapsed(!!bool);
      this.expand   = () => this._setCollapsed(false);
      this.isCollapsed = () => this.section.classList.contains('is-collapsed');
    }

    _setCollapsed(collapse, opts = {}) {
      if (!this.section) return;
      const toggle = this.section.querySelector(this._coll.selectors.toggle);
      const label  = toggle?.querySelector('.label');

      // Class togglen
      this.section.classList.toggle('is-collapsed', collapse);

      // ARIA + label
      if (toggle) toggle.setAttribute('aria-expanded', (!collapse).toString());
      if (label)  label.textContent = collapse ? this._coll.labels.show : this._coll.labels.hide;

      // Persist
      if (this._coll.persist && !opts.skipPersist) {
        try { localStorage.setItem(this._coll.storageKey, collapse ? '1' : '0'); } catch(e){}
      }

      // Kleine layout nudge als we uitklappen (voor Choices breedte/positie)
      if (!collapse) {
        setTimeout(() => {
          try { window.dispatchEvent(new Event('resize')); } catch(e){}
          // Focus eerste select (gebruikersvriendelijk)
          const firstSelect = this.section.querySelector('.filter-item select, .filter-item input, .choices__input');
          if (firstSelect && !opts.announce) firstSelect.focus({preventScroll:true});
        }, 180);
      }
    }

    _readCollapsedState() {
      try {
        const v = localStorage.getItem(this._coll.storageKey);
        if (v === '1') return true;
        if (v === '0') return false;
      } catch(e){}
      return null;
    }

    _populateSelectFromGrid(selectEl, dataAttr) {
      const key = this._dataKey(dataAttr);
      const set = new Set();
      this.cards.forEach(c => {
        const v = c.dataset[key];
        if (v && v !== 'undefined') set.add(v);
      });
      const values = Array.from(set).sort((a,b)=> String(a).localeCompare(String(b),'nl'));
      values.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v;
        opt.textContent = v;
        selectEl.appendChild(opt);
      });
    }

    _getActiveFilterState() {
      const state = [];
      this.opt.selects.forEach(conf => {
        const inst = this.choicesInstances[conf.id];
        const value = inst?.getValue?.(true) || '';
        if (!value) return;
        const f = { conf, value, range: null };

        if (conf.type === 'range' && Array.isArray(conf.ranges)) {
          const r = conf.ranges.find(r => r.label === value);
          if (r) f.range = r;
        }
        state.push(f);
      });
      return state;
    }

    _renderChips() {
      if (!this.opt.chipContainer) return;
      const mount = document.querySelector(this.opt.chipContainer);
      if (!mount) return;

      const entries = this.opt.selects.map(conf => {
        const value = this.choicesInstances[conf.id]?.getValue?.(true) || '';
        return { id: conf.id, key: conf.label, value };
      }).filter(e => e.value);

      if (entries.length === 0) {
        mount.innerHTML = '';
        return;
      }

      mount.innerHTML = entries.map(({id,key,value}) => `
        <span class="filter-chip" data-for="${id}">
          <span class="chip-key">${key}</span>
          <span class="chip-value">${value}</span>
          <button type="button" aria-label="Verwijder filter ${key}" title="Verwijder">✕</button>
        </span>
      `).join('');

      mount.querySelectorAll('.filter-chip button').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const chip = e.currentTarget.closest('.filter-chip');
          const selectId = chip?.dataset.for;
          const inst = this.choicesInstances[selectId];
          if (inst) {
            inst.removeActiveItems();
            inst.setChoiceByValue('');
          }
          this.applyFilters();
          this._updateFilterIndicators();
          this._renderChips();
        });
      });
    }

    _updateFilterIndicators() {
      this.opt.selects.forEach(conf => {
        const el = document.getElementById(conf.id);
        if (!el) return;
        const hasVal = !!(this.choicesInstances[conf.id]?.getValue?.(true));
        const wrap = el.closest('.filter-item');
        if (!wrap) return;
        wrap.classList.toggle('filter-active', hasVal);
      });
    }

    _ensureStatsEl() {
      if (this.opt.statsSelector) {
        this._statsEl = document.querySelector(this.opt.statsSelector);
        if (this._statsEl) return;
      }
      // zo niet: maak er eentje direct onder filter-section
      const host = this.section || (this.opt.filterSectionSelector ? document.querySelector(this.opt.filterSectionSelector) : null);
      if (host && host.parentNode) {
        const div = document.createElement('div');
        div.className = 'stats-summary';
        host.parentNode.insertBefore(div, host.nextSibling);
        this._statsEl = div;
      }
    }

    _updateStats(count = null, total = 0) {
      if (!this._statsEl) return;

      if (count === null) {
        const visible = this.cards.filter(c => c.style.display !== 'none');
        count = visible.length;
        if (this.opt.totalAttribute) {
          total = visible.reduce((acc, c) => {
            const v = parseFloat(c.dataset[this._dataKey(this.opt.totalAttribute)]);
            return acc + (isNaN(v) ? 0 : v);
          }, 0);
        }
      }

      const totalHtml = (this.opt.totalAttribute && total > 0)
        ? ` | Totale ${this.opt.totalAttribute}: <strong>${total.toFixed(2)}</strong>`
        : '';

      this._statsEl.innerHTML = `📊 <strong>${count}</strong> item${count===1?'':'s'} getoond${totalHtml}`;
    }

    _showNoResultsMessage(visibleCount) {
      if (visibleCount > 0) { this._hideNoResultsMessage(); return; }
      let msg = document.querySelector('.no-results-filter');
      if (!msg) {
        msg = document.createElement('div');
        msg.className = 'no-results-filter no-data';
        msg.innerHTML = `
          <h3>🔍 Geen resultaten gevonden</h3>
          <p>Er zijn geen items die voldoen aan de huidige filters.</p>
          <button type="button" class="action-btn" data-reset>🔄 Reset alle filters</button>
        `;
        const container = this.grid.parentElement || document.body;
        container.appendChild(msg);
        msg.querySelector('[data-reset]').addEventListener('click', ()=> this.reset());
      }
      msg.style.display = 'block';
      this.grid.style.display = 'none';
    }

    _hideNoResultsMessage() {
      const msg = document.querySelector('.no-results-filter');
      if (msg) msg.style.display = 'none';
      this.grid.style.display = 'grid';
    }

    _toCSV(data) {
      if (!data || data.length === 0) return '';
      const headers = Object.keys(data[0]);
      const rows = [headers.join(',')];
      data.forEach(row => {
        const values = headers.map(h => {
          const val = row[h] ?? '';
          const s = String(val);
          return (s.includes(',') || s.includes('"') || s.includes('\n'))
            ? `"${s.replace(/"/g, '""')}"`
            : s;
        });
        rows.push(values.join(','));
      });
      return rows.join('\n');
    }

    _dataKey(attr) {
      // van 'nv-gebied' naar dataset key 'nvGebied'
      return String(attr).replace(/-([a-z])/g, (_,c)=> c.toUpperCase());
    }
  }

  // Exporteer naar window
  global.FilterManager = FilterManager;

})(typeof window !== 'undefined' ? window : this);
