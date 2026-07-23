/* avocloud brand v2.9.1 — shared page behaviour.
   Blueprint-grid drift (§6), page-transition curtain (§5b), plus the existing
   scroll cue and mobile nav toggle. Everything here is decoration: with this
   file blocked, every page is still complete and navigable. */

(function () {
    const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;

    /* ── Blueprint grid (BRANDING §6) ──────────────────────────────────────
       Two fixed layers drifting at DIFFERENT rates. They are not meant to
       line up: two independent scales reading as parallax depth is the point,
       and syncing them flattens it back into one grid.

       transform only — never top/height/background-position (§5b don't-list). */
    function mountGrid() {
        if (document.querySelector('.avo-grid')) return;

        const grid = document.createElement('div');
        grid.className = 'avo-grid';
        grid.setAttribute('aria-hidden', 'true');
        const cross = document.createElement('div');
        cross.className = 'avo-crosshair';
        cross.setAttribute('aria-hidden', 'true');
        document.body.appendChild(grid);
        document.body.appendChild(cross);

        if (REDUCED) return; // static grid, no drift

        let ticking = false;
        function update() {
            ticking = false;
            const y = window.scrollY;
            // The two rates are deliberately unrelated.
            grid.style.setProperty('--avo-grid-y', (y * 0.06) + 'px');
            cross.style.setProperty('--avo-crosshair-y', (y * 0.14) + 'px');
        }
        window.addEventListener('scroll', () => {
            if (ticking) return;
            ticking = true;
            requestAnimationFrame(update);
        }, { passive: true });
        update();
    }

    /* ── Page-transition curtain (BRANDING §5b) ────────────────────────────
       One curtain swept across two page loads: it rises from the bottom edge
       over the outgoing page, and the incoming page carries it the rest of
       the way off the top.

       0.3s out, 0.42s in. UI scale, not signature scale: the outgoing half is
       latency the visitor did not ask for, and anything longer stops reading
       as motion and starts reading as a slow site. */
    const FLAG = 'avo-nav';
    const FLAG_TTL = 4000; // links out to pages that never consume it must expire

    function mountCurtain() {
        if (REDUCED) return;

        const curtain = document.createElement('div');
        curtain.className = 'avo-curtain';
        curtain.setAttribute('aria-hidden', 'true');
        document.body.appendChild(curtain);

        /* ---- arrival ----
           Only animate arrivals that had a departure. Someone coming from a
           bookmark or a search result has nothing to continue from, and
           covering their first view would be a loading screen we invented.

           Where a load intro also runs, the intro wins outright: it already
           owns the reveal, and two curtains for one navigation is one too
           many. */
        let stamp = 0;
        try {
            stamp = parseInt(sessionStorage.getItem(FLAG) || '0', 10);
            sessionStorage.removeItem(FLAG);
        } catch (e) { /* private mode — no arrival half, page still fine */ }

        const hasIntro = !!document.getElementById('avo-splash');
        if (stamp && Date.now() - stamp < FLAG_TTL && !hasIntro) {
            curtain.classList.add('is-covered');
            let released = false;
            const release = () => {
                if (released) return;
                released = true;
                curtain.classList.remove('is-covered');
                curtain.classList.add('is-in');
            };
            /* rAF guarantees the covered state was painted, so the transition
               has something to animate from. The timeout behind it is for the
               throttled tab where rAF stalls for seconds and the visitor
               would otherwise sit under a curtain that never lifts. */
            requestAnimationFrame(() => requestAnimationFrame(release));
            setTimeout(release, 400);
        }

        /* ---- departure ----
           Real <a href> elements stay; only the click is intercepted. A span
           with an onclick is not focusable, not middle-clickable, not "open
           in new tab", and not a link to anything that reads the page. */
        document.addEventListener('click', (ev) => {
            // Never intercept a click that wasn't going to navigate anyway.
            if (ev.defaultPrevented) return;
            if (ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;

            const a = ev.target.closest && ev.target.closest('a[href]');
            if (!a) return;
            if (a.target && a.target !== '_self') return;
            if (a.hasAttribute('download')) return;

            let url;
            try { url = new URL(a.href, location.href); } catch (e) { return; }
            if (url.origin !== location.origin) return;
            if (url.protocol !== 'http:' && url.protocol !== 'https:') return;
            // Covering the screen for a jump to #section is a transition for a
            // navigation that never happened.
            if (url.pathname === location.pathname && url.search === location.search && url.hash) return;

            ev.preventDefault();
            try { sessionStorage.setItem(FLAG, String(Date.now())); } catch (e) { }
            curtain.classList.add('is-out');

            let went = false;
            const go = () => {
                if (went) return;
                went = true;
                location.href = url.href;
            };
            curtain.addEventListener('transitionend', go, { once: true });
            setTimeout(go, 500); // never strand the click on a missed transitionend
        });

        /* The bfcache restores the DOM exactly as it was left, raised curtain
           included, and the returning visitor gets a blank screen. */
        window.addEventListener('pageshow', (ev) => {
            if (!ev.persisted) return;
            curtain.classList.remove('is-out', 'is-in', 'is-covered');
            try { sessionStorage.removeItem(FLAG); } catch (e) { }
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        mountGrid();
        mountCurtain();

        const scrollBtn = document.querySelector('.scroll-indicator');
        if (scrollBtn) {
            scrollBtn.addEventListener('click', () => {
                window.scrollTo({ top: window.innerHeight, behavior: 'smooth' });
            });
        }

        // ── Mobile hamburger nav toggle ──────────────────────────
        const navToggle = document.getElementById('dash-nav-toggle');
        const dashNav = document.getElementById('dash-nav');
        const navCurrentLabel = document.getElementById('dash-nav-current');

        if (navToggle && dashNav) {
            function closeNav() {
                dashNav.classList.remove('open');
                navToggle.setAttribute('aria-expanded', 'false');
                document.body.classList.remove('nav-open');
            }

            navToggle.addEventListener('click', () => {
                const isOpen = dashNav.classList.toggle('open');
                navToggle.setAttribute('aria-expanded', isOpen);
                document.body.classList.toggle('nav-open', isOpen);
            });

            // Close overlay when a nav item is clicked
            dashNav.querySelectorAll('.dash-nav-item').forEach(item => {
                item.addEventListener('click', closeNav);
            });

            // Update the toggle label to show the active section name
            function updateNavLabel() {
                const active = dashNav.querySelector('.dash-nav-item.active');
                if (active && navCurrentLabel) {
                    navCurrentLabel.textContent = active.textContent.trim();
                }
            }

            // Watch for active class changes via MutationObserver
            const observer = new MutationObserver(updateNavLabel);
            dashNav.querySelectorAll('.dash-nav-item').forEach(item => {
                observer.observe(item, { attributes: true, attributeFilter: ['class'] });
            });

            updateNavLabel();
        }
    });
})();
