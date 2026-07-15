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

    // Signed-in avatar dropdown: toggle + close on outside click / Escape.
    var userMenu = document.getElementById('userMenu');
    var userMenuToggle = document.getElementById('userMenuToggle');
    var userMenuDropdown = document.getElementById('userMenuDropdown');
    if (userMenu && userMenuToggle && userMenuDropdown) {
        var setUserMenuOpen = function (open) {
            userMenu.classList.toggle('is-open', open);
            userMenuToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
            userMenuDropdown.hidden = !open;
        };
        userMenuToggle.addEventListener('click', function (e) {
            e.stopPropagation();
            setUserMenuOpen(userMenuDropdown.hidden);
        });
        document.addEventListener('click', function (e) {
            if (!userMenuDropdown.hidden && !userMenu.contains(e.target)) {
                setUserMenuOpen(false);
            }
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && !userMenuDropdown.hidden) {
                setUserMenuOpen(false);
                userMenuToggle.focus();
            }
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

    // Homepage capability carousel: manual controls with responsive pages.
    var capabilityCarousel = document.querySelector('[data-cap-carousel]');
    if (capabilityCarousel) {
        var capabilityViewport = capabilityCarousel.querySelector('.capability-viewport');
        var capabilityTrack = capabilityCarousel.querySelector('.capability-track');
        var capabilityCards = Array.prototype.slice.call(capabilityCarousel.querySelectorAll('.capability-card'));
        var capabilityPrevious = capabilityCarousel.querySelector('[data-cap-prev]');
        var capabilityNext = capabilityCarousel.querySelector('[data-cap-next]');
        var capabilityPagination = capabilityCarousel.querySelector('.capability-pagination');
        var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        var carouselPages = 0;

        var capabilityStep = function () {
            if (!capabilityCards.length) return 0;
            var gap = parseFloat(window.getComputedStyle(capabilityTrack).gap) || 0;
            return capabilityCards[0].getBoundingClientRect().width + gap;
        };
        var capabilityMaxPage = function () {
            var step = capabilityStep();
            return step ? Math.max(0, Math.round((capabilityViewport.scrollWidth - capabilityViewport.clientWidth) / step)) : 0;
        };
        var capabilityCurrentPage = function () {
            var step = capabilityStep();
            return step ? Math.min(capabilityMaxPage(), Math.max(0, Math.round(capabilityViewport.scrollLeft / step))) : 0;
        };
        var renderCapabilityPagination = function () {
            var maxPage = capabilityMaxPage();
            var pageCount = maxPage + 1;
            if (carouselPages === pageCount) return;
            carouselPages = pageCount;
            capabilityPagination.innerHTML = '';
            for (var i = 0; i < pageCount; i++) {
                var dot = document.createElement('button');
                dot.type = 'button';
                dot.setAttribute('aria-label', 'Show capability group ' + (i + 1));
                dot.addEventListener('click', (function (page) {
                    return function () {
                        capabilityViewport.scrollTo({ left: capabilityStep() * page, behavior: reducedMotion ? 'auto' : 'smooth' });
                    };
                })(i));
                capabilityPagination.appendChild(dot);
            }
        };
        var updateCapabilityControls = function () {
            renderCapabilityPagination();
            var page = capabilityCurrentPage();
            var maxPage = capabilityMaxPage();
            capabilityPrevious.disabled = page === 0;
            capabilityNext.disabled = page === maxPage;
            Array.prototype.forEach.call(capabilityPagination.children, function (dot, index) {
                dot.classList.toggle('is-active', index === page);
                dot.setAttribute('aria-current', index === page ? 'true' : 'false');
            });
        };
        var moveCapabilityCarousel = function (direction) {
            var page = capabilityCurrentPage();
            capabilityViewport.scrollTo({
                left: capabilityStep() * Math.min(capabilityMaxPage(), Math.max(0, page + direction)),
                behavior: reducedMotion ? 'auto' : 'smooth'
            });
        };

        capabilityPrevious.addEventListener('click', function () { moveCapabilityCarousel(-1); });
        capabilityNext.addEventListener('click', function () { moveCapabilityCarousel(1); });
        capabilityViewport.addEventListener('scroll', updateCapabilityControls, { passive: true });
        window.addEventListener('resize', updateCapabilityControls);
        updateCapabilityControls();
    }
})();
