(function () {
    "use strict";
    var orgId = document.querySelector("[data-org-id]").getAttribute("data-org-id");
    var base = "/api/organizations/" + encodeURIComponent(orgId);

    function api(method, url, body) {
        var opts = { method: method };
        if (body !== undefined) {
            opts.headers = { "Content-Type": "application/json" };
            opts.body = JSON.stringify(body);
        }
        return fetch(url, opts).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (b) { return { ok: r.ok, body: b }; });
        });
    }
    function done(r, okMessage, redirect) {
        if (r.ok) {
            if (redirect) { window.location.href = redirect; return; }
            if (okMessage) { try { sessionStorage.setItem("wsToast", okMessage); } catch (e) {} }
            window.location.reload();
        } else {
            window.arToast(r.body.error || "Something went wrong.", "error");
        }
    }
    try {
        var pending = sessionStorage.getItem("wsToast");
        if (pending) { sessionStorage.removeItem("wsToast"); window.arToast(pending, "info"); }
    } catch (e) {}

    function onSubmit(id, handler) {
        var form = document.getElementById(id);
        if (form) form.addEventListener("submit", function (e) { e.preventDefault(); handler(); });
    }
    function val(id) { return document.getElementById(id).value.trim(); }

    onSubmit("inviteForm", function () {
        api("POST", base + "/invites", { email: val("inviteEmail"), role: val("inviteRole") })
            .then(async function (r) {
                if (r.ok && r.body.link) {
                    await window.arPrompt("Email delivery is not configured. Send this link to the invitee yourself:", { label: "Invitation link", defaultValue: r.body.link, confirmLabel: "Done" });
                }
                done(r, "Invitation sent.");
            });
    });
    onSubmit("folderForm", function () {
        api("POST", base + "/folders", { name: val("folderName") }).then(function (r) { done(r, "Folder created."); });
    });
    onSubmit("domainForm", function () {
        api("POST", base + "/domains", { hostname: val("domainHost") }).then(function (r) { done(r, "Domain added. Create the DNS record, then verify."); });
    });
    onSubmit("brandingForm", function () {
        api("PATCH", base + "/branding", {
            name: val("brandName"),
            logo_url: val("brandLogo"),
            primary_color: document.getElementById("brandColor").value,
            hide_powered_by: document.getElementById("brandHide").checked
        }).then(function (r) { done(r, "Branding saved."); });
    });

    document.addEventListener("change", function (e) {
        var uid = e.target.getAttribute && e.target.getAttribute("data-member-role");
        if (!uid) return;
        api("PATCH", base + "/members/" + uid, { role: e.target.value }).then(function (r) { done(r, "Role updated."); });
    });

    document.addEventListener("click", async function (e) {
        var t = e.target.closest("button");
        if (!t) return;
        var id;
        if ((id = t.getAttribute("data-remove-member"))) {
            if (!await window.arConfirm("Remove " + t.getAttribute("data-name") + " from this organization?", { confirmLabel: "Remove", danger: true })) return;
            api("DELETE", base + "/members/" + id).then(function (r) { done(r, "Member removed."); });
        } else if ((id = t.getAttribute("data-revoke-invite"))) {
            api("DELETE", base + "/invites/" + id).then(function (r) { done(r, "Invitation revoked."); });
        } else if ((id = t.getAttribute("data-rename-folder"))) {
            var name = await window.arPrompt("Rename folder", { label: "Folder name", defaultValue: t.getAttribute("data-name"), confirmLabel: "Rename" });
            if (!name || !name.trim()) return;
            api("PATCH", base + "/folders/" + id, { name: name.trim() }).then(function (r) { done(r, "Folder renamed."); });
        } else if ((id = t.getAttribute("data-delete-folder"))) {
            if (!await window.arConfirm("Delete folder “" + t.getAttribute("data-name") + "”? Its models stay in the library.", { confirmLabel: "Delete", danger: true })) return;
            api("DELETE", base + "/folders/" + id).then(function (r) { done(r, "Folder deleted."); });
        } else if ((id = t.getAttribute("data-verify-domain"))) {
            t.disabled = true;
            api("POST", base + "/domains/" + id + "/verify").then(function (r) {
                t.disabled = false;
                done(r, "Domain verified.");
            });
        } else if ((id = t.getAttribute("data-delete-domain"))) {
            if (!await window.arConfirm("Remove " + t.getAttribute("data-name") + "?", { confirmLabel: "Remove", danger: true })) return;
            api("DELETE", base + "/domains/" + id).then(function (r) { done(r, "Domain removed."); });
        } else if (t.id === "leaveOrg") {
            if (!await window.arConfirm("Leave this organization? You will lose access to its shared models.", { confirmLabel: "Leave", danger: true })) return;
            api("POST", base + "/leave").then(function (r) { done(r, null, "/workspace"); });
        } else if (t.id === "transferOwner") {
            var sel = document.getElementById("transferTarget");
            var who = sel.options[sel.selectedIndex].text;
            if (!await window.arConfirm("Make " + who + " the owner? You become an admin, and the organization's plan limits follow the new owner.", { confirmLabel: "Transfer", danger: true })) return;
            api("POST", base + "/transfer", { user_id: parseInt(sel.value, 10) }).then(function (r) { done(r, "Ownership transferred."); });
        }
    });
})();
