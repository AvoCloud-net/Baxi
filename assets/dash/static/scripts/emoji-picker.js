/* Emoji picker for single-line fields.
   Any <input data-emoji-picker> gets a small button that opens an opaque popover with
   the common emojis in tabs; a click puts the emoji into the field (replacing its
   value) and fires an `input` event. The field stays a normal text input, so a custom
   server emoji (<:name:123456789012345678>) can still be typed or pasted. Fields added
   later are picked up by the observer. Without this file the field still works. */
(function () {
    const SETS = [
        ['Smileys', '😀 😃 😄 😁 😆 😅 😂 🤣 😊 😇 🙂 🙃 😉 😌 😍 🥰 😘 😋 😛 😜 🤪 🤨 🧐 🤓 😎 🥳 😏 😒 😞 😔 😟 😕 🙁 😣 😖 😫 😩 🥺 😢 😭 😤 😠 😡 🤬 🤯 😳 🥵 🥶 😱 😨 😰 😥 😓 🤗 🤔 🤭 🤫 🤥 😶 😐 😑 😬 🙄 😯 😦 😧 😮 😲 🥱 😴 🤤 😪 😵 🤐 🥴 🤢 🤮 🤧 😷 🤒 🤕 🤑 🤠 😈 👿 👹 👺 🤡 💩 👻 💀 ☠️ 👽 👾 🤖'],
        ['People', '👋 🤚 🖐️ ✋ 🖖 👌 🤌 🤏 ✌️ 🤞 🤟 🤘 🤙 👈 👉 👆 👇 ☝️ 👍 👎 ✊ 👊 🤛 🤜 👏 🙌 👐 🤲 🤝 🙏 ✍️ 💪 🦾 🧠 👀 👁️ 👅 👄 👶 🧒 👦 👧 🧑 👨 👩 🧓 👴 👵 👮 🕵️ 💂 🥷 👷 🤴 👸 🧙 🧚 🧛 🧜 🦸 🦹'],
        ['Symbols', '❤️ 🧡 💛 💚 💙 💜 🖤 🤍 🤎 💔 ❣️ 💕 💞 💓 💗 💖 💘 💝 💯 💢 💥 💫 💦 💨 💬 💭 💤 ✅ ❌ ❎ ✔️ ➕ ➖ ➗ ✖️ ❓ ❔ ❕ ❗ ‼️ ⁉️ ⚠️ 🚫 ⛔ 📛 🔞 ♻️ ⚜️ 🔱 ⭐ 🌟 ✨ ⚡ 🔥 🌈 ☀️ 🌙 ❄️ 💧 🔔 🔕 🔒 🔓 🔑 🔨 🛠️ ⚙️ 🔧 🧰 🔗 📌 📍 🏷️ 🆗 🆕 🆙 🆘 ℹ️ 🔰 🔴 🟠 🟡 🟢 🔵 🟣 ⚫ ⚪ 🟥 🟧 🟨 🟩 🟦 🟪'],
        ['Objects', '🎫 🎟️ 🎮 🕹️ 🎲 🎯 🎁 🎉 🎊 🎈 🏆 🥇 🥈 🥉 🏅 🎖️ 👑 💎 💰 💵 💳 🛒 🛍️ 📦 📫 📮 📝 ✏️ 🖊️ 📋 📎 📁 📂 🗂️ 📅 📆 📊 📈 📉 📚 📖 🔖 💡 🔦 📱 💻 🖥️ ⌨️ 🖱️ 🎧 🎤 🎵 🎶 📷 📹 🎬 🧪 🔬 🔭 💊 🩹 🚨 🚑 🚓 🚀 ✈️ 🚗 ⚓ 🏠 🏰 🗡️ ⚔️ 🛡️ 🏹 💣 🧨 🪄 🔮'],
        ['Nature', '🐶 🐱 🐭 🐹 🐰 🦊 🐻 🐼 🐨 🐯 🦁 🐮 🐷 🐸 🐵 🐔 🐧 🐦 🦆 🦉 🦇 🐺 🐴 🦄 🐝 🐛 🦋 🐌 🐞 🐜 🕷️ 🐢 🐍 🦎 🐙 🦑 🦀 🐠 🐟 🐬 🐳 🦈 🐊 🐘 🦒 🌵 🌲 🌳 🌴 🌱 🌿 🍀 🍁 🍂 🌸 🌼 🌻 🌹 🍄 🌍 🌎 🌋 🗻'],
        ['Food', '🍏 🍎 🍐 🍊 🍋 🍌 🍉 🍇 🍓 🍒 🍑 🥭 🍍 🥥 🥝 🍅 🥑 🥦 🌽 🥕 🍞 🧀 🍳 🥞 🥓 🍔 🍟 🍕 🌭 🥪 🌮 🌯 🍝 🍜 🍣 🍤 🍦 🍩 🍪 🎂 🍰 🍫 🍬 🍭 ☕ 🍵 🥤 🍺 🍻 🥂 🍷 🍸'],
    ].map(([name, s]) => [name, s.split(/\s+/).filter(Boolean)]);

    let pop = null, current = null;

    function close() { if (pop) { pop.remove(); pop = null; current = null; } }

    function open(input, anchor) {
        close();
        current = input;
        pop = document.createElement('div');
        pop.className = 'ep-pop';
        const tabs = document.createElement('div'); tabs.className = 'ep-tabs';
        const grid = document.createElement('div'); grid.className = 'ep-grid';
        const show = (i) => {
            [...tabs.children].forEach((t, k) => t.classList.toggle('active', k === i));
            grid.innerHTML = '';
            SETS[i][1].forEach((em) => {
                const b = document.createElement('button');
                b.type = 'button'; b.className = 'ep-em'; b.textContent = em; b.title = em;
                b.onclick = () => {
                    input.value = em;
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    close();
                };
                grid.appendChild(b);
            });
        };
        SETS.forEach(([name], i) => {
            const t = document.createElement('button');
            t.type = 'button'; t.className = 'ep-tab'; t.textContent = name; t.onclick = () => show(i);
            tabs.appendChild(t);
        });
        const clear = document.createElement('button');
        clear.type = 'button'; clear.className = 'ep-clear'; clear.textContent = 'Clear';
        clear.onclick = () => { input.value = ''; input.dispatchEvent(new Event('input', { bubbles: true })); close(); };
        pop.append(tabs, grid, clear);
        document.body.appendChild(pop);
        show(0);
        const r = anchor.getBoundingClientRect();
        const w = pop.offsetWidth, h = pop.offsetHeight;
        pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8)) + 'px';
        pop.style.top = (r.bottom + h + 8 > window.innerHeight ? Math.max(8, r.top - h - 4) : r.bottom + 4) + 'px';
    }

    function enhance(input) {
        if (input.dataset.epDone) return;
        input.dataset.epDone = '1';
        const wrap = document.createElement('div');
        wrap.className = 'ep-wrap';
        input.parentNode.insertBefore(wrap, input);
        wrap.appendChild(input);
        const btn = document.createElement('button');
        btn.type = 'button'; btn.className = 'btn ep-btn'; btn.dataset.variant = 'outline'; btn.dataset.size = 'icon';
        btn.title = 'Pick an emoji'; btn.setAttribute('aria-label', 'Pick an emoji'); btn.textContent = '🙂';
        btn.onclick = (e) => { e.stopPropagation(); (pop && current === input) ? close() : open(input, wrap); };
        wrap.appendChild(btn);
    }

    function scan(root) { (root || document).querySelectorAll('input[data-emoji-picker]').forEach(enhance); }

    document.addEventListener('click', (e) => { if (pop && !pop.contains(e.target)) close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
    window.addEventListener('resize', close);
    scan();
    new MutationObserver(() => scan()).observe(document.body, { childList: true, subtree: true });
})();
