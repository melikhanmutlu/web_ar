(function () {
    "use strict";
    var form = document.getElementById("createOrgForm");
    if (!form) return;
    form.addEventListener("submit", function (e) {
        e.preventDefault();
        var name = document.getElementById("orgName").value.trim();
        if (!name) return;
        fetch("/api/organizations", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: name })
        }).then(function (r) {
            return r.json().then(function (b) { return { ok: r.ok, body: b }; });
        }).then(function (r) {
            if (r.ok) { window.location.href = "/workspace/" + r.body.organization.id; }
            else { window.arToast(r.body.error || "Could not create the organization.", "error"); }
        });
    });
})();
