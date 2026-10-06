// Phones start on a lighter LOD (server-picked, see services/lod_delivery.py).
// The moment a visitor opens the Tools panel or the measure tool, switch to the
// full model so those tools work on real geometry. One-way and one-time.
(function () {
    const viewer = document.getElementById('modelViewer');
    const fullSrc = viewer && viewer.dataset.fullSrc;
    if (!fullSrc) return;

    function loadFullModel() {
        if (viewer.src !== fullSrc) viewer.src = fullSrc;
    }

    // Capture phase so the full model is already loading when the tool's own
    // handler runs.
    ['toolsPanelToggle', 'measureToolButton'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('click', loadFullModel, { capture: true, once: true });
    });
})();
