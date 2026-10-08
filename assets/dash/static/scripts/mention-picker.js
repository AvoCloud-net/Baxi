/* Mention + variable picker for the dashboard's text fields.
   Every <textarea> gets a small bar (# Channel · @ Role · @ User) that inserts
   <#id> / <@&id> / <@id> at the cursor, so nobody has to copy IDs out of Discord.
   A field that declares data-vars="user,server,…" (a textarea or a single-line
   <input>) also gets a { } Variable button. Per-variable help can be overridden:
   data-vars="user=Display name,server". Single-line inputs get no mention buttons
   unless they carry data-mentions.
   The field itself becomes a plain-text contenteditable that shows those tokens
   as pills (#chat, @Mod, @Fabian, {server}). The original textarea/input stays in
   the DOM, hidden, as the source of truth: its .value always holds the raw tokens,
   and setting .value from the dashboard's own code re-renders the editor. The
   editor deliberately carries none of the field's own classes, so
   querySelector('.some-field') keeps finding the real element.
   Channels and roles come from window.BAXI_MENTIONS (rendered into the page);
   users are looked up through /api/dash/members/. Fields the dashboard adds later
   (sticky edit, custom commands, livestream) are picked up by the observer.
   Opt a textarea out with data-no-mentions (it still gets variables if it declares
   any). With this file blocked, every field still works: you type the token by hand. */

(function () {
    const cfg = window.BAXI_MENTIONS;
    if (!cfg) return;

    const KINDS = {
        channel: { label: 'Channel', icon: '#', placeholder: 'Search channels…' },
        role: { label: 'Role', icon: '@', placeholder: 'Search roles…' },
        user: { label: 'User', icon: '@', placeholder: 'Search by name or nickname…' },
        variable: { label: 'Variable', icon: '{ }', placeholder: 'Search variables…' },
    };

    // Default help text; a field can override it with data-vars="name=help".
    const VAR_HELP = {
        user: 'Mentions the member',
        username: 'Account username',
        displayname: 'Display name (nickname)',
        server: 'Server name',
        membercount: 'Number of members',
        button: 'Label of the button that was clicked',
        count: 'Current value',
        target: 'First mentioned user, otherwise the author',
    };

    let pop = null;       // the single open popover
    let popState = null;  // { field, kind, items, index, input, list, timer, range }

    function el(tag, cls, text) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text !== undefined) e.textContent = text;
        return e;
    }

    /* ── Field config ───────────────────────────────────────────── */

    function fieldCfg(f) {
        const vars = (f.dataset.vars || '').split(',').map(s => s.trim()).filter(Boolean).map(s => {
            const i = s.indexOf('=');
            const name = i < 0 ? s : s.slice(0, i);
            return { name, help: i < 0 ? (VAR_HELP[name] || '') : s.slice(i + 1) };
        });
        const single = f.tagName === 'INPUT';
        const mentions = single ? f.hasAttribute('data-mentions') : !f.hasAttribute('data-no-mentions');
        return { vars, single, mentions };
    }

    // One global regex per field: only the token kinds that field supports become pills.
    function tokenRegex(fc) {
        const parts = [];
        if (fc.mentions) {
            parts.push('(?<ch><#(?<chid>\\d{17,20})>)', '(?<ro><@&(?<roid>\\d{17,20})>)',
                '(?<us><@!?(?<usid>\\d{17,20})>)', '(?<sp>@(?<spn>everyone|here)\\b)');
        }
        if (fc.vars.length) parts.push(`(?<va>\\{(?<van>${fc.vars.map(v => v.name).join('|')})\\})`);
        return () => new RegExp(parts.join('|'), 'g');
    }

    /* ── Data ───────────────────────────────────────────────────── */

    function localItems(kind, fc) {
        if (kind === 'variable') {
            return fc.vars.map(v => ({ name: `{${v.name}}`, sub: v.help, token: `{${v.name}}`, prefix: '', search: v.name + ' ' + v.help }));
        }
        if (kind === 'channel') {
            const out = [];
            Object.entries(cfg.channels || {}).forEach(([id, name]) => out.push({ id, name, group: 'Text', token: `<#${id}>`, prefix: '#' }));
            Object.entries(cfg.forum || {}).forEach(([id, name]) => out.push({ id, name, group: 'Forum', token: `<#${id}>`, prefix: '💬' }));
            Object.entries(cfg.voice || {}).forEach(([id, name]) => out.push({ id, name, group: 'Voice', token: `<#${id}>`, prefix: '🔊' }));
            Object.entries(cfg.stage || {}).forEach(([id, name]) => out.push({ id, name, group: 'Stage', token: `<#${id}>`, prefix: '🎙' }));
            return out;
        }
        const out = [
            { id: 'everyone', name: 'everyone', group: 'Special', token: '@everyone', prefix: '@' },
            { id: 'here', name: 'here', group: 'Special', token: '@here', prefix: '@' },
        ];
        const pos = cfg.rolePositions || {};
        Object.entries(cfg.roles || {})
            .filter(([, name]) => name !== '@everyone')
            .sort((a, b) => (pos[b[0]] || 0) - (pos[a[0]] || 0))
            .forEach(([id, name]) => out.push({ id, name, group: 'Roles', token: `<@&${id}>`, prefix: '@' }));
        return out;
    }

    async function searchUsers(query) {
        const res = await fetch(`/api/dash/members/?guild_id=${encodeURIComponent(cfg.guildId)}&q=${encodeURIComponent(query)}`);
        if (!res.ok) throw new Error('lookup failed');
        const body = await res.json();
        return (body.members || []).map(m => ({
            id: m.id, name: m.name, sub: m.username, avatar: m.avatar, bot: m.bot,
            token: `<@${m.id}>`, prefix: '@',
        }));
    }

    /* ── Pills ──────────────────────────────────────────────────── */

    const userNames = new Map();     // id -> display name (null while unknown)
    const pendingUsers = new Set();
    let resolveTimer = null;

    function labelFor(g, fc) {
        if (g.ch) {
            if (cfg.channels && cfg.channels[g.chid]) return { kind: 'channel', prefix: '#', name: cfg.channels[g.chid] };
            if (cfg.voice && cfg.voice[g.chid]) return { kind: 'channel', prefix: '🔊', name: cfg.voice[g.chid] };
            if (cfg.forum && cfg.forum[g.chid]) return { kind: 'channel', prefix: '💬', name: cfg.forum[g.chid] };
            if (cfg.stage && cfg.stage[g.chid]) return { kind: 'channel', prefix: '🎙', name: cfg.stage[g.chid] };
            return { kind: 'channel', prefix: '#', name: 'unknown-channel', dead: true };
        }
        if (g.ro) {
            const n = cfg.roles && cfg.roles[g.roid];
            return n ? { kind: 'role', prefix: '@', name: n } : { kind: 'role', prefix: '@', name: 'deleted-role', dead: true };
        }
        if (g.us) {
            const known = userNames.get(g.usid);
            if (known) return { kind: 'user', prefix: '@', name: known, uid: g.usid };
            if (!userNames.has(g.usid)) { userNames.set(g.usid, null); pendingUsers.add(g.usid); scheduleResolve(); }
            return { kind: 'user', prefix: '@', name: 'user', uid: g.usid };
        }
        if (g.sp) return { kind: 'special', prefix: '@', name: g.spn };
        const v = fc.vars.find(x => x.name === g.van);
        return { kind: 'var', prefix: '', name: `{${g.van}}`, help: v ? v.help : '' };
    }

    function makePill(token, groups, fc) {
        const info = labelFor(groups, fc);
        const pill = el('span', 'mp-pill mp-pill-' + info.kind);
        pill.contentEditable = 'false';
        pill.dataset.token = token;
        if (info.dead) pill.classList.add('dead');
        if (info.uid) pill.dataset.uid = info.uid;
        if (info.help) pill.title = info.help;
        if (info.prefix) pill.append(el('span', 'mp-pill-prefix', info.prefix));
        pill.append(el('span', 'mp-pill-name', info.name));
        return pill;
    }

    function scheduleResolve() {
        clearTimeout(resolveTimer);
        resolveTimer = setTimeout(async () => {
            const ids = [...pendingUsers].slice(0, 10);
            ids.forEach(i => pendingUsers.delete(i));
            if (!ids.length) return;
            try {
                const res = await fetch(`/api/dash/members/?guild_id=${encodeURIComponent(cfg.guildId)}&ids=${ids.join(',')}`);
                const body = res.ok ? await res.json() : { members: [] };
                const found = new Set();
                (body.members || []).forEach(m => { userNames.set(m.id, m.name); found.add(m.id); });
                ids.forEach(i => { if (!found.has(i)) userNames.set(i, 'unknown-user'); });
            } catch (e) {
                ids.forEach(i => userNames.set(i, 'unknown-user'));
            }
            document.querySelectorAll('.mp-pill[data-uid]').forEach(p => {
                const n = userNames.get(p.dataset.uid);
                if (n) p.querySelector('.mp-pill-name').textContent = n;
            });
            if (pendingUsers.size) scheduleResolve();
        }, 60);
    }

    /* ── Editor (pills over a hidden field) ─────────────────────── */

    // Browsers without contenteditable="plaintext-only" keep the plain field (and the bar).
    const PLAINTEXT_OK = (() => { const d = document.createElement('div'); d.contentEditable = 'plaintext-only'; return d.contentEditable === 'plaintext-only'; })();
    const ZWSP = '​'; // gives the caret a place to sit after a pill; never saved

    // Only look classes are copied to the editor. The field's own hooks
    // (.cc-act-response, .tv-trigger-name, …) must stay unique to the real element.
    const LOOK_CLASS = /^(w-|min-h-|max-w-|flex-|grow$|shrink|text-|font-|h-|mt-|mb-)/;

    function serialize(node) {
        let out = '';
        node.childNodes.forEach(n => {
            if (n.nodeType === 3) out += n.nodeValue.split(ZWSP).join('');
            else if (n.classList && n.classList.contains('mp-pill')) out += n.dataset.token;
            else if (n.classList && n.classList.contains('mp-trail')) { /* display-only line */ }
            else if (n.nodeName === 'BR') out += '\n';
            else if (n.nodeName === 'DIV' || n.nodeName === 'P') out += (out && !out.endsWith('\n') ? '\n' : '') + serialize(n);
            else out += serialize(n);
        });
        return out;
    }

    function renderInto(editor, text, fc, mkRe) {
        editor.replaceChildren();
        let last = 0;
        const re = mkRe();
        let m;
        while ((m = re.exec(text))) {
            if (m.index > last) editor.appendChild(document.createTextNode(text.slice(last, m.index)));
            editor.appendChild(makePill(m[0], m.groups, fc));
            last = m.index + m[0].length;
        }
        if (last < text.length) editor.appendChild(document.createTextNode(text.slice(last)));
        // A trailing newline only shows a line if something follows it.
        if (text.endsWith('\n')) editor.appendChild(el('br', 'mp-trail'));
    }

    function placeCaretEnd(editor) {
        editor.focus();
        const r = document.createRange();
        r.selectNodeContents(editor);
        r.collapse(false);
        const sel = getSelection();
        sel.removeAllRanges();
        sel.addRange(r);
    }

    function currentRange(editor) {
        const sel = getSelection();
        if (sel && sel.rangeCount && editor.contains(sel.anchorNode)) return sel.getRangeAt(0).cloneRange();
        const r = document.createRange();
        r.selectNodeContents(editor);
        r.collapse(false);
        return r;
    }

    function buildEditor(f, fc) {
        const nativeValue = Object.getOwnPropertyDescriptor(f.tagName === 'INPUT' ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype, 'value');
        const mkRe = tokenRegex(fc);
        const look = f.className.split(/\s+/).filter(c => LOOK_CLASS.test(c)).join(' ');
        const editor = el('div', `${look} mp-editor${fc.single ? ' mp-single' : ''}`);
        editor.contentEditable = 'plaintext-only';
        editor.spellcheck = !fc.single;
        editor.setAttribute('role', 'textbox');
        if (!fc.single) editor.setAttribute('aria-multiline', 'true');
        if (f.id) {
            const label = document.querySelector(`label[for="${CSS.escape(f.id)}"]`);
            if (label) { if (!label.id) label.id = f.id + '-label'; editor.setAttribute('aria-labelledby', label.id); }
        }
        if (!fc.single && f.hasAttribute('rows')) editor.style.minHeight = `calc(${f.rows}lh + 1rem)`;

        let good = nativeValue.get.call(f);   // last value that fit maxlength
        const max = () => (f.maxLength > 0 ? f.maxLength : Infinity);
        const draw = text => renderInto(editor, text, fc, mkRe);

        const render = () => {
            good = nativeValue.get.call(f);
            draw(good);
            editor.dataset.placeholder = f.placeholder || '';
        };

        // Dashboard code reads and writes .value everywhere; keep both views in step.
        Object.defineProperty(f, 'value', {
            configurable: true,
            get() { return nativeValue.get.call(this); },
            set(v) { nativeValue.set.call(this, v); render(); },
        });
        f.focus = () => editor.focus();

        editor.addEventListener('input', () => {
            let text = serialize(editor);
            if (fc.single && /\n/.test(text)) { text = text.replace(/\s*\n\s*/g, ' '); draw(text); placeCaretEnd(editor); }
            if (text.length > max()) { draw(good); placeCaretEnd(editor); return; }
            good = text;
            nativeValue.set.call(f, text);
            f.dispatchEvent(new Event('input', { bubbles: true }));
        });
        if (fc.single) editor.addEventListener('keydown', ev => { if (ev.key === 'Enter') ev.preventDefault(); });
        // Typed or pasted tokens become pills once the field is left; doing it while
        // typing would throw the caret around. Skipped while the popover holds a range.
        editor.addEventListener('blur', () => { if (!pop && serialize(editor) === good) draw(good); });

        f.hidden = true;
        f.style.display = 'none';
        f.insertAdjacentElement('beforebegin', editor);
        render();
        return {
            editor, fc, max,
            pill(token) { const m = mkRe().exec(token); return m ? makePill(token, m.groups, fc) : null; },
        };
    }

    /* ── Insert ─────────────────────────────────────────────────── */

    function toastFull(max) {
        const t = document.getElementById('toaster');
        if (t && t.toast) t.toast({ category: 'error', title: 'Not enough space', description: `This field is limited to ${max} characters.` });
        return false;
    }

    function insertToken(f, token, withSpace) {
        const ed = f._mp;
        if (!ed) return insertIntoField(f, token);
        const range = popState && popState.range ? popState.range : currentRange(ed.editor);
        const room = ed.max() - serialize(ed.editor).length + range.toString().length;
        if (token.length + (withSpace ? 1 : 0) > room) return toastFull(ed.max());
        const pill = ed.pill(token);
        if (!pill) return insertIntoField(f, token);
        range.deleteContents();
        // Mentions get a trailing space like in Discord; either way the caret needs a text node after the pill.
        const next = range.endContainer.nodeType === 3 ? range.endContainer.nodeValue.charAt(range.endOffset) : '';
        const after = document.createTextNode(withSpace && !/\s/.test(next) ? ' ' : ZWSP);
        range.insertNode(after);
        range.insertNode(pill);
        ed.editor.focus();
        const r = document.createRange();
        r.setStart(after, after.length); r.collapse(true);
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
        ed.editor.dispatchEvent(new Event('input', { bubbles: true }));
        return true;
    }

    function insertIntoField(f, token) {
        const max = f.maxLength > 0 ? f.maxLength : Infinity;
        const start = f.selectionStart ?? f.value.length;
        const end = f.selectionEnd ?? start;
        if (f.value.length - (end - start) + token.length > max) return toastFull(max);
        f.focus();
        f.setRangeText(token, start, end, 'end');
        // Bubbles to the save bar's dirty tracking and to any character counters.
        f.dispatchEvent(new Event('input', { bubbles: true }));
        return true;
    }

    /* ── Popover ────────────────────────────────────────────────── */

    function closePop() {
        if (!pop) return;
        clearTimeout(popState.timer);
        pop.remove();
        pop = popState = null;
        document.removeEventListener('mousedown', onOutside, true);
        window.removeEventListener('resize', closePop);
    }

    function onOutside(ev) {
        if (pop && !pop.contains(ev.target) && !ev.target.closest('.mp-btn')) closePop();
    }

    function renderList(items, emptyText) {
        const list = popState.list;
        list.replaceChildren();
        popState.items = items;
        popState.index = items.length ? 0 : -1;
        if (!items.length) {
            list.appendChild(el('div', 'mp-empty', emptyText));
            return;
        }
        let group = null;
        items.forEach((it, i) => {
            if (it.group && it.group !== group) {
                group = it.group;
                list.appendChild(el('div', 'mp-group', group));
            }
            const row = el('button', 'mp-item');
            row.type = 'button';
            row.dataset.i = i;
            if (it.avatar) {
                const img = el('img', 'mp-avatar');
                img.src = it.avatar; img.alt = ''; img.width = 20; img.height = 20; img.loading = 'lazy';
                row.appendChild(img);
            } else if (it.prefix) {
                row.appendChild(el('span', 'mp-prefix', it.prefix));
            }
            row.appendChild(el('span', 'mp-name', it.name));
            if (it.sub) row.appendChild(el('span', 'mp-sub', it.sub + (it.bot ? ' · bot' : '')));
            row.addEventListener('mousedown', ev => ev.preventDefault()); // keep the field's cursor
            row.addEventListener('click', () => choose(i));
            list.appendChild(row);
        });
        highlight();
    }

    function highlight() {
        const rows = popState.list.querySelectorAll('.mp-item');
        rows.forEach(r => r.classList.toggle('active', Number(r.dataset.i) === popState.index));
        const cur = popState.list.querySelector('.mp-item.active');
        if (cur) cur.scrollIntoView({ block: 'nearest' });
    }

    function choose(i) {
        const it = popState && popState.items[i];
        if (!it) return;
        // A blurred field keeps its selection, so the token lands where the cursor was.
        if (insertToken(popState.field, it.token, popState.kind !== 'variable')) closePop();
    }

    function refresh() {
        const { kind, input } = popState;
        const q = input.value.trim().toLowerCase();
        if (kind !== 'user') {
            const hits = popState.all.filter(it => !q || (it.search || it.name).toLowerCase().includes(q));
            renderList(hits.slice(0, 80), 'Nothing found.');
            return;
        }
        clearTimeout(popState.timer);
        if (!q) { renderList([], 'Type a name to search members.'); return; }
        popState.timer = setTimeout(async () => {
            const state = popState;
            try {
                const hits = await searchUsers(q);
                if (popState === state) renderList(hits, 'No member found.');
            } catch (e) {
                if (popState === state) renderList([], 'Search unavailable.');
            }
        }, 220);
    }

    function openPop(f, kind, anchor) {
        const same = pop && popState.field === f && popState.kind === kind;
        closePop();
        if (same) return;

        pop = el('div', 'mp-pop');
        pop.setAttribute('role', 'dialog');
        const input = el('input', 'mp-search');
        input.type = 'text';
        input.placeholder = KINDS[kind].placeholder;
        input.autocomplete = 'off';
        input.setAttribute('aria-label', KINDS[kind].placeholder);
        const list = el('div', 'mp-list');
        pop.append(input, list);
        document.body.appendChild(pop);

        const fc = f._mp ? f._mp.fc : fieldCfg(f);
        // Focusing the search box moves the selection, so keep the caret the user left.
        const range = f._mp ? currentRange(f._mp.editor) : null;
        popState = { field: f, kind, items: [], index: -1, input, list, timer: null, range, all: kind === 'user' ? [] : localItems(kind, fc) };

        const r = anchor.getBoundingClientRect();
        const w = Math.min(kind === 'variable' ? 360 : 320, window.innerWidth - 24);
        pop.style.width = w + 'px';
        pop.style.left = Math.max(12, Math.min(r.left, window.innerWidth - w - 12)) + 'px';
        const below = window.innerHeight - r.bottom;
        if (below < 300 && r.top > below) {
            pop.style.bottom = (window.innerHeight - r.top + 6) + 'px';
        } else {
            pop.style.top = (r.bottom + 6) + 'px';
        }

        input.addEventListener('input', refresh);
        input.addEventListener('keydown', ev => {
            if (ev.key === 'Escape') { ev.preventDefault(); const t = popState.field; closePop(); t.focus(); return; }
            if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
                ev.preventDefault();
                const n = popState.items.length;
                if (!n) return;
                popState.index = (popState.index + (ev.key === 'ArrowDown' ? 1 : -1) + n) % n;
                highlight();
            } else if (ev.key === 'Enter') {
                ev.preventDefault();
                choose(popState.index);
            }
        });
        document.addEventListener('mousedown', onOutside, true);
        window.addEventListener('resize', closePop);

        refresh();
        input.focus();
    }

    /* ── Bar ────────────────────────────────────────────────────── */

    function enhance(f) {
        if (f.dataset.mpDone) return;
        const fc = fieldCfg(f);
        if (!fc.mentions && !fc.vars.length) return;
        f.dataset.mpDone = '1';
        if (PLAINTEXT_OK) {
            try { f._mp = buildEditor(f, fc); } catch (e) { f._mp = null; }
        }

        const bar = el('div', 'mp-bar' + (fc.single ? ' mp-bar-single' : ''));
        bar.appendChild(el('span', 'mp-bar-label', 'Insert'));
        const kinds = [...(fc.mentions ? ['channel', 'role', 'user'] : []), ...(fc.vars.length ? ['variable'] : [])];
        kinds.forEach(kind => {
            const b = el('button', 'btn mp-btn');
            b.type = 'button';
            b.dataset.variant = 'outline';
            b.dataset.size = 'sm';
            b.title = kind === 'variable' ? 'Insert a variable at the cursor' : `Insert a ${KINDS[kind].label.toLowerCase()} mention at the cursor`;
            b.append(el('span', 'mp-btn-icon', KINDS[kind].icon), el('span', 'btn-label', KINDS[kind].label));
            // mousedown would blur the field and lose its cursor before the click handler reads it.
            b.addEventListener('mousedown', ev => ev.preventDefault());
            b.addEventListener('click', () => openPop(f, kind, b));
            bar.appendChild(b);
        });
        (f._mp ? f._mp.editor : f).insertAdjacentElement('afterend', bar);
    }

    const FIELDS = 'textarea, input[data-vars]';

    function scan(root) {
        if (root.nodeType !== 1) return;
        if (root.matches && root.matches(FIELDS)) enhance(root);
        root.querySelectorAll && root.querySelectorAll(FIELDS).forEach(enhance);
    }

    function init() {
        scan(document.body);
        new MutationObserver(muts => muts.forEach(m => m.addedNodes.forEach(scan)))
            .observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
