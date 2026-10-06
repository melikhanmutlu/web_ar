(function () {
    "use strict";
    var esc = window.escapeHtml || function (s) { return String(s); };

    function reveal(el, label, value) {
        el.hidden = false;
        el.innerHTML = esc(label) + " <strong>" + esc(value) + "</strong> — copy it now, it won't be shown again.";
    }

    function jsonFetch(url, options) {
        return fetch(url, options).then(function (r) {
            return r.json().then(function (body) { return { ok: r.ok, body: body }; });
        });
    }

    // ---- Tokens ----
    var tokenForm = document.getElementById("tokenForm");
    var tokenList = document.getElementById("tokenList");

    function renderTokens(tokens) {
        if (!tokenList) return;
        if (!tokens.length) { tokenList.innerHTML = '<p class="field-help">No tokens yet.</p>'; return; }
        tokenList.innerHTML = tokens.map(function (t) {
            var meta = t.scopes.join(", ") + (t.revoked ? " · revoked" : "");
            var btn = t.revoked ? "" : '<button class="secondary-btn mini" data-revoke="' + t.id + '">Revoke</button>';
            return '<div class="dev-row"><div class="dev-row-main"><strong>' + esc(t.name) +
                '</strong> <code>' + esc(t.prefix) + '…</code><br><span class="field-help">' + esc(meta) +
                '</span></div><div class="dev-actions">' + btn + '</div></div>';
        }).join("");
    }

    function loadTokens() {
        jsonFetch("/api/tokens", {}).then(function (r) {
            if (r.ok) renderTokens(r.body.tokens || []);
        });
    }

    if (tokenForm) {
        tokenForm.addEventListener("submit", function (e) {
            e.preventDefault();
            var name = document.getElementById("tokenName").value.trim();
            var scopes = [].slice.call(tokenForm.querySelectorAll('input[type=checkbox]:checked')).map(function (c) { return c.value; });
            if (!name || !scopes.length) return;
            jsonFetch("/api/tokens", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: name, scopes: scopes })
            }).then(function (r) {
                if (r.ok && r.body.token) {
                    reveal(document.getElementById("tokenReveal"), "New token:", r.body.token);
                    document.getElementById("tokenName").value = "";
                    loadTokens();
                } else {
                    window.arToast(r.body.error || "Could not create token.", "error");
                }
            });
        });
    }
    if (tokenList) {
        tokenList.addEventListener("click", async function (e) {
            var id = e.target.getAttribute("data-revoke");
            if (!id) return;
            if (!await window.arConfirm("Revoke this token? Apps using it will stop working.", { confirmLabel: "Revoke", danger: true })) return;
            jsonFetch("/api/tokens/" + id, { method: "DELETE" }).then(loadTokens);
        });
        loadTokens();
    }

    // ---- Webhooks ----
    var webhookForm = document.getElementById("webhookForm");
    var webhookList = document.getElementById("webhookList");

    function renderWebhooks(hooks) {
        if (!webhookList) return;
        if (!hooks.length) { webhookList.innerHTML = '<p class="field-help">No webhooks yet.</p>'; return; }
        webhookList.innerHTML = hooks.map(function (h) {
            return '<div class="dev-row"><div class="dev-row-main"><strong>' + esc(h.url) +
                '</strong><br><span class="field-help">' + esc(h.event_types.join(", ")) +
                '</span></div><div class="dev-actions">' +
                '<button class="secondary-btn mini" data-rotate="' + h.id + '">Rotate secret</button>' +
                '<button class="secondary-btn mini" data-delhook="' + h.id + '">Delete</button></div></div>';
        }).join("");
    }

    function loadWebhooks() {
        jsonFetch("/api/webhooks", {}).then(function (r) {
            if (r.ok) renderWebhooks(r.body.webhooks || []);
        });
    }

    if (webhookForm) {
        webhookForm.addEventListener("submit", function (e) {
            e.preventDefault();
            var url = document.getElementById("webhookUrl").value.trim();
            var events = [].slice.call(webhookForm.querySelectorAll('input[type=checkbox]:checked')).map(function (c) { return c.value; });
            if (!url || !events.length) return;
            jsonFetch("/api/webhooks", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url: url, event_types: events })
            }).then(function (r) {
                if (r.ok && r.body.webhook) {
                    reveal(document.getElementById("webhookReveal"), "Signing secret:", r.body.webhook.secret);
                    document.getElementById("webhookUrl").value = "";
                    loadWebhooks();
                } else {
                    window.arToast(r.body.error || "Could not add webhook.", "error");
                }
            });
        });
    }
    if (webhookList) {
        webhookList.addEventListener("click", async function (e) {
            var del = e.target.getAttribute("data-delhook");
            var rot = e.target.getAttribute("data-rotate");
            if (del) {
                if (!await window.arConfirm("Delete this webhook?", { confirmLabel: "Delete", danger: true })) return;
                jsonFetch("/api/webhooks/" + del, { method: "DELETE" }).then(loadWebhooks);
            } else if (rot) {
                jsonFetch("/api/webhooks/" + rot + "/rotate-secret", { method: "POST" }).then(function (r) {
                    if (r.ok && r.body.secret) {
                        reveal(document.getElementById("webhookReveal"), "New signing secret:", r.body.secret);
                    }
                });
            }
        });
        loadWebhooks();
    }
})();
