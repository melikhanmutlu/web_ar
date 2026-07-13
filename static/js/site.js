(function () {
    // Fixed nav: shrink + solid background after 24px of scroll.
    var nav = document.querySelector('.nav');
    if (nav) {
        var onScroll = function () {
            nav.classList.toggle('nav-scrolled', window.scrollY > 24);
        };
        window.addEventListener('scroll', onScroll, { passive: true });
        onScroll();
    }

    // Mobile hamburger: toggle the dropdown menu.
    var burger = document.getElementById('navBurger');
    var mobileMenu = document.getElementById('mobileMenu');
    if (burger && nav && mobileMenu) {
        burger.addEventListener('click', function () {
            var open = nav.classList.toggle('menu-open');
            burger.setAttribute('aria-expanded', open ? 'true' : 'false');
            mobileMenu.hidden = !open;
        });
    }

    // Scroll-reveal: single observer over all [data-reveal] nodes.
    var els = document.querySelectorAll('[data-reveal]');
    if (els.length) {
        if (!('IntersectionObserver' in window) ||
            window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            els.forEach(function (el) { el.classList.add('is-visible'); });
        } else {
            var obs = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting) {
                        entry.target.classList.add('is-visible');
                        obs.unobserve(entry.target);
                    }
                });
            }, { threshold: 0.12 });
            els.forEach(function (el) { obs.observe(el); });
        }
    }

    // Landing workflow section: 3-step tab switcher.
    var tabs = document.querySelectorAll('.workflow-tabs button');
    if (tabs.length) {
        var details = document.querySelectorAll('.workflow-detail');
        tabs.forEach(function (btn, i) {
            btn.addEventListener('click', function () {
                tabs.forEach(function (b) { b.classList.remove('active'); });
                btn.classList.add('active');
                details.forEach(function (d, j) {
                    d.classList.toggle('hidden', j !== i);
                });
            });
        });
    }
})();
