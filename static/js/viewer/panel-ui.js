document.addEventListener('DOMContentLoaded', () => {
        // ── Panel mutex helpers ──
        function openTools() {
            document.getElementById('toolsPanel')?.classList.add('is-open');
            document.getElementById('toolsPanelToggle')?.classList.add('is-active');
            lucide.createIcons();
            document.getElementById('rightSidebar')?.classList.add('info-hidden');
            document.getElementById('infoToggleBtn')?.classList.remove('is-active');
        }

        function closeTools() {
            document.getElementById('toolsPanel')?.classList.remove('is-open');
            document.getElementById('toolsPanelToggle')?.classList.remove('is-active');
        }

        function openInfo() {
            document.getElementById('rightSidebar')?.classList.remove('info-hidden');
            document.getElementById('infoToggleBtn')?.classList.add('is-active');
            // Also un-collapse the card if it was closed via its X button —
            // otherwise the sidebar becomes visible but the card stays at
            // opacity 0 and the Info button appears to do nothing.
            window._expandShowcaseCard?.();
            closeTools();
        }

        function closeInfo() {
            document.getElementById('rightSidebar')?.classList.add('info-hidden');
            document.getElementById('infoToggleBtn')?.classList.remove('is-active');
        }

        // Tools Panel close button
        document.getElementById('toolsPanelClose')?.addEventListener('click', closeTools);

        // Tools Panel toggle
        document.getElementById('toolsPanelToggle')?.addEventListener('click', function() {
            const isOpen = document.getElementById('toolsPanel')?.classList.contains('is-open');
            if (isOpen) closeTools(); else openTools();
        });

        // Info panel toggle
        document.getElementById('infoToggleBtn')?.addEventListener('click', function() {
            const isHidden = document.getElementById('rightSidebar')?.classList.contains('info-hidden');
            if (isHidden) openInfo(); else closeInfo();
        });

        // On mobile/tablet (<=1024) the info card is a drawer; start it closed so it
        // doesn't cover the model. Desktop keeps it open as a floating card.
        (function initInfoDrawer() {
            const mq = () => window.innerWidth <= 1024;
            let wasMobile = mq();
            if (wasMobile) closeInfo();
            window.addEventListener('resize', () => {
                // Mobile browsers fire 'resize' when the URL bar collapses or
                // the soft keyboard opens (e.g. tapping the inline title/
                // description editor) -- not just on an actual desktop<->mobile
                // width change. Only close the drawer on a real crossing, or
                // editing text would slam it shut mid-edit.
                const isMobile = mq();
                const sidebar = document.getElementById('rightSidebar');
                if (isMobile && !wasMobile && sidebar && !sidebar.classList.contains('info-hidden')) {
                    closeInfo();
                }
                wasMobile = isMobile;
            });
        })();

        document.documentElement.classList.remove('dark');
        localStorage.theme = 'light';

        lucide.createIcons();

        // ── Tagline typing effect ──────────────────────────────────────
        (function() {
            const words = ['Your Portfolio', 'Education', 'Medicine', 'Architecture', 'Engineering', 'Gaming', 'E-Commerce'];
            const el = document.querySelector('.tagline-main');
            if (!el) return;
            let wi = 0, ci = 0, deleting = false;
            const cursor = document.createElement('span');
            cursor.className = 'tagline-cursor';
            el.after(cursor);
            function tick() {
                const word = words[wi];
                el.textContent = deleting ? word.slice(0, ci--) : word.slice(0, ci++);
                if (!deleting && ci > word.length) { deleting = true; setTimeout(tick, 1600); return; }
                if (deleting && ci < 0) { deleting = false; wi = (wi + 1) % words.length; ci = 0; setTimeout(tick, 300); return; }
                setTimeout(tick, deleting ? 50 : 80);
            }
            tick();
        })();
});
