/* Mention picker for the dashboard's message fields.
   Every <textarea> gets a small bar (# Channel · @ Role · @ User) that inserts
   <#id> / <@&id> / <@id> at the cursor, so nobody has to copy IDs out of Discord.
   The field itself becomes a plain-text contenteditable that shows those tokens
   as Discord-style pills (#chat, @Mod, @Fabian). The textarea stays in the DOM,
   hidden, as the source of truth: its .value always holds the raw tokens, and
   setting .value from the dashboard's own code re-renders the editor.
   Channels and roles come from window.BAXI_MENTIONS (rendered into the page);
   users are looked up through /api/dash/members/. Textareas the dashboard adds
   later (sticky edit, custom commands, livestream) are picked up by the observer.
   Opt out per field with data-no-mentions. With this file blocked, every field
   still works: you just type the mention by hand. */

(function () {
    const cfg = window.BAXI_MENTIONS;
    if (!cfg) return;

    const KINDS = {
        channel: { label: 'Channel', icon: '#', placeholder: 'Search channels…' },
        role: { label: 'Role', icon: '@', placeholder: 'Search roles…' },
        user: { label: 'User', icon: '@', placeholder: 'Search by name or nickname…' },
    };

    let pop = null;       // the single open popover
    let popState = null;  // { textarea, kind, items, index, input, list, timer }

    function el(tag, cls, text) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text !== undefined) e.textContent = text;
        return e;
    }

    /* ── Data ───────────────────────────────────────────────────── */

    function localItems(kind) {
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

    const TOKEN_RE = /<#(\d{17,20})>|<@&(\d{17,20})>|<@!?(\d{17,20})>|@(everyone|here)\b/g;
    const userNames = new Map();     // id -> display name (null while unknown)
    const pendingUsers = new Set();
    let resolveTimer = null;

    function labelFor(m) {
        if (m[1]) {
            if (cfg.channels && cfg.channels[m[1]]) return { kind: 'channel', prefix: '#', name: cfg.channels[m[1]] };
            if (cfg.voice && cfg.voice[m[1]]) return { kind: 'channel', prefix: '🔊', name: cfg.voice[m[1]] };
            if (cfg.forum && cfg.forum[m[1]]) return { kind: 'channel', prefix: '💬', name: cfg.forum[m[1]] };
            if (cfg.stage && cfg.stage[m[1]]) return { kind: 'channel', prefix: '🎙', name: cfg.stage[m[1]] };
            return { kind: 'channel', prefix: '#', name: 'unknown-channel', dead: true };
        }
        if (m[2]) {
            const n = cfg.roles && cfg.roles[m[2]];
            return n ? { kind: 'role', prefix: '@', name: n } : { kind: 'role', prefix: '@', name: 'deleted-role', dead: true };
        }
        if (m[3]) {
            const known = userNames.get(m[3]);
            if (known) return { kind: 'user', prefix: '@', name: known };
            if (!userNames.has(m[3])) { userNames.set(m[3], null); pendingUsers.add(m[3]); scheduleResolve(); }
            return { kind: 'user', prefix: '@', name: 'user', loading: true };
        }
        return { kind: 'special', prefix: '@', name: m[4] };
    }

    function makePill(token, m) {
        const info = labelFor(m);
        const pill = el('span', 'mp-pill mp-pill-' + info.kind);
        pill.contentEditable = 'false';
        pill.dataset.token = token;
        if (info.dead) pill.classList.add('dead');
        if (m[3]) pill.dataset.uid = m[3];
        pill.append(el('span', 'mp-pill-prefix', info.prefix), el('span', 'mp-pill-name', info.name));
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
                if (n) { p.querySelector('.mp-pill-name').textContent = n; }
            });
            if (pendingUsers.size) scheduleResolve();
        }, 60);
    }

    /* ── Editor (pills over a hidden textarea) ──────────────────── */

    // Browsers without contenteditable="plaintext-only" keep the plain textarea (and the bar).
    const PLAINTEXT_OK = (() => { const d = document.createElement('div'); d.contentEditable = 'plaintext-only'; return d.contentEditable === 'plaintext-only'; })();
    const nativeValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');

    function serialize(node) {
        let out = '';
        node.childNodes.forEach(n => {
            if (n.nodeType === 3) out += n.nodeValue;
            else if (n.classList && n.classList.contains('mp-pill')) out += n.dataset.token;
            else if (n.classList && n.classList.contains('mp-trail')) { /* display-only line */ }
            else if (n.nodeName === 'BR') out += '\n';
            else if (n.nodeName === 'DIV' || n.nodeName === 'P') out += (out && !out.endsWith('\n') ? '\n' : '') + serialize(n);
            else out += serialize(n);
        });
        return out;
    }

    function renderInto(editor, text) {
        editor.replaceChildren();
        let last = 0;
        TOKEN_RE.lastIndex = 0;
        let m;
        while ((m = TOKEN_RE.exec(text))) {
            if (m.index > last) editor.appendChild(document.createTextNode(text.slice(last, m.index)));
            editor.appendChild(makePill(m[0], m));
            last = m.index + m[0].length;
        }
        if (last < text.length) editor.appendChild(document.createTextNode(text.slice(last)));
        // A trailing newline only shows a line if something follows it.
        if (text.endsWith('\n')) editor.appendChild(el('br', 'mp-trail'));
    }

    function syncPlaceholder(ta, editor) {
        editor.dataset.placeholder = ta.placeholder || '';
    }

    function buildEditor(ta) {
        const editor = el('div', ta.className + ' mp-editor');
        editor.contentEditable = 'plaintext-only';
        editor.spellcheck = true;
        editor.setAttribute('role', 'textbox');
        editor.setAttribute('aria-multiline', 'true');
        if (ta.id) {
            editor.dataset.for = ta.id;
            const label = document.querySelector(`label[for="${CSS.escape(ta.id)}"]`);
            if (label) { if (!label.id) label.id = ta.id + '-label'; editor.setAttribute('aria-labelledby', label.id); }
        }
        if (ta.rows > 0 && ta.hasAttribute('rows')) editor.style.minHeight = `calc(${ta.rows}lh + 1rem)`;

        let good = nativeValue.get.call(ta);   // last value that fit maxlength
        const max = () => (ta.maxLength > 0 ? ta.maxLength : Infinity);

        const render = () => {
            good = nativeValue.get.call(ta);
            renderInto(editor, good);
            syncPlaceholder(ta, editor);
        };

        // Dashboard code reads and writes ta.value everywhere; keep both views in step.
        Object.defineProperty(ta, 'value', {
            configurable: true,
            get() { return nativeValue.get.call(this); },
            set(v) { nativeValue.set.call(this, v); render(); },
        });
        ta.focus = () => editor.focus();

        editor.addEventListener('input', () => {
            const text = serialize(editor);
            if (text.length > max()) { renderInto(editor, good); placeCaretEnd(editor); return; }
            good = text;
            nativeValue.set.call(ta, text);
            ta.dispatchEvent(new Event('input', { bubbles: true }));
        });
        // Typed or pasted <#id> text becomes a pill once the field is left; doing it
        // while typing would throw the caret around.
        editor.addEventListener('blur', () => { if (!pop && serialize(editor) === good) renderInto(editor, good); });

        ta.hidden = true;
        ta.style.display = 'none';
        ta.insertAdjacentElement('beforebegin', editor);
        render();
        return { editor, render, max, setGood: v => { good = v; } };
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

    /* ── Insert ─────────────────────────────────────────────────── */

    function insertToken(ta, token) {
        const ed = ta._mp;
        if (ed) {
            const range = popState && popState.range ? popState.range : currentRange(ed.editor);
            const room = ed.max() - serialize(ed.editor).length + range.toString().length;
            if (token.length + 1 > room) return toastFull(ed.max());
            range.deleteContents();
            TOKEN_RE.lastIndex = 0;
            const m = TOKEN_RE.exec(token);
            const pill = makePill(token, m);
            // A trailing space (like Discord) gives the caret a place to sit after the pill.
            const next = range.endContainer.nodeType === 3 ? range.endContainer.nodeValue.charAt(range.endOffset) : '';
            const space = document.createTextNode(/\s/.test(next) ? '' : ' ');
            range.insertNode(space);
            range.insertNode(pill);
            ed.editor.focus();
            const r = document.createRange();
            r.setStart(space, space.length); r.collapse(true);
            const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
            ed.editor.dispatchEvent(new Event('input', { bubbles: true }));
            return true;
        }
        return insertIntoTextarea(ta, token);
    }

    function toastFull(max) {
        const t = document.getElementById('toaster');
        if (t && t.toast) t.toast({ category: 'error', title: 'Not enough space', description: `This field is limited to ${max} characters.` });
        return false;
    }

    function insertIntoTextarea(ta, token) {
        const max = ta.maxLength > 0 ? ta.maxLength : Infinity;
        const start = ta.selectionStart ?? ta.value.length;
        const end = ta.selectionEnd ?? start;
        if (ta.value.length - (end - start) + token.length > max) return toastFull(max);
        ta.focus();
        ta.setRangeText(token, start, end, 'end');
        // Bubbles to the save bar's dirty tracking and to any character counters.
        ta.dispatchEvent(new Event('input', { bubbles: true }));
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
            } else {
                row.appendChild(el('span', 'mp-prefix', it.prefix));
            }
            row.appendChild(el('span', 'mp-name', it.name));
            if (it.sub) row.appendChild(el('span', 'mp-sub', it.sub + (it.bot ? ' · bot' : '')));
            row.addEventListener('mousedown', ev => ev.preventDefault()); // keep the textarea's cursor
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
        const ta = popState.textarea;
        // A blurred textarea keeps its selection, so the token lands where the cursor was.
        if (insertToken(ta, it.token)) closePop();
    }

    function refresh() {
        const { kind, input } = popState;
        const q = input.value.trim().toLowerCase();
        if (kind !== 'user') {
            const hits = popState.all.filter(it => !q || it.name.toLowerCase().includes(q));
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

    function openPop(ta, kind, anchor) {
        const same = pop && popState.textarea === ta && popState.kind === kind;
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

        // Focusing the search box moves the selection, so keep the caret the user left.
        const range = ta._mp ? currentRange(ta._mp.editor) : null;
        popState = { textarea: ta, kind, items: [], index: -1, input, list, timer: null, range, all: kind === 'user' ? [] : localItems(kind) };

        const r = anchor.getBoundingClientRect();
        const w = Math.min(320, window.innerWidth - 24);
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
            if (ev.key === 'Escape') { ev.preventDefault(); const t = popState.textarea; closePop(); t.focus(); return; }
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

    function enhance(ta) {
        if (ta.dataset.mpDone || ta.hasAttribute('data-no-mentions')) return;
        ta.dataset.mpDone = '1';
        if (PLAINTEXT_OK) {
            try { ta._mp = buildEditor(ta); } catch (e) { ta._mp = null; }
        }

        const bar = el('div', 'mp-bar');
        bar.appendChild(el('span', 'mp-bar-label', 'Insert'));
        Object.keys(KINDS).forEach(kind => {
            const b = el('button', 'btn mp-btn');
            b.type = 'button';
            b.dataset.variant = 'outline';
            b.dataset.size = 'sm';
            b.title = `Insert a ${KINDS[kind].label.toLowerCase()} mention at the cursor`;
            b.append(el('span', 'mp-btn-icon', KINDS[kind].icon), el('span', 'btn-label', KINDS[kind].label));
            // mousedown would blur the textarea and lose its cursor before the click handler reads it.
            b.addEventListener('mousedown', ev => ev.preventDefault());
            b.addEventListener('click', () => openPop(ta, kind, b));
            bar.appendChild(b);
        });
        (ta._mp ? ta._mp.editor : ta).insertAdjacentElement('afterend', bar);
    }

    function scan(root) {
        if (root.nodeType !== 1) return;
        if (root.matches && root.matches('textarea')) enhance(root);
        root.querySelectorAll && root.querySelectorAll('textarea').forEach(enhance);
    }

    function init() {
        scan(document.body);
        new MutationObserver(muts => muts.forEach(m => m.addedNodes.forEach(scan)))
            .observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
