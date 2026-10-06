/* "Save your edit link" banner for anonymous uploaders. Model id and the
   private edit token come from data-* attributes on #anonOwnerBanner. */
(function () {
    var banner = document.getElementById('anonOwnerBanner');
    var key = 'anonBannerDismissed:' + banner.dataset.modelId;
    var token = banner.dataset.editToken;
    try { if (sessionStorage.getItem(key)) return; } catch (e) {}
    banner.hidden = false;
    document.getElementById('anonBannerDismiss').addEventListener('click', function () {
        banner.hidden = true;
        try { sessionStorage.setItem(key, '1'); } catch (e) {}
    });
    document.getElementById('anonCopyEditLink').addEventListener('click', function () {
        var link = location.origin + location.pathname + '?edit_token=' + encodeURIComponent(token);
        var btn = this;
        function ok() { btn.textContent = 'Edit link copied'; }
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(link).then(ok, function () { window.arPrompt('Copy your private edit link', { defaultValue: link, label: 'Private edit link', confirmLabel: 'Done' }); });
        } else { window.arPrompt('Copy your private edit link', { defaultValue: link, label: 'Private edit link', confirmLabel: 'Done' }); }
    });
})();
