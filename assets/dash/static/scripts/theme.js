/* Theme toggle.
 *
 * Replaces https://avocloud.net/assets/js/theme.js, which now 404s. While it was
 * missing, `html.dark` was never set (so every page rendered light regardless of
 * the OS setting), `toggleTheme()` was undefined (so the button did nothing) and
 * #theme-icon stayed the empty circle that gave the bug away.
 *
 * Must stay a plain synchronous <script> in <head>: the class has to land before
 * first paint or the page flashes the wrong theme.
 */
(function () {
    var KEY  = 'avo:theme';
    var root = document.documentElement;
    var mq   = window.matchMedia('(prefers-color-scheme: dark)');

    function stored() {
        try {
            var v = localStorage.getItem(KEY);
            return (v === 'dark' || v === 'light') ? v : null;
        } catch (e) { return null; }   // storage blocked (private mode, embedded)
    }

    /* main.css styles .theme-toggle svg (size, stroke, caps) — these are the
       path data only, so the icon inherits the button's colour. */
    var ICONS = {
        // Shown in dark mode: clicking goes to light.
        sun:  '<circle cx="12" cy="12" r="4"/>'
            + '<path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41'
            + 'M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
        // Shown in light mode: clicking goes to dark.
        moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z"/>'
    };

    function paintIcon(theme) {
        var el = document.getElementById('theme-icon');
        if (!el) return;   // not every page has the toggle
        el.innerHTML = theme === 'dark' ? ICONS.sun : ICONS.moon;
        var btn = el.closest ? el.closest('.theme-toggle') : null;
        if (btn) {
            var label = 'Switch to ' + (theme === 'dark' ? 'light' : 'dark') + ' theme';
            btn.setAttribute('aria-label', label);
            btn.setAttribute('title', label);
        }
    }

    function apply(theme) {
        root.classList.toggle('dark', theme === 'dark');
        paintIcon(theme);
    }

    window.toggleTheme = function () {
        var next = root.classList.contains('dark') ? 'light' : 'dark';
        try { localStorage.setItem(KEY, next); } catch (e) { /* not fatal */ }
        apply(next);
    };

    // Runs in <head>, so the class is set before the body paints. The icon
    // paint is a no-op this early and is redone once the button exists.
    apply(stored() || (mq.matches ? 'dark' : 'light'));
    document.addEventListener('DOMContentLoaded', function () {
        paintIcon(root.classList.contains('dark') ? 'dark' : 'light');
    });

    // Follow the OS only while the visitor has not picked a side themselves.
    try {
        mq.addEventListener('change', function (e) {
            if (stored()) return;
            apply(e.matches ? 'dark' : 'light');
        });
    } catch (e) { /* older Safari: no addEventListener on MediaQueryList */ }
})();
