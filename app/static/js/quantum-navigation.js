/*
 * QuantumNavigation — robuuste inline/drawer navigatie met drop-up user-menu
 * v1.6.0 (incl. href-hydratie voor Flask routes + desktop/drawer scheiding + nav-offset helper)
 *
 * Gebruik:
 *  - Plaats je nav in HTML met id="quantumNav", een .quantum-nav-links UL en een button .quantum-mobile-btn of #quantumMobileBtn.
 *  - Roep window.setFlaskUrls({...}) aan (mag voor/na init); hrefs hydrateren automatisch zodra routes bekend zijn.
 *  - De component auto-init op elementen met data-component="QuantumNavigation" en data-auto-init="true".
 */
(function (global, factory) {
  if (typeof module === "object" && typeof module.exports === "object") {
    module.exports = factory();
  } else {
    global.QuantumNavigation = factory();
  }
})(typeof window !== "undefined" ? window : this, function () {

  class QuantumNavigation {
    constructor(options = {}) {
      const defaults = {
        root: "#quantumNav",
        navLinksSelector: ".quantum-nav-links",
        mobileBtnSelector: ".quantum-mobile-btn, #quantumMobileBtn",
        currentPage: "",
        showUserProfile: true,
        adminOnly: false,
        user: { name: "Gebruiker", avatar: "U", role: "Gebruiker" },
        onLogout: null,
        customNavItems: null,
        forceDrawer: "auto",       // "auto" | true | false
        fallbackBreakpoint: 1200   // CSS fallback; JS gebruikt overflow-detectie
      };
      this.options = { ...defaults, ...options };

      this.nav = typeof this.options.root === "string" ? document.querySelector(this.options.root) : this.options.root;
      if (!this.nav) { console.error("QuantumNavigation: root not found", this.options.root); return; }

      // Zorg dat basis-klasse aanwezig is (voor CSS hooks)
      this.nav.classList.add("quantum-nav");

      // data-attrs lezen
      const dataForce = this.nav.getAttribute("data-force-drawer");
      if (dataForce) this.options.forceDrawer = (dataForce === "true" || dataForce === "1") ? true : (dataForce === "false" ? false : "auto");
      const dataBreak = parseInt(this.nav.getAttribute("data-breakpoint") || "", 10);
      if (!Number.isNaN(dataBreak)) this.options.fallbackBreakpoint = dataBreak;

      this.navLinks = this.nav.querySelector(this.options.navLinksSelector) || this.nav.querySelector("#quantumNavLinks");
      this.mobileBtn = this.nav.querySelector(this.options.mobileBtnSelector) || document.querySelector("#quantumMobileBtn");
      if (!this.navLinks || !this.mobileBtn) { console.error("QuantumNavigation: navLinks or mobileBtn missing"); return; }

      this.container = this.nav.querySelector(".quantum-nav-container") || this.nav;
      this.brand     = this.nav.querySelector(".quantum-nav-brand");
      this.actions   = null; // set in setupNavigation
      this.isMenuOpen = false;
      this._focusableCache = null;

      // bindings
      this._onScroll = this._onScroll.bind(this);
      this._rafScroll = false;
      this._applyLayoutMode = this._applyLayoutMode.bind(this);
      this._onResize = this._onResize.bind(this);
      this._onClickOutside = this._onClickOutside.bind(this);
      this._onKeydown = this._onKeydown.bind(this);

      // observers
      this._resizeObs = null;

      this.init();
    }

    /* ---------- Init ---------- */
    init() {
      this.setupNavigation();
      this.setupMobileMenu();
      this.setupScrollEffects();
      this.setupA11y();
      this.setupGlobalHandlers();

      // Markeer dat JS actief is (overrulet CSS fallback)
      this.nav.classList.add("js-ready");

      // Eerste layout-bepaling + extra passes om FOUC/overflow bij font-load te voorkomen
      this._applyLayoutMode();
      requestAnimationFrame(this._applyLayoutMode);
      window.addEventListener("load", this._applyLayoutMode, { once:true });
      if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(this._applyLayoutMode);
      }

      // HREFs meteen proberen te hydrateren (mocht FLASK_URLS al gezet zijn)
      this.refreshHrefs();

      // Observeer breedte/veranderingen van container/links/acties
      if ("ResizeObserver" in window) {
        this._resizeObs = new ResizeObserver(() => {
          this._applyLayoutMode();
          // (optioneel) opnieuw hydrateren bij layout-veranderingen
          this.refreshHrefs();
        });
        this._resizeObs.observe(this.container);
        this._resizeObs.observe(this.navLinks);
      }

      // BFCache terugkeer (Safari/Firefox)
      window.addEventListener("pageshow", (e)=>{ if (e.persisted) { this._applyLayoutMode(); this.refreshHrefs(); }});

      this.emit("ready");
    }

    setupNavigation() {
      const defaults = [
        { id: "dashboard",       flaskRoute: "dashboard.bedrijfsdashboard", icon: "🏠", text: "Home" },
        { id: "bemesting-nieuw", flaskRoute: "bemestingen.bemestingen_nieuw", icon: "➕", text: "Nieuwe bemesting" },
        { id: "bedrijven",       flaskRoute: "bedrijven.bedrijven", icon: "🏢", text: "Bedrijven" },
        { id: "percelen",        flaskRoute: "percelen.percelen", icon: "🌾", text: "Percelen" },
        { id: "gebruiksnormen",  flaskRoute: "gebruiksnormen.gebruiksnormen", icon: "📊", text: "Gebruiksnormen" },
        { id: "universele-data", flaskRoute: "universele_data.universele_data", icon: "🌱", text: "Universele data" },
        { id: "bemestingen",     flaskRoute: "bemestingen.bemestingen", icon: "🧪", text: "Bemestingen" },
        { id: "gebruikers",      flaskRoute: "gebruikers.gebruikers", icon: "👥", text: "Gebruikersbeheer", adminOnly: true }
      ];
      const items = this.options.customNavItems || defaults;

      // (Re)build
      this.navLinks.innerHTML = "";
      items
        .filter(i => !i.adminOnly || this.options.adminOnly)
        .forEach(item => this._addItem(item));

      // Actions rechts (user)
      const actions = document.createElement("div");
      actions.className = "quantum-nav-actions";
      if (this.options.showUserProfile && this.options.user) actions.appendChild(this._userProfile());
      this.navLinks.appendChild(actions);
      this.actions = actions;
    }

    _addItem(item) {
      const li = document.createElement("li");
      li.className = "quantum-nav-item";

      const a = document.createElement("a");
      a.href = this._flaskUrl(item.flaskRoute) || item.href || "#";
      a.className = `quantum-nav-link ${item.id === this.options.currentPage ? "active" : ""}`;
      a.setAttribute("data-page", item.id);
      a.setAttribute("role", "menuitem");
      a.setAttribute("tabindex", "0");

      // Bewaar de Flask-route, zodat we later de echte URL kunnen zetten
      if (item.flaskRoute) a.dataset.flaskRoute = item.flaskRoute;

      if (item.icon) {
        const icon = document.createElement("span");
        icon.className = "quantum-nav-icon";
        icon.textContent = item.icon;
        a.appendChild(icon);
      }
      const text = document.createElement("span");
      text.className = "quantum-nav-text";
      text.textContent = item.text;
      a.appendChild(text);

      a.addEventListener("click", (e) => this._onNavClick(e, item));
      li.appendChild(a);
      this.navLinks.appendChild(li);
    }

    _flaskUrl(route) {
      if (route && window.FLASK_URLS && window.FLASK_URLS[route]) return window.FLASK_URLS[route];
      return null;
    }

    // Zet/actualiseer alle hrefs aan de hand van FLASK_URLS (na setFlaskUrls of init)
    refreshHrefs(){
      const links = this.nav.querySelectorAll(".quantum-nav-link");
      links.forEach(a=>{
        const route = a.dataset.flaskRoute;
        if (!route) return;
        const url = this._flaskUrl(route);
        if (url) a.setAttribute("href", url);
      });
    }

    _userProfile() {
      const li = document.createElement("li");
      li.className = "quantum-nav-user";

      const btn = document.createElement("button");
      btn.className = "quantum-nav-user-btn";
      btn.setAttribute("aria-expanded", "false");
      btn.setAttribute("aria-haspopup", "true");
      btn.innerHTML = `<div class="quantum-nav-avatar">${this.options.user.avatar}</div><span class="quantum-nav-text">${this.options.user.name}</span>`;

      const dd = document.createElement("div");
      dd.className = "quantum-nav-user-dropdown";
      dd.setAttribute("role", "menu");
      dd.innerHTML = `
        <a href="#" class="quantum-nav-dropdown-item" role="menuitem">👤 Profiel</a>
        <a href="#" class="quantum-nav-dropdown-item" role="menuitem">⚙️ Instellingen</a>
        <div class="quantum-nav-dropdown-divider" role="separator"></div>
        <button class="quantum-nav-dropdown-item" data-action="logout" role="menuitem">🚪 Uitloggen</button>
      `;

      btn.addEventListener("click", (e) => {
        e.preventDefault();
        this._toggleUserDropdown(dd, btn);
      });

      dd.querySelector('[data-action="logout"]')?.addEventListener("click", (e) => {
        e.preventDefault(); this.logout();
      });

      li.appendChild(btn);
      li.appendChild(dd);
      return li;
    }

    _renderHamburgerIcon() {
      if (this.mobileBtn.childElementCount || this.mobileBtn.textContent.trim()) return;
      const wrap = document.createElement("span");
      wrap.className = "quantum-hamburger";
      for (let i = 0; i < 3; i++) { wrap.appendChild(document.createElement("span")); }
      this.mobileBtn.appendChild(wrap);
    }

    setupMobileMenu() {
      this._renderHamburgerIcon();
      this.mobileBtn.addEventListener("click", () => this.toggleMobileMenu());
      this.mobileBtn.setAttribute("aria-expanded", "false");
      this.mobileBtn.setAttribute("aria-controls", this.navLinks.id || "quantumNavLinks");
      this.navLinks.setAttribute("role", "menubar");
      this._setDrawerAria(false);
    }

    toggleMobileMenu(){ this.isMenuOpen ? this.closeMobileMenu() : this.openMobileMenu(); }
    openMobileMenu(){
      // Alleen openen als we echt in drawer-modus zitten
      if (!this.nav.classList.contains("use-drawer")) return;
      this.navLinks.classList.add("active");
      this.mobileBtn.classList.add("active");
      this.mobileBtn.setAttribute("aria-expanded","true");
      document.body.classList.add("nav-open");
      document.body.style.overflow = "hidden";
      this.isMenuOpen = true;
      this._trapFocus();
      this._setDrawerAria(true);
      this.emit("menuOpen");
    }
    closeMobileMenu(){
      this.navLinks.classList.remove("active");
      this.mobileBtn.classList.remove("active");
      this.mobileBtn.setAttribute("aria-expanded","false");
      document.body.classList.remove("nav-open");
      document.body.style.overflow = "";
      this.isMenuOpen = false;
      this._releaseFocus();
      this._setDrawerAria(false);
      this.emit("menuClose");
    }
    _setDrawerAria(open){ this.navLinks.setAttribute("aria-hidden", open ? "false" : "true"); }

    /* ---------- Layout switching (inline ↔ drawer) ---------- */
    _applyLayoutMode(){
      const forced = this.options.forceDrawer;
      let useDrawer = forced === true;

      if (forced === "auto" || forced === undefined || forced === null) {
        useDrawer = this._needsDrawer();
      }

      // Toggle class
      this.nav.classList.toggle("use-drawer", !!useDrawer);

      // Ga naar inline? sluit dan zeker het drawer-menu.
      if (!useDrawer && this.isMenuOpen) this.closeMobileMenu();
    }

    _needsDrawer(){
      // 1) harde breakpoint (fallback)
      if (window.innerWidth <= this.options.fallbackBreakpoint) return true;

      // 2) overflow-detectie: heb je genoeg ruimte?
      const brandW   = this.brand?.offsetWidth   || 0;
      const actionsW = this.actions?.offsetWidth || 0;
      const available = this.container.clientWidth - brandW - actionsW - 32; // marge

      // Alleen de items (zonder actions) meten
      let itemsWidth = 0;
      const items = Array.from(this.navLinks.children).filter(el => !el.classList.contains("quantum-nav-actions"));
      items.forEach(el => itemsWidth += el.offsetWidth);

      // Wrapped?
      const wrapped = items.length
        ? (items[items.length-1].offsetTop > items[0].offsetTop + 5)
        : false;

      return (itemsWidth > available) || wrapped;
    }

    /* ---------- Scroll effecten ---------- */
    setupScrollEffects(){
      window.addEventListener("scroll", this._onScroll, { passive:true });
      this._onScroll();
    }
    _onScroll(){
      if (this._rafScroll) return;
      this._rafScroll = true;
      requestAnimationFrame(() => {
        if (window.scrollY > 100) this.nav.classList.add("scrolled");
        else this.nav.classList.remove("scrolled");
        this._rafScroll = false;
      });
    }

    /* ---------- A11y ---------- */
    setupA11y(){ document.addEventListener("keydown", this._onKeydown); }
    _onKeydown(e){
      if (e.key === "Escape" && this.isMenuOpen) this.closeMobileMenu();
      if (e.key === "Tab" && this.isMenuOpen) {
        const f = this._getFocusable();
        if (!f.length) return;
        const first = f[0], last = f[f.length-1];
        if (e.shiftKey && document.activeElement === first){ e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last){ e.preventDefault(); first.focus(); }
      }
    }
    _trapFocus(){
      this._focusableCache = this._getFocusable();
      if (this._focusableCache[0] && !this.nav.contains(document.activeElement)) {
        this._focusableCache[0].focus();
      }
    }
    _releaseFocus(){ this._focusableCache = null; }
    _getFocusable(){
      return Array.from(this.nav.querySelectorAll('a[href],button:not([disabled]),[tabindex]:not([tabindex="-1"])'))
        .filter(el => el.offsetParent !== null);
    }

    /* ---------- Click buiten nav + externe triggers ---------- */
    setupGlobalHandlers(){
      window.addEventListener("resize", this._onResize);
      window.addEventListener("orientationchange", this._applyLayoutMode);
      document.addEventListener("click", this._onClickOutside, { capture:true });

      // Externe triggers: open hetzelfde user-menu vanaf elk element met onderstaande selector
      document.addEventListener("click", (e) => {
        const t = e.target.closest('[data-open-user],[data-quantum-open="user-menu"],.js-open-user-menu');
        if (!t) return;
        e.preventDefault();

        const dd  = this.nav.querySelector(".quantum-nav-user-dropdown");
        const btn = this.nav.querySelector(".quantum-nav-user-btn");
        if (!dd || !btn) return;

        const willOpen = !dd.classList.contains("open");
        this._toggleUserDropdown(dd, btn, { anchorEl: willOpen ? t : null });
      }, { capture:false });

      // Href-hydratie wanneer Flask URLs binnenkomen
      document.addEventListener('flaskUrlsReady', () => this.refreshHrefs());
    }

    _onResize(){ this._applyLayoutMode(); }

    _onClickOutside(e){
      if (!this.nav.contains(e.target) && this.isMenuOpen) this.closeMobileMenu();
      const dd = this.nav.querySelector(".quantum-nav-user-dropdown.open");
      if (dd && !dd.parentElement.contains(e.target)) {
        dd.classList.remove("open");
        dd.parentElement.querySelector(".quantum-nav-user-btn")?.setAttribute("aria-expanded","false");
      }
    }

    /* ---------- Dropdown positionering ---------- */
    _toggleUserDropdown(dd, triggerEl, { anchorEl = null } = {}) {
      const willOpen = !dd.classList.contains("open");

      // Sluit andere dropdowns
      this.nav.querySelectorAll(".quantum-nav-user-dropdown.open").forEach(x=>{ if (x !== dd) x.classList.remove("open"); });

      dd.classList.toggle("open", willOpen);
      triggerEl?.setAttribute("aria-expanded", String(willOpen));

      if (willOpen) {
        this._positionDropdown(dd, triggerEl, { fixedTo: anchorEl || null });
        dd.querySelector(".quantum-nav-dropdown-item")?.focus();
      }
    }

    _positionDropdown(dd, triggerEl, { fixedTo = null } = {}) {
      dd.classList.remove("drop-down","is-fixed");
      dd.style.removeProperty("--dd-top");
      dd.style.removeProperty("--dd-left");
      dd.style.removeProperty("--dd-origin");

      const rect = (fixedTo || triggerEl).getBoundingClientRect();
      const ddWidth  = dd.offsetWidth || 260;
      const ddHeight = dd.offsetHeight || 180;

      const spaceAbove = rect.top;
      const spaceBelow = window.innerHeight - rect.bottom;
      const openDown = spaceBelow >= ddHeight + 12 || spaceBelow > spaceAbove;

      if (fixedTo) {
        let top, left, origin;
        if (openDown) { top = rect.bottom + 8; origin = "top right"; }
        else         { top = rect.top - ddHeight - 8; origin = "bottom right"; }
        left = Math.max(8, Math.min(rect.right - ddWidth, window.innerWidth - ddWidth - 8));
        dd.classList.add("is-fixed");
        dd.style.setProperty("--dd-top",  `${top}px`);
        dd.style.setProperty("--dd-left", `${left}px`);
        dd.style.setProperty("--dd-origin", origin);
      } else {
        if (openDown) dd.classList.add("drop-down");
      }
    }

    /* ---------- Navigatie ---------- */
    _onNavClick(e, item){
      // Sluit drawer indien open
      if (this.isMenuOpen) this.closeMobileMenu();

      const anchor = e.currentTarget;
      const href   = anchor?.getAttribute('href') || "";
      const route  = anchor?.dataset?.flaskRoute || item.flaskRoute || "";
      const url    = route ? this._flaskUrl(route) : null;

      // Als href nog '#' is maar we wél een URL kunnen resolveren → navigeer
      if ((!href || href === "#" || href.endsWith("/#")) && url){
        e.preventDefault();
        window.location.assign(url);
        return;
      }

      // Anders: laat browser doen (geen preventDefault)
      this.setActive(item.id);
      this.emit("navigate", { item, event:e });
    }

    /* ---------- Public API ---------- */
    setActive(pageId){
      this.nav.querySelectorAll(".quantum-nav-link").forEach(a => {
        a.classList.toggle("active", a.getAttribute("data-page") === pageId);
      });
      this.options.currentPage = pageId;
      this.emit("activeChange", { pageId });
    }
    updateBadge(pageId, badge){
      const li = this.nav.querySelector(`.quantum-nav-link[data-page="${pageId}"]`)?.parentElement;
      if (!li) return;
      li.querySelector(".quantum-nav-badge")?.remove();
      if (badge){
        const b = document.createElement("span");
        b.className="quantum-nav-badge"; b.textContent = badge;
        li.appendChild(b);
      }
    }
    updateUser(user = {}){
      this.options.user = { ...this.options.user, ...user };
      const avatar = this.nav.querySelector(".quantum-nav-avatar");
      if (avatar) avatar.textContent = this.options.user.avatar ?? "U";
      const nameEl = this.nav.querySelector(".quantum-nav-user-btn .quantum-nav-text");
      if (nameEl) nameEl.textContent = this.options.user.name ?? "Gebruiker";
      this.emit("userUpdate", { user: this.options.user });
    }
    logout(){
      if (typeof this.options.onLogout === "function") {
        this.options.onLogout();
      } else {
        const href = this._flaskUrl("gebruikers.logout");
        if (href) window.location.href = href;
        else if (confirm("Uitloggen?")) alert("Configureer 'gebruikers.logout' in FLASK_URLS.");
      }
      this.emit("logout");
    }
    openMobile(){ this.openMobileMenu(); }
    closeMobile(){ this.closeMobileMenu(); }
    toggleMobile(){ this.toggleMobileMenu(); }
    setTheme(theme){ this.nav.setAttribute("data-theme", theme); }
    destroy(){
      window.removeEventListener("scroll", this._onScroll);
      window.removeEventListener("resize", this._onResize);
      window.removeEventListener("orientationchange", this._applyLayoutMode);
      document.removeEventListener("click", this._onClickOutside, { capture:true });
      document.removeEventListener("keydown", this._onKeydown);
      if (this._resizeObs) this._resizeObs.disconnect();
      document.body.classList.remove("nav-open");
      document.body.style.overflow = "";
      this.emit("destroy");
    }
    emit(name, detail = {}){ this.nav.dispatchEvent(new CustomEvent(`quantumNav:${name}`, { detail, bubbles:true })); }
    on(name, cb){ this.nav.addEventListener(`quantumNav:${name}`, cb); }
    off(name, cb){ this.nav.removeEventListener(`quantumNav:${name}`, cb); }

    /* ---------- Auto-init ---------- */
    static autoInit(){
      const nodes = document.querySelectorAll('[data-component="QuantumNavigation"][data-auto-init="true"]');
      const instances = [];
      nodes.forEach(el => {
        const opts = {
          root: el,
          currentPage: el.dataset.currentPage || "",
          adminOnly: el.dataset.adminOnly === "true",
          showUserProfile: el.dataset.showUserProfile !== "false",
          forceDrawer: el.dataset.forceDrawer || "auto",
          fallbackBreakpoint: parseInt(el.dataset.breakpoint || "1200", 10)
        };
        instances.push(new QuantumNavigation(opts));
      });
      return instances;
    }
  }

  // Auto-init op DOMContentLoaded
  if (typeof document !== "undefined") {
    document.addEventListener("DOMContentLoaded", () => { QuantumNavigation.autoInit(); });
  }

  return QuantumNavigation;
});


/* ---------- Flask helper: routes instellen + event dispatch voor hydratatie ---------- */
window.setFlaskUrls = (urls)=>{
  window.FLASK_URLS = urls || {};
  document.dispatchEvent(new CustomEvent('flaskUrlsReady'));
};


/* ---------- Nav-offset helper: zet --qnav-h op basis van echte hoogte ---------- */
(function(){
  const nav = document.getElementById('quantumNav');
  if (!nav) return;

  function setNavOffset(){
    // meet de echte hoogte (met blur/border etc.)
    const h = Math.ceil(nav.getBoundingClientRect().height || 72);
    document.documentElement.style.setProperty('--qnav-h', h + 'px');
  }

  // init + updates bij relevante gebeurtenissen
  const once = { once:true };
  setNavOffset();
  window.addEventListener('load', setNavOffset, once);
  window.addEventListener('resize', setNavOffset);
  window.addEventListener('orientationchange', setNavOffset);
  document.fonts?.ready.then(setNavOffset);

  // luister naar events uit QuantumNavigation
  nav.addEventListener('quantumNav:ready', setNavOffset);
  nav.addEventListener('quantumNav:menuOpen', setNavOffset);
  nav.addEventListener('quantumNav:menuClose', setNavOffset);

  // volg veranderingen in de nav zelf
  if ('ResizeObserver' in window){
    const ro = new ResizeObserver(setNavOffset);
    ro.observe(nav);
  }
})();

(function(){
  const nav = document.getElementById('quantumNav');
  const labelEl = document.getElementById('quantumPageLabel');
  const h1 = document.getElementById('pageTitle');

  if(!nav || !labelEl || !h1) return;

  function getActiveLabel(){
    // 1) expliciete override (optioneel): <nav data-page-title="Universele Data">
    const override = nav.getAttribute('data-page-title');
    if (override) return override;

    // 2) actieve nav-link tekst
    const activeText = nav.querySelector('.quantum-nav-link.active .quantum-nav-text')?.textContent?.trim();
    if (activeText) return activeText;

    // 3) via data-current-page id
    const pageId = nav.dataset.currentPage || nav.getAttribute('data-currentPage');
    const byIdText = pageId
      ? nav.querySelector(`.quantum-nav-link[data-page="${pageId}"] .quantum-nav-text`)?.textContent?.trim()
      : null;
    if (byIdText) return byIdText;

    // 4) fallback: H1 of document.title
    const h1Existing = document.querySelector('.header-row .page-title')?.textContent?.trim();
    if (h1Existing) return h1Existing.replace(/\s+/g,' ');
    return (document.title || '').replace(/[|–-].*$/,'').trim() || 'Pagina';
  }

  function refresh(){
    const t = getActiveLabel();
    labelEl.textContent = t;
    h1.textContent = t;
  }

  // updaten bij init, actieve wijziging, (terug) navigeren en fonts/layout
  nav.addEventListener('quantumNav:ready', refresh);
  nav.addEventListener('quantumNav:activeChange', refresh);
  window.addEventListener('pageshow', refresh);
  document.addEventListener('DOMContentLoaded', refresh);
  document.fonts?.ready.then(refresh);
  refresh();
})();