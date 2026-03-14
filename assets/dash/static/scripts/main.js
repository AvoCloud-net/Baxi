document.addEventListener('DOMContentLoaded', () => {
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
