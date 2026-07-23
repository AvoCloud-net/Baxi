/* avocloud CAD construction reveal — vanilla port of brand/motion/Wordmark.tsx
   (React + GSAP). Same measured geometry, same timeline, same timeScale 0.6.

   BRANDING §5 forbids a second hand-rolled version of this animation, so both
   call sites go through here: the post-login splash on dash_home.html and the
   hero on welcome.html. Which letters get an inscribed ring and which run
   coral is carried by the markup (data-round / .coral) rather than the
   component's ROUND and CORAL_FROM constants.

   Usage: avoWordmarkReveal(wrapEl, onDone)
     wrapEl  — the .hw wrapper holding the .hw-ch letter spans
     onDone  — called when the reveal finishes, AND when it is skipped
               (reduced motion, no GSAP, missing markup). Callers must treat
               it as "the wordmark is now in its final state", nothing more.

   Requires: GSAP on the page, and main.css for .hw-* / html.gsap-ready. */
window.avoWordmarkReveal = function (wrap, onDone) {
    var SVG_NS = 'http://www.w3.org/2000/svg';
    var finished = false;

    /* html.gsap-ready is the FOUC guard: it pre-hides .hw-fill so the solid
       wordmark never flashes before the reveal takes over. Dropping it is
       therefore load-bearing — leave it on after a failed or skipped reveal
       and the wordmark stays permanently invisible. Every exit path clears
       it, including the timeout below. */
    function unguard() {
        document.documentElement.classList.remove('gsap-ready');
    }

    function done() {
        if (finished) return;
        finished = true;
        unguard();
        if (typeof onDone === 'function') onDone();
    }

    // Reduced motion or no GSAP: straight to the end state, no static hold.
    if (!wrap || matchMedia('(prefers-reduced-motion: reduce)').matches || !window.gsap) {
        return done();
    }

    /* Fail-safe: document.fonts.load can hang on a blocked font host, and the
       page must not be left with an invisible wordmark because of it. */
    var failsafe = setTimeout(done, 6000);

    /* Guides are measured from the real glyph boxes — never hardcode a guide
       box, it drifts out of alignment as soon as the font or size changes. */
    function buildGuides(wrap) {
        var chs = [].slice.call(wrap.querySelectorAll('.hw-ch'));
        if (!chs.length) return null;
        var wr = wrap.getBoundingClientRect();
        var r = chs.map(function (c) {
            var b = c.getBoundingClientRect();
            return { left: b.left - wr.left, right: b.right - wr.left, top: b.top - wr.top, bottom: b.bottom - wr.top };
        });
        var tops = r.map(function (x) { return x.top; });
        var bottoms = r.map(function (x) { return x.bottom; });
        var lead = (r[0].bottom - r[0].top) * 0.11;
        var capTop = Math.min.apply(null, tops) + lead;
        var base = Math.max.apply(null, bottoms) - lead;
        var midY = (capTop + base) / 2;
        var left = r[0].left;
        var right = r[r.length - 1].right;
        var ext = wr.width * 0.05;

        var lines = [];
        [capTop, midY, base].forEach(function (y) {
            lines.push({ x1: left - ext, y1: y, x2: right + ext, y2: y });
        });
        lines.push({ x1: left, y1: capTop - ext * 0.5, x2: left, y2: base + ext * 0.5 });
        lines.push({ x1: right, y1: capTop - ext * 0.5, x2: right, y2: base + ext * 0.5 });
        for (var i = 0; i < r.length - 1; i++) {
            var x = (r[i].right + r[i + 1].left) / 2;
            lines.push({ x1: x, y1: capTop - ext * 0.25, x2: x, y2: base + ext * 0.25 });
        }
        lines.push({ x1: left, y1: capTop, x2: right, y2: base });
        lines.push({ x1: right, y1: capTop, x2: left, y2: base });

        // Dashed rings inscribing the round letters (O, C, D).
        var circles = [];
        chs.forEach(function (c, i) {
            if (c.dataset.round !== '1') return;
            circles.push({
                cx: (r[i].left + r[i].right) / 2,
                cy: (r[i].top + r[i].bottom) / 2,
                r: ((base - capTop) / 2) * 1.08,
                coral: c.classList.contains('coral')
            });
        });

        var svg = document.createElementNS(SVG_NS, 'svg');
        svg.setAttribute('class', 'hw-guides');
        svg.setAttribute('width', wr.width);
        svg.setAttribute('height', wr.height);
        svg.setAttribute('viewBox', '0 0 ' + wr.width + ' ' + wr.height);
        svg.setAttribute('aria-hidden', 'true');
        lines.forEach(function (l) {
            var el = document.createElementNS(SVG_NS, 'line');
            el.setAttribute('class', 'hw-line');
            el.setAttribute('x1', l.x1);
            el.setAttribute('y1', l.y1);
            el.setAttribute('x2', l.x2);
            el.setAttribute('y2', l.y2);
            el.setAttribute('pathLength', '1');
            el.setAttribute('vector-effect', 'non-scaling-stroke');
            svg.appendChild(el);
        });
        circles.forEach(function (c) {
            var el = document.createElementNS(SVG_NS, 'circle');
            el.setAttribute('class', 'hw-circ' + (c.coral ? ' coral' : ''));
            el.setAttribute('cx', c.cx);
            el.setAttribute('cy', c.cy);
            el.setAttribute('r', c.r);
            el.setAttribute('vector-effect', 'non-scaling-stroke');
            svg.appendChild(el);
        });
        wrap.insertBefore(svg, wrap.firstChild);
        return svg;
    }

    function play() {
        if (finished) return; // the fail-safe already fired
        clearTimeout(failsafe);
        buildGuides(wrap);

        var strokes = wrap.querySelectorAll('.hw-stroke');
        var fills = wrap.querySelectorAll('.hw-fill');
        var lines = wrap.querySelectorAll('.hw-line');
        var circles = wrap.querySelectorAll('.hw-circ');

        if (!fills.length) return done();

        gsap.set(fills, { clipPath: 'inset(100% 0 0 0)' });
        // The inline clip-path now owns the hidden state, so the CSS guard can
        // go — and with it the risk of it outliving the animation.
        unguard();
        gsap.set(strokes, { opacity: 0, yPercent: 8 });
        gsap.set(lines, { strokeDashoffset: 1, opacity: 0 });
        gsap.set(circles, { opacity: 0, transformOrigin: '50% 50%' });

        var tl = gsap.timeline({ delay: 0.15, onComplete: done });
        tl.set(lines, { opacity: 1 })
          .to(lines, { strokeDashoffset: 0, duration: 0.7, ease: 'power2.inOut', stagger: 0.025 }, 0)
          .fromTo(circles, { scale: 0.86 }, { opacity: 1, scale: 1, duration: 0.55, ease: 'power2.out', stagger: 0.06 }, 0.25)
          .to(strokes, { opacity: 1, yPercent: 0, duration: 0.4, ease: 'power2.out', stagger: 0.045 }, 0.4)
          .to(fills, { clipPath: 'inset(0% 0 0 0)', duration: 0.5, ease: 'power2.out', stagger: 0.055 }, 0.85)
          .to([lines, circles], { opacity: 0, duration: 0.7, ease: 'power2.inOut' }, 1.7)
          .to(strokes, { opacity: 0, duration: 0.7, ease: 'power2.inOut' }, 1.7);
        tl.timeScale(0.6); // the 1.0 default reads as rushed for this moment

        /* Hard fail-safe, independent of the animation library. A plugin that
           fails on a target, an exception in a callback, or a throttled tab
           whose requestAnimationFrame stops firing would otherwise leave the
           wordmark clipped to nothing forever — the fills are hidden by an
           inline clip-path only this timeline ever clears.

           The deadline comes from the timeline's REAL playback time, doubled.
           duration() alone reports the authored length and ignores the 0.6
           stretch, and a hardcoded number silently becomes a truncation the
           next time the sequence is retimed. */
        var deadline = (tl.duration() / tl.timeScale()) * 2 * 1000;
        setTimeout(function () {
            if (finished) return;
            tl.progress(1); // renders the end state synchronously
            done();
        }, deadline);
    }

    // Measure only once Syne is actually rendering, or the guides land on
    // fallback-font metrics.
    if (document.fonts && document.fonts.load) {
        document.fonts.load("800 1em 'Syne'").then(function () {
            requestAnimationFrame(function () { requestAnimationFrame(play); });
        }).catch(play);
    } else {
        play();
    }
};
