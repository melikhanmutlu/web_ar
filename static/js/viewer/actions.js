/* Delegated handlers for the data-action* attributes in view.html (see the
   arActions dispatcher in security-head.js). The CSP forbids inline on*=
   attributes. The viewer functions are looked up at click time: most of them
   are defined by deferred scripts that load after this one. */
(function () {
    var A = window.arActions;
    A.startEditTitle = function (e, el) { window.startEditTitle(el); };
    A.startEditDescription = function (e, el) { window.startEditDescription(el); };
    A.toggleShowcaseCollapse = function () { if (window.toggleShowcaseCollapse) window.toggleShowcaseCollapse(); };
    A.uploadTexture = function () { document.getElementById('textureUpload').click(); };
    A.removeTexture = function () { window.removeTexture(); };
    A.applySectionPreset = function (e, el) {
        window.applySectionPreset(el.dataset.axis, Number(el.dataset.value), el.dataset.side);
    };
    A.openVr = function (e, el) { window.open(el.dataset.href, '_blank'); };
    // "More models" gallery thumbnail failed to load: swap in a gradient tile with the file name.
    A.galleryThumbFailed = function (e, img) {
        var holder = img.parentElement;
        if (!holder) return;
        var color = img.dataset.color || '#667eea';
        var tile = document.createElement('div');
        tile.className = 'gallery-fallback';
        tile.style.background = 'linear-gradient(135deg,' + color + ' 0%,' + color + 'cc 100%)';
        var label = document.createElement('span');
        label.className = 'gallery-filename';
        label.textContent = img.dataset.label || '';
        tile.appendChild(label);
        holder.replaceChildren(tile);
    };
})();
