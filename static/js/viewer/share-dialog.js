/* Share dialog: visibility, public link + QR, and secure (expiring / password /
 * edit) share links. Owner-only; the server enforces that on every endpoint.
 *
 * Share-link tokens are stored hashed server-side, so a link's URL exists only
 * in the response that created it. The dialog keeps it in memory for the
 * current session ("Copy now"); older links can be listed and revoked, not
 * re-copied.
 *
 * Usage: ArShareDialog.open({modelId, name, visibility, opener, onVisibilityChange})
 */
(function () {
    'use strict';

    const esc = (v) => (window.escapeHtml ? window.escapeHtml(v) : String(v == null ? '' : v)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'));

    const VISIBILITY = [
        ['private', 'Private', 'Only you can open this model. Use a secure link below to show it to someone.'],
        ['unlisted', 'Unlisted', 'Anyone with the link can open it. It is not listed in Community or search.'],
        ['public', 'Public', 'Anyone can find and open it, and it appears in Community.'],
    ];
    const EXPIRY = [['1', '1 hour'], ['24', '1 day'], ['168', '7 days'], ['720', '30 days'], ['', 'Never']];

    const CSS = `
.sd-backdrop{position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;padding:1rem;background:rgba(0,0,0,.6)}
.sd-card{width:min(34rem,100%);max-height:90vh;overflow-y:auto;background:var(--color-white,#fff);color:var(--color-gray-900,#111318);border:1px solid var(--color-gray-200,#dfe3e9);border-radius:12px;padding:1.25rem;font-size:.9rem;line-height:1.45}
.dark .sd-card{background:var(--color-gray-900,#111318);color:var(--color-gray-100,#eceef3);border-color:var(--color-gray-700,#30313a)}
.sd-head{display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;margin-bottom:.75rem}
.sd-head h2{margin:0;font-size:1.1rem}
.sd-sub{margin:.15rem 0 0;color:var(--color-gray-500,#626b78);font-size:.8rem;word-break:break-word}
.sd-sec{border-top:1px solid var(--color-gray-200,#dfe3e9);padding-top:.9rem;margin-top:.9rem}
.dark .sd-sec{border-color:var(--color-gray-700,#30313a)}
.sd-sec h3{margin:0 0 .5rem;font-size:.85rem;text-transform:uppercase;letter-spacing:.04em;color:var(--color-gray-500,#626b78)}
.sd-radio{display:flex;gap:.6rem;align-items:flex-start;padding:.45rem .5rem;border-radius:8px;cursor:pointer}
.sd-radio:hover{background:var(--color-gray-100,#eceef3)}
.dark .sd-radio:hover{background:var(--color-gray-800,#15161c)}
.sd-radio small{display:block;color:var(--color-gray-500,#626b78)}
.sd-row{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}
.sd-field{display:flex;flex-direction:column;gap:.2rem;flex:1;min-width:8rem}
.sd-field label{font-size:.75rem;color:var(--color-gray-500,#626b78)}
.sd-card input[type=text],.sd-card input[type=password],.sd-card select{width:100%;padding:.45rem .6rem;border:1px solid var(--color-gray-300,#c4c9d1);border-radius:8px;background:transparent;color:inherit;font:inherit}
.sd-btn{padding:.45rem .8rem;border-radius:8px;border:1px solid var(--color-gray-300,#c4c9d1);background:transparent;color:inherit;font:inherit;cursor:pointer;white-space:nowrap}
.sd-btn:hover{background:var(--color-gray-100,#eceef3)}
.dark .sd-btn:hover{background:var(--color-gray-800,#15161c)}
.sd-btn--primary{background:var(--color-gray-900,#111318);color:#fff;border-color:var(--color-gray-900,#111318)}
.sd-btn--primary:hover{background:var(--color-gray-700,#30313a)}
.sd-btn--danger{color:#b42318;border-color:#f1b8b2}
.sd-btn[disabled]{opacity:.55;cursor:not-allowed}
.sd-card :focus-visible{outline:2px solid #625df5;outline-offset:2px}
.sd-hint{margin:.4rem 0 0;color:var(--color-gray-500,#626b78);font-size:.8rem}
.sd-hint a{text-decoration:underline}
.sd-error{color:#b42318;font-size:.82rem;margin:.4rem 0 0}
.sd-qr{margin-top:.6rem;display:inline-block;padding:6px;background:#fff;border-radius:8px;line-height:0}
.sd-qr canvas{display:none!important}.sd-qr img{display:block!important;width:140px;height:140px}
.sd-new{margin-top:.6rem;padding:.6rem;border-radius:8px;background:var(--color-gray-100,#eceef3)}
.dark .sd-new{background:var(--color-gray-800,#15161c)}
.sd-links{list-style:none;margin:.6rem 0 0;padding:0}
.sd-link{display:flex;justify-content:space-between;align-items:center;gap:.5rem;padding:.5rem 0;border-top:1px solid var(--color-gray-200,#dfe3e9);flex-wrap:wrap}
.dark .sd-link{border-color:var(--color-gray-700,#30313a)}
.sd-link small{display:block;color:var(--color-gray-500,#626b78)}
.sd-visually-hidden{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
`;

    let ctx = null; // state of the currently open dialog

    function injectCss() {
        if (document.getElementById('sdStyles')) return;
        const style = document.createElement('style');
        style.id = 'sdStyles';
        style.textContent = CSS;
        document.head.appendChild(style);
    }

    function toast(message, type) {
        if (typeof window.displayToast === 'function') window.displayToast(message, type || 'success');
    }

    function copyText(text) {
        const done = () => toast('Link copied to clipboard');
        if (navigator.clipboard && window.isSecureContext) {
            return navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
        }
        return fallbackCopy(text, done);
    }

    function fallbackCopy(text, done) {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); done(); } catch (e) { toast('Could not copy - select the link and copy it manually', 'error'); }
        ta.remove();
    }

    async function api(path, options) {
        const res = await fetch(path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, options));
        let body = {};
        try { body = await res.json(); } catch (e) { /* non-JSON */ }
        if (!res.ok) {
            const err = new Error(body.error || ('Request failed (' + res.status + ')'));
            err.body = body;
            throw err;
        }
        return body;
    }

    function ensureQrLib() {
        if (typeof QRCode !== 'undefined') return Promise.resolve();
        return new Promise((resolve, reject) => {
            const s = document.createElement('script');
            s.src = '/static/js/qrcode.min.js';
            s.onload = resolve;
            s.onerror = reject;
            document.head.appendChild(s);
        });
    }

    function fmtDate(iso) {
        if (!iso) return null;
        const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
        return isNaN(d) ? null : d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
    }

    function build() {
        const backdrop = document.createElement('div');
        backdrop.className = 'sd-backdrop';
        backdrop.innerHTML = `
<div class="sd-card" role="dialog" aria-modal="true" aria-labelledby="sdTitle" tabindex="-1">
  <div class="sd-head">
    <div><h2 id="sdTitle">Share model</h2><p class="sd-sub" id="sdModelName"></p></div>
    <button type="button" class="sd-btn" id="sdClose" aria-label="Close share dialog">Close</button>
  </div>
  <section aria-labelledby="sdVisH">
    <h3 id="sdVisH">Who can view</h3>
    <div id="sdVisibility" role="radiogroup" aria-labelledby="sdVisH"></div>
    <p class="sd-error" id="sdVisError" role="alert" hidden></p>
  </section>
  <section class="sd-sec" id="sdLinkSec" aria-labelledby="sdLinkH">
    <h3 id="sdLinkH">Link</h3>
    <div id="sdLinkBody"></div>
  </section>
  <section class="sd-sec" aria-labelledby="sdSecureH">
    <h3 id="sdSecureH">Secure links</h3>
    <p class="sd-hint" style="margin-top:0">Give a specific person access, even when the model is private. Revoke a link at any time.</p>
    <form id="sdCreateForm" class="sd-row" style="margin-top:.6rem;align-items:flex-end" novalidate>
      <div class="sd-field"><label for="sdPerm">Access</label>
        <select id="sdPerm"><option value="view">Can view</option><option value="edit">Can edit</option></select></div>
      <div class="sd-field"><label for="sdExpiry">Expires</label>
        <select id="sdExpiry"></select></div>
      <div class="sd-field"><label for="sdPassword">Password (optional)</label>
        <input id="sdPassword" type="password" autocomplete="new-password" aria-describedby="sdPwHint"></div>
      <button type="submit" class="sd-btn sd-btn--primary" id="sdCreate">Create link</button>
    </form>
    <p class="sd-hint" id="sdPwHint"></p>
    <p class="sd-error" id="sdCreateError" role="alert" hidden></p>
    <div id="sdNew" class="sd-new" hidden></div>
    <h3 style="margin-top:1rem">Active links</h3>
    <ul class="sd-links" id="sdList" aria-live="polite"></ul>
  </section>
</div>`;
        return backdrop;
    }

    function setError(el, message) {
        el.textContent = message || '';
        el.hidden = !message;
    }

    function renderVisibility() {
        const box = ctx.root.querySelector('#sdVisibility');
        box.innerHTML = VISIBILITY.map(([value, label, help]) =>
            `<label class="sd-radio"><input type="radio" name="sdVis" value="${esc(value)}"${ctx.visibility === value ? ' checked' : ''}>
            <span><strong>${esc(label)}</strong><small>${esc(help)}</small></span></label>`).join('');
        box.querySelectorAll('input').forEach((input) => input.addEventListener('change', () => setVisibility(input.value)));
    }

    async function setVisibility(value) {
        const err = ctx.root.querySelector('#sdVisError');
        const previous = ctx.visibility;
        setError(err, '');
        try {
            await api('/api/models/' + encodeURIComponent(ctx.modelId) + '/sharing', {
                method: 'PATCH', body: JSON.stringify({ visibility: value }),
            });
            ctx.visibility = value;
            if (typeof ctx.onVisibilityChange === 'function') ctx.onVisibilityChange(value);
            toast('Visibility updated');
        } catch (e) {
            ctx.visibility = previous;
            setError(err, e.message);
        }
        renderVisibility();
        renderLink();
    }

    function renderLink() {
        const body = ctx.root.querySelector('#sdLinkBody');
        if (ctx.visibility === 'private') {
            body.innerHTML = '<p class="sd-hint" style="margin-top:0">This model is private, so its plain link only works for you. Switch to Unlisted or Public above, or create a secure link below.</p>';
            return;
        }
        const url = location.origin + '/view/' + encodeURIComponent(ctx.modelId);
        body.innerHTML = `<div class="sd-row"><input type="text" readonly id="sdUrl" aria-label="Model link" value="${esc(url)}" style="flex:1">
            <button type="button" class="sd-btn" id="sdCopyUrl">Copy link</button></div>
            <div class="sd-qr" id="sdQr" role="img" aria-label="QR code for the model link"></div>`;
        body.querySelector('#sdCopyUrl').addEventListener('click', () => copyText(url));
        body.querySelector('#sdUrl').addEventListener('focus', (e) => e.target.select());
        ensureQrLib().then(() => {
            const qr = body.querySelector('#sdQr');
            if (qr && !qr.firstChild) new QRCode(qr, { text: url, width: 140, height: 140, colorDark: '#000000', colorLight: '#ffffff' });
        }).catch(() => { const qr = body.querySelector('#sdQr'); if (qr) qr.remove(); });
    }

    function renderPasswordGate() {
        const pw = ctx.root.querySelector('#sdPassword');
        const hint = ctx.root.querySelector('#sdPwHint');
        if (ctx.passwordAllowed) {
            pw.disabled = false;
            hint.textContent = 'Visitors must enter the password before the model opens.';
        } else {
            pw.disabled = true;
            hint.innerHTML = 'Password-protected links are a Pro feature. <a href="/pricing?upgrade_reason=password_protected_shares">See plans</a>';
        }
    }

    function permLabel(p) { return p === 'edit' ? 'Can edit' : 'Can view'; }

    function renderList() {
        const list = ctx.root.querySelector('#sdList');
        if (!ctx.links.length) {
            list.innerHTML = '<li class="sd-hint">No active secure links.</li>';
            return;
        }
        list.innerHTML = '';
        ctx.links.forEach((link) => {
            const li = document.createElement('li');
            li.className = 'sd-link';
            const expires = fmtDate(link.expires_at);
            const created = fmtDate(link.created_at);
            const info = document.createElement('div');
            info.innerHTML = `<strong>${esc(permLabel(link.permission))}</strong>${link.has_password ? ' &middot; password' : ''}
                <small>${created ? 'Created ' + esc(created) + ' &middot; ' : ''}${expires ? 'Expires ' + esc(expires) : 'No expiry'}</small>`;
            li.appendChild(info);
            const actions = document.createElement('div');
            actions.className = 'sd-row';
            const url = ctx.urls[link.id];
            if (url) {
                const copy = document.createElement('button');
                copy.type = 'button';
                copy.className = 'sd-btn';
                copy.textContent = 'Copy';
                copy.addEventListener('click', () => copyText(url));
                actions.appendChild(copy);
            }
            const revoke = document.createElement('button');
            revoke.type = 'button';
            revoke.className = 'sd-btn sd-btn--danger';
            revoke.textContent = 'Revoke';
            revoke.setAttribute('aria-label', 'Revoke ' + permLabel(link.permission).toLowerCase() + ' link');
            revoke.addEventListener('click', () => revokeLink(link, revoke));
            actions.appendChild(revoke);
            li.appendChild(actions);
            list.appendChild(li);
        });
    }

    async function loadLinks() {
        try {
            const data = await api('/api/models/' + encodeURIComponent(ctx.modelId) + '/share-links');
            ctx.links = data.links || [];
            ctx.passwordAllowed = !!data.password_allowed;
        } catch (e) {
            ctx.links = [];
            setError(ctx.root.querySelector('#sdCreateError'), 'Could not load share links: ' + e.message);
        }
        renderPasswordGate();
        renderList();
    }

    async function revokeLink(link, button) {
        button.disabled = true;
        try {
            await api('/api/models/' + encodeURIComponent(ctx.modelId) + '/share-links/' + link.id, { method: 'DELETE' });
            delete ctx.urls[link.id];
            const newBox = ctx.root.querySelector('#sdNew');
            if (newBox.dataset.linkId === String(link.id)) newBox.hidden = true;
            ctx.links = ctx.links.filter((l) => l.id !== link.id);
            renderList();
            toast('Link revoked');
        } catch (e) {
            button.disabled = false;
            setError(ctx.root.querySelector('#sdCreateError'), e.message);
        }
    }

    async function createLink(event) {
        event.preventDefault();
        const err = ctx.root.querySelector('#sdCreateError');
        const btn = ctx.root.querySelector('#sdCreate');
        const pwInput = ctx.root.querySelector('#sdPassword');
        const expiry = ctx.root.querySelector('#sdExpiry').value;
        const payload = {
            permission: ctx.root.querySelector('#sdPerm').value,
            expires_in_hours: expiry === '' ? null : Number(expiry),
        };
        if (pwInput.value && !pwInput.disabled) payload.password = pwInput.value;
        setError(err, '');
        btn.disabled = true;
        try {
            const data = await api('/api/models/' + encodeURIComponent(ctx.modelId) + '/share-links', {
                method: 'POST', body: JSON.stringify(payload),
            });
            ctx.urls[data.id] = data.url;
            pwInput.value = '';
            showNewLink(data);
            await loadLinks();
        } catch (e) {
            setError(err, e.message);
        } finally {
            btn.disabled = false;
        }
    }

    function showNewLink(data) {
        const box = ctx.root.querySelector('#sdNew');
        box.dataset.linkId = String(data.id);
        box.innerHTML = `<strong>Link created.</strong> Copy it now - for security it can't be shown again after you close this dialog.
            <div class="sd-row" style="margin-top:.4rem"><input type="text" readonly aria-label="New share link" value="${esc(data.url)}" style="flex:1">
            <button type="button" class="sd-btn sd-btn--primary">Copy link</button></div>`;
        box.hidden = false;
        box.querySelector('input').addEventListener('focus', (e) => e.target.select());
        box.querySelector('button').addEventListener('click', () => copyText(data.url));
        box.querySelector('button').focus();
    }

    function focusables() {
        return Array.from(ctx.root.querySelectorAll('button, input, select, a[href], [tabindex]:not([tabindex="-1"])'))
            .filter((el) => !el.disabled && !el.hidden && el.offsetParent !== null);
    }

    function onKeydown(e) {
        if (!ctx) return;
        if (e.key === 'Escape') { e.preventDefault(); close(); return; }
        if (e.key !== 'Tab') return;
        const items = focusables();
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && (document.activeElement === first || document.activeElement === ctx.root.firstElementChild)) {
            e.preventDefault(); last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault(); first.focus();
        }
    }

    function close() {
        if (!ctx) return;
        document.removeEventListener('keydown', onKeydown, true);
        const { root, opener } = ctx;
        root.remove();
        document.body.style.overflow = ctx.prevOverflow;
        ctx = null;
        if (opener && document.contains(opener)) opener.focus();
    }

    function open(opts) {
        if (ctx) return;
        injectCss();
        const root = build();
        document.body.appendChild(root);
        ctx = {
            root, modelId: opts.modelId, visibility: opts.visibility || 'private',
            onVisibilityChange: opts.onVisibilityChange, opener: opts.opener || document.activeElement,
            links: [], urls: {}, passwordAllowed: false, prevOverflow: document.body.style.overflow,
        };
        document.body.style.overflow = 'hidden';
        root.querySelector('#sdModelName').textContent = opts.name || '';
        root.querySelector('#sdExpiry').innerHTML = EXPIRY.map(([v, l]) =>
            `<option value="${esc(v)}"${v === '168' ? ' selected' : ''}>${esc(l)}</option>`).join('');
        root.querySelector('#sdClose').addEventListener('click', close);
        root.addEventListener('mousedown', (e) => { if (e.target === root) close(); });
        root.querySelector('#sdCreateForm').addEventListener('submit', createLink);
        document.addEventListener('keydown', onKeydown, true);
        renderVisibility();
        renderLink();
        renderPasswordGate();
        renderList();
        root.querySelector('.sd-card').focus();
        loadLinks();
    }

    window.ArShareDialog = { open, close };

    // Any element with data-share-dialog opens the dialog; the library card menu
    // and the viewer toolbar share this one entry point.
    document.addEventListener('click', (e) => {
        const trigger = e.target.closest && e.target.closest('[data-share-dialog]');
        if (!trigger) return;
        e.preventDefault();
        e.stopPropagation();
        const modelId = trigger.dataset.modelId;
        const select = document.querySelector('.visibility-select[data-model-id="' + modelId + '"]');
        const details = trigger.closest('details');
        if (details) details.removeAttribute('open');
        open({
            modelId,
            name: trigger.dataset.modelName || '',
            visibility: (select && select.value) || trigger.dataset.visibility || 'private',
            opener: trigger,
            onVisibilityChange: (value) => {
                trigger.dataset.visibility = value;
                if (select) select.value = value;
            },
        });
    });
})();
