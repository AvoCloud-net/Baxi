document.addEventListener('DOMContentLoaded', () => {
    const scrollBtn = document.querySelector('.scroll-indicator');
    if (scrollBtn) {
        scrollBtn.addEventListener('click', () => {
            window.scrollTo({ top: window.innerHeight, behavior: 'smooth' });
        });
    }
});
