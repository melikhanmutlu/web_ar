/* Viewer page chrome: mobile nav toggle, user menu, stage background switcher.
   Loaded synchronously at the end of <body> (site.js isn't loaded on the viewer page). */
// Mobile hamburger toggle (site.js isn't loaded on the viewer page).
(function () {
    var nav = document.getElementById('siteNav');
    var burger = document.getElementById('navBurger');
    var mobileMenu = document.getElementById('mobileMenu');
    if (nav && burger && mobileMenu) {
        burger.addEventListener('click', function () {
            var open = nav.classList.toggle('menu-open');
            burger.setAttribute('aria-expanded', open ? 'true' : 'false');
            mobileMenu.hidden = !open;
        });
    }
})();
// Signed-in avatar dropdown toggle (mirrors site.js).
(function () {
    var userMenu = document.getElementById('userMenu');
    var userMenuToggle = document.getElementById('userMenuToggle');
    var userMenuDropdown = document.getElementById('userMenuDropdown');
    if (!userMenu || !userMenuToggle || !userMenuDropdown) return;
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
})();
// Stage background switcher: client-side only, remembered per-browser
// via localStorage. Independent of the owner-only, DB-persisted
// viewer_settings.background_color used by the Embed panel.
(function () {
    var STORAGE_KEY = 'arvision.viewerBg';
    var BG_COLORS = { white: '#ffffff', dark: '#111318', black: '#0b0c10' };
    var stage = document.querySelector('.viewer-stage');
    var switcher = document.getElementById('bgSwitcher');
    var button = document.getElementById('bgSwitcherButton');
    var panel = document.getElementById('bgSwitcherPanel');
    if (!stage || !switcher || !button || !panel) return;
    var persistBackground = !window.VIEWER_CONFIG.isMarketingDemo;

    var swatches = panel.querySelectorAll('.bg-swatch');
    var applyBg = function (key) {
        if (!BG_COLORS[key]) return;
        stage.style.background = BG_COLORS[key];
        document.body.classList.toggle('viewer-stage-dark', key === 'dark' || key === 'black');
        swatches.forEach(function (sw) {
            sw.classList.toggle('is-active', sw.getAttribute('data-bg') === key);
        });
    };
    applyBg(persistBackground ? (localStorage.getItem(STORAGE_KEY) || 'dark') : 'dark');

    var setPanelOpen = function (open) {
        button.setAttribute('aria-expanded', open ? 'true' : 'false');
        panel.hidden = !open;
    };
    button.addEventListener('click', function (e) {
        e.stopPropagation();
        setPanelOpen(panel.hidden);
    });
    swatches.forEach(function (sw) {
        sw.addEventListener('click', function () {
            var key = sw.getAttribute('data-bg');
            applyBg(key);
            if (persistBackground) localStorage.setItem(STORAGE_KEY, key);
            setPanelOpen(false);
        });
    });
    document.addEventListener('click', function (e) {
        if (!panel.hidden && !switcher.contains(e.target)) setPanelOpen(false);
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !panel.hidden) {
            setPanelOpen(false);
            button.focus();
        }
    });
})();
