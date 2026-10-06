(function () {
    "use strict";
    var btn = document.getElementById("acceptInvite");
    if (!btn) return;
    btn.addEventListener("click", function () {
        btn.disabled = true;
        fetch("/api/invites/" + encodeURIComponent(btn.getAttribute("data-token")) + "/accept", { method: "POST" })
            .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); })
            .then(function (r) {
                if (r.ok) { window.location.href = btn.getAttribute("data-next"); return; }
                var err = document.getElementById("invite-error");
                err.textContent = r.body.error || "Could not accept the invitation.";
                err.hidden = false;
                btn.disabled = false;
            })
            .catch(function () { btn.disabled = false; });
    });
})();
