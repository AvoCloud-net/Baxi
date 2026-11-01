/* avo-select: custom dropdowns for native <select> elements.
 *
 * The <select> stays in the DOM (visually hidden, still the source of truth for
 * value, validation, `required`, onchange="" attributes and every script that
 * reads or writes it). A pill-less field trigger + an opaque popover with search
 * replace it on screen. Same idea as the mention picker: one popover at a time,
 * keyboard first, no entrance animation, no colour transitions.
 *
 * Opt out with data-native on the <select>. <select multiple> is left alone.
 * Styling lives in main.css (".avo-dd", ".avo-dd-pop").
 */
(function () {
  'use strict';

  var SEARCH_FROM = 8;               // show the search field from this many options
  var valueDesc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
  var indexDesc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'selectedIndex');
  var CHEVRON = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor"><path d="m6 9 6 6 6-6"/></svg>';
  var CHECK = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor"><path d="M20 6 9 17l-5-5"/></svg>';
  var current = null;                // { sel, trig, pop, ... } of the open popover

  function text(opt) { return (opt.textContent || '').replace(/\s+/g, ' ').trim(); }

  function enhance(sel) {
    if (sel.__avoDd || sel.multiple || sel.size > 1 || sel.hasAttribute('data-native')) return;
    var trig = document.createElement('button');
    trig.type = 'button';
    trig.className = 'avo-dd';
    trig.setAttribute('role', 'combobox');
    trig.setAttribute('aria-haspopup', 'listbox');
    trig.setAttribute('aria-expanded', 'false');
    var lbl = sel.getAttribute('aria-label') || (sel.id && document.querySelector('label[for="' + sel.id + '"]'));
    if (typeof lbl === 'string') trig.setAttribute('aria-label', lbl);
    trig.innerHTML = '<span class="avo-dd-label"></span>' + CHEVRON;

    // The trigger takes over the select's sizing: width utilities and inline widths.
    (sel.className.match(/(^|\s)(w-\S+|min-w-\S+|max-w-\S+|flex-\S+|grow|shrink-0|text-sm)(?=\s|$)/g) || [])
      .forEach(function (c) { trig.classList.add(c.trim()); });
    if (/(^|\s)w-full(\s|$)/.test(sel.className)) trig.style.width = '100%';
    if (/(^|\s)flex-1(\s|$)/.test(sel.className)) trig.style.flex = '1 1 0%';
    ['width', 'maxWidth', 'minWidth', 'flex'].forEach(function (p) { if (sel.style[p]) trig.style[p] = sel.style[p]; });

    sel.classList.add('avo-dd-native');
    sel.tabIndex = -1;
    sel.setAttribute('aria-hidden', 'true');
    sel.parentNode.insertBefore(trig, sel.nextSibling);
    sel.__avoDd = trig;

    function sync() {
      var o = sel.options[sel.selectedIndex];
      var label = trig.firstChild;
      label.textContent = o ? text(o) : '';
      trig.classList.toggle('is-placeholder', !o || o.value === '');
      trig.disabled = sel.disabled;
      trig.hidden = getComputedStyle(sel).display === 'none';
    }
    // Scripts set .value / .selectedIndex directly, which fires no event.
    Object.defineProperty(sel, 'value', {
      configurable: true, get: function () { return valueDesc.get.call(sel); },
      set: function (v) { valueDesc.set.call(sel, v); sync(); }
    });
    Object.defineProperty(sel, 'selectedIndex', {
      configurable: true, get: function () { return indexDesc.get.call(sel); },
      set: function (v) { indexDesc.set.call(sel, v); sync(); }
    });
    sel.addEventListener('change', sync);
    new MutationObserver(sync).observe(sel, {
      childList: true, subtree: true, characterData: true,
      attributes: true, attributeFilter: ['disabled', 'class', 'style', 'hidden', 'selected']
    });
    if (sel.form) sel.form.addEventListener('reset', function () { setTimeout(sync, 0); });

    trig.addEventListener('click', function () { current && current.sel === sel ? close(true) : openPop(sel, trig); });
    trig.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); openPop(sel, trig); }
    });
    sync();
  }

  function close(refocus) {
    if (!current) return;
    var c = current; current = null;
    c.pop.remove();
    c.trig.setAttribute('aria-expanded', 'false');
    document.removeEventListener('pointerdown', onOutside, true);
    window.removeEventListener('resize', onWindow);
    window.removeEventListener('scroll', onScroll, true);
    if (refocus) c.trig.focus();
  }
  function onOutside(e) { if (current && !current.pop.contains(e.target) && !current.trig.contains(e.target)) close(false); }
  function onWindow() { close(false); }
  function onScroll(e) { if (current && !current.pop.contains(e.target)) close(false); }

  function openPop(sel, trig) {
    close(false);
    var opts = [];
    var pop = document.createElement('div');
    pop.className = 'avo-dd-pop';
    var search = null;
    var all = Array.prototype.slice.call(sel.querySelectorAll('option'));
    if (all.length >= SEARCH_FROM) {
      search = document.createElement('input');
      search.type = 'text';
      search.className = 'avo-dd-search';
      search.placeholder = 'Search…';
      search.autocomplete = 'off';
      search.setAttribute('aria-label', 'Search options');
      pop.appendChild(search);
    }
    var list = document.createElement('div');
    list.className = 'avo-dd-list';
    list.setAttribute('role', 'listbox');
    list.tabIndex = -1;
    pop.appendChild(list);

    function addOption(o, host) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'avo-dd-item';
      b.setAttribute('role', 'option');
      b.disabled = o.disabled;
      var selected = o.selected;
      b.setAttribute('aria-selected', selected ? 'true' : 'false');
      b.innerHTML = '<span class="avo-dd-item-text"></span>' + (selected ? CHECK : '');
      b.firstChild.textContent = text(o);
      b.__opt = o;
      b.addEventListener('click', function () { choose(o); });
      host.appendChild(b);
      opts.push(b);
    }
    // optgroups become labelled groups
    Array.prototype.forEach.call(sel.children, function (n) {
      if (n.tagName === 'OPTGROUP') {
        var g = document.createElement('div');
        g.className = 'avo-dd-group';
        g.textContent = n.label;
        list.appendChild(g);
        Array.prototype.forEach.call(n.children, function (o) { addOption(o, list); });
      } else if (n.tagName === 'OPTION') addOption(n, list);
    });
    var empty = document.createElement('div');
    empty.className = 'avo-dd-empty';
    empty.textContent = 'No matches';
    empty.hidden = true;
    list.appendChild(empty);

    function choose(o) {
      if (o.disabled) return;
      var changed = !o.selected;
      valueDesc.set.call(sel, o.value);
      o.selected = true;
      sel.dispatchEvent(new Event('input', { bubbles: true }));
      if (changed) sel.dispatchEvent(new Event('change', { bubbles: true }));
      else sel.dispatchEvent(new Event('change'));
      close(true);
    }

    var active = -1;
    function visible() { return opts.filter(function (b) { return !b.hidden && !b.disabled; }); }
    function setActive(b) {
      opts.forEach(function (x) { x.classList.remove('is-active'); });
      if (b) { b.classList.add('is-active'); b.scrollIntoView({ block: 'nearest' }); }
    }
    function move(d) {
      var v = visible(); if (!v.length) return;
      var i = v.indexOf(list.querySelector('.is-active'));
      i = i < 0 ? (d > 0 ? 0 : v.length - 1) : Math.max(0, Math.min(v.length - 1, i + d));
      setActive(v[i]);
    }
    function filter() {
      var q = search.value.trim().toLowerCase();
      var any = false;
      opts.forEach(function (b) {
        var show = !q || text(b.__opt).toLowerCase().indexOf(q) !== -1;
        b.hidden = !show; if (show) any = true;
      });
      Array.prototype.forEach.call(list.querySelectorAll('.avo-dd-group'), function (g) {
        var n = g.nextElementSibling, shown = false;
        while (n && !n.classList.contains('avo-dd-group') && !n.classList.contains('avo-dd-empty')) { if (!n.hidden) shown = true; n = n.nextElementSibling; }
        g.hidden = !shown;
      });
      empty.hidden = any;
      setActive(visible()[0] || null);
    }
    if (search) search.addEventListener('input', filter);

    pop.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(true); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
      else if (e.key === 'Enter') {
        var a = list.querySelector('.is-active');
        if (a) { e.preventDefault(); choose(a.__opt); }
      } else if (e.key === 'Tab') close(false);
    });

    document.body.appendChild(pop);
    trig.setAttribute('aria-expanded', 'true');
    current = { sel: sel, trig: trig, pop: pop };

    // Position: under the trigger, or above it when there is more room there.
    var r = trig.getBoundingClientRect();
    var vh = window.innerHeight, vw = window.innerWidth;
    var gap = 6, want = Math.min(pop.scrollHeight, 340);
    var below = vh - r.bottom - gap - 12, above = r.top - gap - 12;
    var up = below < Math.min(want, 220) && above > below;
    var width = Math.max(r.width, 220);
    var left = Math.max(12, Math.min(r.left, vw - width - 12));
    pop.style.width = Math.min(width, vw - 24) + 'px';
    pop.style.left = left + 'px';
    pop.style.maxHeight = Math.max(140, Math.min(340, up ? above : below)) + 'px';
    if (up) pop.style.bottom = (vh - r.top + gap) + 'px'; else pop.style.top = (r.bottom + gap) + 'px';

    var sb = opts.filter(function (b) { return b.__opt.selected; })[0];
    setActive(sb || visible()[0] || null);
    if (sb) sb.scrollIntoView({ block: 'center' });
    (search || list).focus({ preventScroll: true });

    document.addEventListener('pointerdown', onOutside, true);
    window.addEventListener('resize', onWindow);
    window.addEventListener('scroll', onScroll, true);
  }

  function scan(root) {
    if (root.tagName === 'SELECT') enhance(root);
    else if (root.querySelectorAll) Array.prototype.forEach.call(root.querySelectorAll('select'), enhance);
  }

  function start() {
    scan(document);
    // Selects built at runtime (streamer rows, ticket buttons, reward tiers …).
    new MutationObserver(function (muts) {
      muts.forEach(function (m) { Array.prototype.forEach.call(m.addedNodes, function (n) { if (n.nodeType === 1) scan(n); }); });
    }).observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
