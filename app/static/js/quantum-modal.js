
/*!
 * QuantumModal v1.0
 * - Declaratief (data-modal-trigger) & Programmatic (API)
 * - Focus trap, ESC/backdrop close, stacked modals
 * - Confirm & Form helpers (Promises)
 * - Compat: .modal / .modal-import (adds open/close)
 */
(function (global, factory) {
  if (typeof module === "object" && typeof module.exports === "object") {
    module.exports = factory();
  } else {
    global.QuantumModal = factory();
  }
})(typeof window !== "undefined" ? window : this, function () {

  const FOCUS_SEL = 'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';
  const STATE = { stack: [], z: parseInt(getComputedStyle(document.documentElement).getPropertyValue('--qm-z')) || 1000010 };

  function isDialog(el){
    return el && (el.classList.contains('qm-modal') || el.classList.contains('modal') || el.classList.contains('modal-import'));
  }
  function qs(x,root=document){ return root.querySelector(x); }
  function qsa(x,root=document){ return Array.from(root.querySelectorAll(x)); }

  function trapFocus(modal){
    const dlg = modal.classList.contains('qm-modal') ? qs('.qm-dialog', modal) : modal;
    const nodes = qsa(FOCUS_SEL, dlg).filter(e=>e.offsetParent!==null);
    if (!nodes.length) return;
    const first = nodes[0], last = nodes[nodes.length-1];
    function onKey(e){
      if (e.key === 'Tab'){
        if (e.shiftKey && document.activeElement === first){ e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last){ e.preventDefault(); first.focus(); }
      } else if (e.key === 'Escape'){
        const isStatic = modal.dataset.modalStatic === 'true' || modal.getAttribute('data-static') === 'true';
        if (!isStatic) QuantumModal.close(modal);
      }
    }
    modal._focusHandler = onKey;
    document.addEventListener('keydown', onKey);
    requestAnimationFrame(()=> first.focus());
  }
  function releaseFocus(modal){
    if (modal._focusHandler){ document.removeEventListener('keydown', modal._focusHandler); modal._focusHandler = null; }
  }

  function lockScroll(){ document.body.classList.add('qm-lock'); }
  function unlockScroll(){
    // Unlock only when no modals
    if (STATE.stack.length === 0) document.body.classList.remove('qm-lock');
  }

  function ensureSkeleton(id){
    let host = qs(id);
    if (host) return host;
    // programmatic create skeleton container
    host = document.createElement('div');
    host.className = 'qm-modal';
    host.id = id.replace(/^#/, '');
    host.innerHTML = `
      <div class="qm-dialog qm-size-md" role="dialog" aria-modal="true" aria-labelledby="${host.id}-title">
        <button class="qm-close" data-modal-close aria-label="Sluiten">×</button>
        <header class="qm-header"><h3 class="qm-title" id="${host.id}-title"></h3><p class="qm-subtitle"></p></header>
        <section class="qm-body"></section>
        <footer class="qm-footer"></footer>
      </div>`;
    document.body.appendChild(host);
    bindModal(host);
    return host;
  }

  function bindModal(modal){
    // backdrop click
    modal.addEventListener('mousedown', (e)=>{
      const dlg = modal.classList.contains('qm-modal') ? qs('.qm-dialog', modal) : modal;
      const isInside = dlg.contains(e.target);
      modal._mouseDownInside = isInside;
    });
    modal.addEventListener('mouseup', (e)=>{
      const dlg = modal.classList.contains('qm-modal') ? qs('.qm-dialog', modal) : modal;
      const isStatic = modal.dataset.modalStatic === 'true' || modal.getAttribute('data-static') === 'true';
      const clickInside = dlg.contains(e.target);
      if (!isStatic && modal._mouseDownInside === false && !clickInside){
        QuantumModal.close(modal);
      }
      modal._mouseDownInside = null;
    });
    // close buttons
    modal.addEventListener('click', (e)=>{
      const btn = e.target.closest('[data-modal-close]');
      if (btn) { e.preventDefault(); QuantumModal.close(modal); }
    });
  }

  function mountActions(footer, actions, modal){
    footer.innerHTML = '';
    (actions||[]).forEach(act=>{
      const b = document.createElement('button');
      b.type = act.type || 'button';
      b.className = `qm-btn ${act.variant==='secondary'?'qm-btn-secondary':act.variant==='danger'?'qm-btn-danger':'qm-btn-primary'}`;
      b.textContent = act.label || 'OK';
      if (act.id) b.id = act.id;
      if (act.attrs) Object.entries(act.attrs).forEach(([k,v])=> b.setAttribute(k,v));
      if (act.close) b.setAttribute('data-modal-close','');
      if (typeof act.onClick === 'function') b.addEventListener('click', (ev)=> act.onClick({event:ev, modal, close:()=>QuantumModal.close(modal)}));
      footer.appendChild(b);
    });
  }

  const QuantumModal = {
    /* Open by id/element or by config */
    open(target){
      let modal = null;
      if (typeof target === 'string'){
        modal = qs(target.startsWith('#')? target : '#'+target) || ensureSkeleton(target);
      } else if (target instanceof HTMLElement){
        modal = isDialog(target) ? target : target.closest('.qm-modal, .modal, .modal-import');
      } else if (target && typeof target === 'object'){
        // config build
        const id = target.id ? (target.id.startsWith('#')? target.id : '#'+target.id) : '#qm-'+Math.random().toString(36).slice(2);
        modal = ensureSkeleton(id);
        const dlg = qs('.qm-dialog', modal);
        if (target.size) dlg.classList.remove('qm-size-sm','qm-size-md','qm-size-lg','qm-size-xl','qm-size-full'), dlg.classList.add('qm-size-'+target.size);
        modal.dataset.modalStatic = target.static ? 'true' : 'false';
        if (target.title) qs('.qm-title', modal).textContent = target.title;
        if (qs('.qm-subtitle', modal)) qs('.qm-subtitle', modal).textContent = target.subtitle || '';
        if (target.html!==undefined) qs('.qm-body', modal).innerHTML = target.html;
        mountActions(qs('.qm-footer', modal), target.actions, modal);
      }
      if (!modal) return null;

      // aria
      const dlg = modal.classList.contains('qm-modal') ? qs('.qm-dialog', modal) : modal;
      dlg.setAttribute('role','dialog'); dlg.setAttribute('aria-modal','true');

      // z-index stacking
      STATE.stack.push(modal);
      modal.style.zIndex = (STATE.z + STATE.stack.length*2).toString();
      if (!modal._bound) { bindModal(modal); modal._bound = true; }

      modal.classList.add('open');
      lockScroll();
      trapFocus(modal);
      modal.dispatchEvent(new CustomEvent('qm:open', {bubbles:true}));
      return modal;
    },

    close(target){
      let modal = null;
      if (!target) modal = STATE.stack[STATE.stack.length-1];
      else if (typeof target === 'string') modal = qs(target.startsWith('#')? target : '#'+target);
      else if (target instanceof HTMLElement) modal = isDialog(target)? target : target.closest('.qm-modal, .modal, .modal-import');
      if (!modal) return;

      releaseFocus(modal);
      modal.classList.remove('open');
      modal.dispatchEvent(new CustomEvent('qm:close', {bubbles:true}));
      // pop from stack
      STATE.stack = STATE.stack.filter(m=>m!==modal);
      unlockScroll();
    },

    /* Quick confirm -> Promise<boolean> */
    confirm(opts={}){
      const { title='Weet je het zeker?', message='', confirmText='Bevestigen', cancelText='Annuleren', variant='danger', isStatic=false } = opts;
      const modal = QuantumModal.open({
        size: 'sm',
        static: isStatic,
        title,
        html: `<div class="qm-body"><p style="margin:6px 0 0 0;">${message}</p></div>`,
        actions: [
          { label: cancelText, variant:'secondary', close:true },
          { label: confirmText, variant, id:'qmConfirmBtn' }
        ]
      });
      return new Promise(resolve=>{
        qs('#qmConfirmBtn', modal).addEventListener('click', ()=>{ resolve(true); QuantumModal.close(modal); }, {once:true});
        modal.addEventListener('qm:close', ()=> resolve(false), {once:true});
      });
    },

    /* Quick form -> Promise<FormData> / null on cancel */
    form(opts={}){
      const { title='Formulier', html='', size='md', submitText='Opslaan', cancelText='Annuleren', isStatic=false } = opts;
      const modal = QuantumModal.open({
        size, static: isStatic, title,
        html: `<form class="qm-form" id="qmDynamicForm" autocomplete="off">${html}</form>`,
        actions: [
          { label: cancelText, variant:'secondary', close:true },
          { label: submitText, variant:'primary', id:'qmFormSubmit' }
        ]
      });
      const form = qs('#qmDynamicForm', modal);
      return new Promise(resolve=>{
        qs('#qmFormSubmit', modal).addEventListener('click', ()=>{
          if (form.reportValidity && !form.reportValidity()) return;
          resolve(new FormData(form));
          QuantumModal.close(modal);
        });
        modal.addEventListener('qm:close', ()=> resolve(null), {once:true});
      });
    },

    /* Helpers */
    setContent(idOrEl, html){ const m = typeof idOrEl==='string'? qs('#'+idOrEl) : idOrEl; if (!m) return; (qs('.qm-body',m)||m).innerHTML = html; },
    setTitle(idOrEl, text){ const m = typeof idOrEl==='string'? qs('#'+idOrEl) : idOrEl; if (!m) return; const t=qs('.qm-title',m)||qs('h2',m); if(t) t.textContent=text; }
  };

  /* --------- Declarative triggers --------- */
  document.addEventListener('click', (e)=>{
    const trg = e.target.closest('[data-modal-trigger]');
    if (trg){
      e.preventDefault();
      const target = trg.getAttribute('data-modal-trigger'); // "#id"
      QuantumModal.open(target);
    }
    const closer = e.target.closest('[data-modal-close]');
    if (closer){
      const host = closer.closest('.qm-modal, .modal, .modal-import');
      if (host) QuantumModal.close(host);
    }
  });

  /* Close on ESC if not static — handled in trapFocus() per-top modal */

  /* Auto-bind existing modals (compat) */
  document.addEventListener('DOMContentLoaded', ()=>{
    qsa('.qm-modal, .modal, .modal-import').forEach(bindModal);
  });

  /* Backwards-compatible global helpers */
  window.openModal  = (id)=> QuantumModal.open(id.startsWith('#')? id : '#'+id);
  window.closeModal = (id)=> QuantumModal.close(id? (id.startsWith('#')? id : '#'+id) : undefined);

  return QuantumModal;
});

