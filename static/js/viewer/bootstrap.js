/* Viewer bootstrap (sync, in <head>, before the other viewer scripts).
   1. Exposes the server-rendered values (<script id="viewer-config"> JSON) as
      window.VIEWER_CONFIG for the split-out static/js/viewer/*.js files.
      canEdit mirrors the backend's check_model_mutation_allowed: owner, or an
      anonymous model. Mutating UI (version restore/delete etc.) is only built
      when the server would actually accept the mutation.
   2. The anonymous uploader's edit_token arrives in the URL once (the session
      keeps the capability). Drop it from the address bar right away and make
      every shareable link (QR, copy) the canonical token-free URL. */
window.VIEWER_CONFIG = JSON.parse(document.getElementById('viewer-config').textContent);

window.canonicalViewerUrl = function () { return location.origin + location.pathname; };
(function () {
    try {
        var params = new URLSearchParams(location.search);
        if (params.has('edit_token')) {
            params.delete('edit_token');
            var qs = params.toString();
            history.replaceState(history.state, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
        }
    } catch (e) { /* non-critical */ }
})();
