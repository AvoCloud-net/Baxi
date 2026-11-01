/* avocloud pixel field (BRANDING.md §7) — an ordered Bayer 4x4 dither drawn on a
   low-resolution <canvas> (one cell = 3 CSS px) and scaled up, so the cells stay
   square. Mount with <canvas class="px-canvas" data-dither aria-hidden="true">.
   One pixel moment per view, never behind data. Static under reduced motion,
   paused while hidden or off-screen. data-shape: "orb" (default) | "wave". */
(function () {
  var B = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map(function (v) { return (v + 0.5) / 16; });
  var CELL = 3;
  var reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  var css = getComputedStyle(document.documentElement);
  var COLOR = (css.getPropertyValue('--avo-dither') || '').trim() || '#7A4534';

  function field(shape, x, y, w, h, t) {
    if (shape === 'wave') {
      var base = 0.5 + Math.sin(x * 0.045 + t) * 0.18 + Math.sin(x * 0.11 - t * 0.7) * 0.06;
      return Math.max(0, 1 - Math.abs(y / h - base) * 4.5);
    }
    var cx = w * 0.78, cy = h * 0.34, R = Math.min(w, h) * 0.75;
    var v = Math.max(0, 1 - Math.hypot(x - cx, (y - cy) * 1.05) / R);
    if (v <= 0) return 0;   // the ripple only lives inside the orb, or sparse dots tile the empty area
    return v + (Math.sin(x * 0.12 + t) + Math.sin(y * 0.16 - t * 0.8)) * 0.05 * Math.min(1, v * 4);
  }

  function mount(c) {
    var g = c.getContext('2d'), shape = c.dataset.shape || 'orb';
    var w = 0, h = 0, t = 0, last = 0, raf = 0, visible = true;
    function size() {
      var r = c.getBoundingClientRect();
      w = Math.max(1, Math.ceil(r.width / CELL)); h = Math.max(1, Math.ceil(r.height / CELL));
      c.width = w; c.height = h;
    }
    function draw() {
      g.clearRect(0, 0, w, h); g.fillStyle = COLOR;
      for (var y = 0; y < h; y++) for (var x = 0; x < w; x++)
        if (field(shape, x, y, w, h, t) > B[(y & 3) * 4 + (x & 3)]) g.fillRect(x, y, 1, 1);
    }
    function loop(now) {
      raf = 0;
      if (!visible || document.hidden) return;
      if (now - last > 90) { t += 0.06; last = now; draw(); }
      raf = requestAnimationFrame(loop);
    }
    function start() { if (!reduce && !raf && visible && !document.hidden) raf = requestAnimationFrame(loop); }
    size(); draw();
    addEventListener('resize', function () { size(); draw(); });
    document.addEventListener('visibilitychange', start);
    if ('IntersectionObserver' in window)
      new IntersectionObserver(function (e) { visible = e[0].isIntersecting; if (visible) start(); }, { rootMargin: '100px' }).observe(c);
    start();
  }
  function init() { document.querySelectorAll('canvas[data-dither]').forEach(mount); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
