/* arvision admin panel behaviors.
 *
 * Mutations are plain fetch POSTs returning JSON; the CSRF header is added
 * automatically by the global fetch wrapper in _security_head.html. Pages
 * are server-rendered, so successful mutations simply reload.
 *
 * Buttons opt in via data attributes:
 *   data-action-url="/admin/..."   POST target (required)
 *   data-confirm="text"            open the shared confirm modal first
 *   data-confirm-typed="value"     additionally require typing `value`
 *   data-show-password             display response.temp_password instead of reloading
 *   data-redirect="/admin/..."     navigate there on success instead of reloading
 *
 * Bulk actions: wrap a checkbox table + its action bar in one
 * `.admin-bulk-scope` container.
 *   <input data-select-all>                     header "select all" checkbox
 *   <input data-row-select value="{{ id }}">    one per row
 *   [data-bulk-bar]                              bar shown when 1+ selected
 *   [data-bulk-count]                            text node updated with the count
 *   [data-bulk-action="/admin/..."]              button: POSTs {ids: [...]}
 *   [data-bulk-confirm="Do X to {n} items?"]      {n} is replaced with the count
 *   [data-bulk-confirm-typed="DELETE"]            optional typed confirmation
 */

(function () {
    'use strict';

    // Same toast idiom as my_models.js (kept local: extracting a shared file
    // would touch unrelated pages).
    function displayToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `library-toast library-toast--${type}`;
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }

    async function adminPost(url, body) {
        const init = { method: 'POST' };
        if (body !== undefined) {
            init.headers = { 'Content-Type': 'application/json' };
            init.body = JSON.stringify(body);
        }
        const response = await fetch(url, init);
        let data = {};
        try {
            data = await response.json();
        } catch (e) { /* non-JSON error page */ }
        if (!response.ok || data.success === false) {
            throw new Error(data.error || `Request failed (${response.status})`);
        }
        return data;
    }

    // ------------------------------------------------------------------
    // Shared confirm modal
    // ------------------------------------------------------------------
    const modal = document.getElementById('adminConfirmModal');
    const confirmText = document.getElementById('adminConfirmText');
    const confirmInput = document.getElementById('adminConfirmInput');
    const confirmResult = document.getElementById('adminConfirmResult');
    const confirmResultValue = document.getElementById('adminConfirmResultValue');
    const confirmOk = document.getElementById('adminConfirmOk');

    let pending = null; // { url, typed, showPassword }
    let lastFocusedElement = null;

    function getFocusableModalElements() {
        return Array.from(
            modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
        ).filter((el) => !el.disabled && el.offsetParent !== null);
    }

    function openModal(options) {
        pending = options;
        lastFocusedElement = document.activeElement;
        confirmText.textContent = options.message;
        confirmResult.style.display = 'none';
        confirmOk.style.display = '';
        confirmOk.disabled = false;
        if (options.typed) {
            confirmInput.style.display = '';
            confirmInput.value = '';
            confirmInput.placeholder = `type "${options.typed}" to confirm`;
            confirmOk.disabled = true;
        } else {
            confirmInput.style.display = 'none';
        }
        modal.style.display = 'block';
        (options.typed ? confirmInput : modal.querySelector('[data-confirm-cancel]')).focus();
    }

    function closeModal() {
        pending = null;
        modal.style.display = 'none';
        if (lastFocusedElement) lastFocusedElement.focus();
        lastFocusedElement = null;
    }

    if (confirmInput) {
        confirmInput.addEventListener('input', () => {
            if (pending && pending.typed) {
                confirmOk.disabled = confirmInput.value.trim() !== pending.typed;
            }
        });
    }

    if (modal) {
        modal.querySelectorAll('[data-confirm-cancel]').forEach((el) =>
            el.addEventListener('click', closeModal)
        );
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeModal();
        });
        document.addEventListener('keydown', (e) => {
            if (modal.style.display !== 'block') return;
            if (e.key === 'Escape') {
                e.preventDefault();
                closeModal();
                return;
            }
            if (e.key !== 'Tab') return;
            // Basic focus trap: keep Tab/Shift+Tab cycling within the modal.
            const focusable = getFocusableModalElements();
            if (!focusable.length) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        });
    }

    async function runAction(url, showPassword, redirect, body) {
        try {
            const data = await adminPost(url, body);
            if (showPassword && data.temp_password) {
                // Keep the modal open and surface the one-time password.
                confirmText.textContent = 'password reset successfully.';
                confirmInput.style.display = 'none';
                confirmResult.style.display = '';
                confirmResultValue.value = data.temp_password;
                confirmOk.style.display = 'none';
                modal.style.display = 'block';
                return;
            }
            closeModal();
            if (redirect) window.location.href = redirect;
            else window.location.reload();
        } catch (err) {
            closeModal();
            displayToast(err.message, 'error');
        }
    }

    if (confirmOk) {
        confirmOk.addEventListener('click', () => {
            if (!pending) return;
            const { url, showPassword, redirect, body } = pending;
            confirmOk.disabled = true;
            runAction(url, showPassword, redirect, body);
        });
    }

    document.addEventListener('click', (e) => {
        const button = e.target.closest('[data-action-url]');
        if (!button) return;
        e.preventDefault();
        const url = button.getAttribute('data-action-url');
        const message = button.getAttribute('data-confirm');
        const typed = button.getAttribute('data-confirm-typed');
        const showPassword = button.hasAttribute('data-show-password');
        const redirect = button.getAttribute('data-redirect');
        if (message) {
            openModal({ url, message, typed, showPassword, redirect });
        } else {
            runAction(url, showPassword, redirect);
        }
    });

    // ------------------------------------------------------------------
    // Bulk selection + bulk actions
    // ------------------------------------------------------------------
    function updateBulkBar(scope) {
        const bar = scope.querySelector('[data-bulk-bar]');
        if (!bar) return;
        const checked = scope.querySelectorAll('[data-row-select]:checked').length;
        bar.style.display = checked > 0 ? 'flex' : 'none';
        const countEl = bar.querySelector('[data-bulk-count]');
        if (countEl) countEl.textContent = `${checked} selected`;
    }

    document.querySelectorAll('.admin-bulk-scope').forEach((scope) => {
        const selectAll = scope.querySelector('[data-select-all]');
        if (selectAll) {
            selectAll.addEventListener('change', () => {
                scope.querySelectorAll('[data-row-select]').forEach((cb) => {
                    cb.checked = selectAll.checked;
                });
                updateBulkBar(scope);
            });
        }
        scope.querySelectorAll('[data-row-select]').forEach((cb) => {
            cb.addEventListener('change', () => {
                if (!cb.checked && selectAll) selectAll.checked = false;
                updateBulkBar(scope);
            });
        });
    });

    document.addEventListener('click', (e) => {
        const button = e.target.closest('[data-bulk-action]');
        if (!button) return;
        e.preventDefault();
        const scope = button.closest('.admin-bulk-scope');
        if (!scope) return;
        const ids = Array.from(scope.querySelectorAll('[data-row-select]:checked')).map(
            (cb) => cb.value
        );
        if (!ids.length) return;

        const url = button.getAttribute('data-bulk-action');
        const template = button.getAttribute('data-bulk-confirm') || 'Apply this to {n} selected item(s)?';
        const message = template.replace('{n}', ids.length);
        const typed = button.getAttribute('data-bulk-confirm-typed');
        openModal({ url, message, typed, body: { ids } });
    });

    // ------------------------------------------------------------------
    // Sidebar toggle (mobile)
    // ------------------------------------------------------------------
    const menuToggle = document.getElementById('adminMenuToggle');
    const sidebar = document.getElementById('adminSidebar');
    if (menuToggle && sidebar) {
        menuToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            sidebar.classList.toggle('is-open');
        });
        document.addEventListener('click', (e) => {
            if (sidebar.classList.contains('is-open') && !sidebar.contains(e.target)) {
                sidebar.classList.remove('is-open');
            }
        });
    }

    // ------------------------------------------------------------------
    // Inline SVG bar charts: <div class="admin-chart" data-points='[{"d","v"},...]'>
    // ------------------------------------------------------------------
    function renderBarChart(el) {
        let points;
        try {
            points = JSON.parse(el.getAttribute('data-points') || '[]');
        } catch (e) {
            return;
        }
        if (!points.length) return;

        const width = 600;
        const height = 150;
        const padBottom = 18;
        const padTop = 14;
        const gap = 2;
        const barWidth = (width - gap * (points.length - 1)) / points.length;
        const maxValue = Math.max(1, ...points.map((p) => p.v));
        const chartHeight = height - padBottom - padTop;

        const svgNS = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(svgNS, 'svg');
        svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
        svg.setAttribute('preserveAspectRatio', 'none');
        svg.setAttribute('role', 'img');

        const baseline = document.createElementNS(svgNS, 'line');
        baseline.setAttribute('x1', 0);
        baseline.setAttribute('x2', width);
        baseline.setAttribute('y1', height - padBottom);
        baseline.setAttribute('y2', height - padBottom);
        baseline.setAttribute('class', 'baseline');
        svg.appendChild(baseline);

        points.forEach((p, i) => {
            const barHeight = Math.round((p.v / maxValue) * chartHeight);
            const x = i * (barWidth + gap);
            const bar = document.createElementNS(svgNS, 'rect');
            bar.setAttribute('x', x);
            bar.setAttribute('y', height - padBottom - barHeight);
            bar.setAttribute('width', Math.max(1, barWidth));
            bar.setAttribute('height', Math.max(p.v > 0 ? 2 : 0, barHeight));
            bar.setAttribute('class', 'bar');
            const title = document.createElementNS(svgNS, 'title');
            title.textContent = `${p.d}: ${p.v}`;
            bar.appendChild(title);
            svg.appendChild(bar);
        });

        // First / middle / last date labels
        [0, Math.floor(points.length / 2), points.length - 1].forEach((i, idx) => {
            const label = document.createElementNS(svgNS, 'text');
            label.setAttribute('y', height - 5);
            label.setAttribute('class', 'axis-label');
            if (idx === 0) label.setAttribute('x', 0);
            else if (idx === 1) {
                label.setAttribute('x', width / 2);
                label.setAttribute('text-anchor', 'middle');
            } else {
                label.setAttribute('x', width);
                label.setAttribute('text-anchor', 'end');
            }
            label.textContent = points[i].d;
            svg.appendChild(label);
        });

        el.innerHTML = '';
        el.appendChild(svg);
    }

    document.querySelectorAll('.admin-chart[data-points]').forEach(renderBarChart);
})();
