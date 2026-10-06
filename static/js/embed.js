// Embed page AR button (only included when AR is enabled for this embed).
(function () {
    const modelId = document.currentScript.dataset.modelId;
    const viewer = document.getElementById('viewer');
    const arBtn = document.getElementById('arBtn');

    viewer.addEventListener('load', () => {
        if (viewer.canActivateAR) {
            arBtn.style.display = 'flex';
        }
    });
    arBtn?.addEventListener('click', () => {
        fetch(`/api/models/${modelId}/events`, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({event_type: 'ar_launch', metadata: {source: 'embed'}})
        }).catch(() => {});
        viewer.activateAR();
    });
    // Reason-specific feedback isn't practical in this compact embed
    // surface (no modal chrome) -- a 'failed' status (commonly a denied
    // camera permission) at least surfaces a tooltip instead of
    // silently doing nothing.
    viewer.addEventListener('ar-status', (event) => {
        if (event.detail && event.detail.status === 'failed' && arBtn) {
            arBtn.title = 'AR failed to start - check your camera permission and try again';
        }
    });
})();
