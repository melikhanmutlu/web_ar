document.addEventListener('DOMContentLoaded', () => {
    const modelViewer = document.querySelector('model-viewer');

        // ===================================================================
        // RESET CAMERA
        // ===================================================================
        document.getElementById('resetCamera')?.addEventListener('click', () => {
            if (!modelViewer) return;
            modelViewer.cameraOrbit = '36deg 70deg auto';
            modelViewer.fieldOfView = '24deg';
            modelViewer.cameraTarget = 'auto auto auto';
        });

        // ===================================================================
        // CAMERA PRESETS (Front / Back / Left / Right / Top / Bottom)
        // ===================================================================
        // Keeps the model's current zoom (radius) — only theta/phi change —
        // so switching presets doesn't reset how close the user zoomed in.
        document.querySelectorAll('.camera-preset-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                if (!modelViewer) return;
                const theta = btn.dataset.theta;
                const phi = btn.dataset.phi;
                let radius = 'auto';
                try {
                    const current = modelViewer.getCameraOrbit?.();
                    if (current && current.radius) radius = current.radius + 'm';
                } catch (e) { /* keep auto */ }
                modelViewer.cameraOrbit = theta + 'deg ' + phi + 'deg ' + radius;
            });
        });


        // ===================================================================
        // AR PLACEMENT (floor / wall / ceiling)
        // ===================================================================
        document.getElementById('arPlacementSelect')?.addEventListener('change', (e) => {
            const value = e.target.value;
            if (modelViewer) modelViewer.setAttribute('ar-placement', value);
            fetch(`/api/models/${window.VIEWER_CONFIG.modelId}/viewer-settings`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ar_placement: value }),
            }).catch(() => {});
        });

        // TOOLS PANEL NAVIGATION (menu list ↔ full-height section detail)
        // ===================================================================
        (function() {
            const sectionsRoot = document.getElementById('toolsSections');
            const backBar = document.getElementById('toolsDetailBack');
            const backBtn = document.getElementById('toolsDetailBackBtn');
            const titleEl = document.getElementById('toolsDetailTitle');
            if (!sectionsRoot) return;

            function allSections() {
                return Array.from(sectionsRoot.querySelectorAll(':scope > .tp-section'));
            }

            function showToolsMenu() {
                sectionsRoot.dataset.activeSection = '';
                allSections().forEach(sec => {
                    sec.classList.remove('is-active');
                    sec.querySelector(':scope > .tp-section-header')?.classList.remove('is-open');
                    sec.querySelector(':scope > .tp-section-body')?.classList.remove('is-open');
                });
                backBar?.classList.remove('is-visible');
                document.getElementById('toolsPanelBody')?.scrollTo?.(0, 0);
            }

            function showToolsDetail(sectionEl) {
                if (!sectionEl) return;
                sectionsRoot.dataset.activeSection = sectionEl.id || 'active';
                allSections().forEach(sec => sec.classList.toggle('is-active', sec === sectionEl));
                sectionEl.querySelector(':scope > .tp-section-header')?.classList.add('is-open');
                sectionEl.querySelector(':scope > .tp-section-body')?.classList.add('is-open');
                if (titleEl) titleEl.textContent = sectionEl.querySelector(':scope > .tp-section-header span')?.textContent || '';
                backBar?.classList.add('is-visible');
                document.getElementById('toolsPanelBody')?.scrollTo?.(0, 0);
            }

            allSections().forEach(sec => {
                sec.querySelector(':scope > .tp-section-header')?.addEventListener('click', () => showToolsDetail(sec));
            });
            backBtn?.addEventListener('click', showToolsMenu);

            window._toolsShowMenu = showToolsMenu;
            window._toolsShowDetail = function (sectionId) {
                showToolsDetail(document.getElementById(sectionId));
            };
        })();

        // SIDEBAR TOGGLE
        // ===================================================================
        (function() {
            const sidebar = document.getElementById('rightSidebar');
            const backdrop = document.getElementById('mobileSidebarBackdrop');
            const mobileFab = document.getElementById('mobileEditFab');
            const isMobile = () => window.innerWidth <= 1024;

            function setSidebar(open) {
                if (!sidebar) return;
                sidebar.classList.remove('sidebar-collapsed');
                sidebar.classList.toggle('is-open', open || !isMobile());
                backdrop?.classList.toggle('is-visible', isMobile() && open);
                document.body.classList.toggle('mobile-sidebar-open', isMobile() && open);
                mobileFab?.setAttribute('aria-expanded', open ? 'true' : 'false');
            }

            function syncSidebarMode() {
                setSidebar(!isMobile());
            }

            syncSidebarMode();

            mobileFab?.addEventListener('click', () => {
                setSidebar(true);
            });

            backdrop?.addEventListener('click', () => {
                if (isMobile()) setSidebar(false);
            });

            window.addEventListener('resize', syncSidebarMode);
            document.addEventListener('keydown', (event) => {
                if (event.key === 'Escape' && isMobile()) {
                    setSidebar(false);
                }
            });

            // ---- Collapse / Expand showcase card ----
            const showcaseCard = sidebar?.querySelector('.showcase-card');
            let isCardCollapsed = false;

                function collapseCard() {
                if (!showcaseCard || isCardCollapsed) return;
                isCardCollapsed = true;
                sidebar?.classList.add('info-hidden');
                showcaseCard.classList.add('is-collapsed');
                document.getElementById('infoToggleBtn')?.classList.remove('is-active');
                if (isMobile()) setSidebar(false);
            }

            function expandCard() {
                if (!showcaseCard || !isCardCollapsed) return;
                isCardCollapsed = false;
                sidebar?.classList.remove('info-hidden');
                showcaseCard.classList.remove('is-collapsed');
                document.getElementById('infoToggleBtn')?.classList.add('is-active');
                if (isMobile()) setSidebar(true);
            }

            window.toggleShowcaseCollapse = function() {
                if (isCardCollapsed) expandCard();
                else collapseCard();
            };
            // The toolbar Info button must be able to bring the card back after
            // it was collapsed via its X — openInfo() only clears `info-hidden`,
            // which left an `is-collapsed` card invisible with no way to expand.
            window._expandShowcaseCard = expandCard;

            // Mobile fab should also expand card if collapsed
            mobileFab?.addEventListener('click', () => {
                if (isCardCollapsed) expandCard();
            });
        })();

});
