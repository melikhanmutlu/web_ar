// Camera Overlay mode: show the live rear camera behind the (transparent)
// model-viewer canvas, WITHOUT any AR plane anchoring. Lets the user hold
// the phone up to a real object and freely rotate/zoom the model over it
// (e.g. "will this printed part fit on my tool?") on ANY device — no
// ARCore/ARKit/WebXR needed, works on iPhone too.
//
// Honest tradeoff vs real AR: without depth tracking the scale is manual
// (pinch to match), so the hint chip shows the model's real dimensions to
// line things up against.
document.addEventListener('DOMContentLoaded', () => {
    const button = document.getElementById('cameraOverlayButton');
    const modelViewer = document.getElementById('modelViewer');
    const stage = document.querySelector('.viewer-stage');
    if (!button || !modelViewer || !stage) return;

    let stream = null;
    let videoEl = null;
    let hintEl = null;
    let savedStageBg = '';
    let active = false;
    let entering = false; // guards the async getUserMedia window against double-clicks

    function buildHint() {
        hintEl = document.createElement('div');
        hintEl.id = 'cameraOverlayHint';
        hintEl.className = 'camera-overlay-hint';
        hintEl.textContent = 'Rotate and pinch the model to line it up with the real object.';
        document.body.appendChild(hintEl);
        // Real dimensions give the user a scale reference, since this mode
        // (by design) has no automatic real-world scaling.
        fetch(`/get_model_dimensions/${window.VIEWER_CONFIG.modelId}`)
            .then((r) => r.json())
            .then((data) => {
                const d = data && data.dimensions;
                if (hintEl && d && d.width != null) {
                    const fmt = (v) => Number(v).toFixed(1);
                    hintEl.textContent =
                        `Real size: ${fmt(d.width)} × ${fmt(d.height)} × ${fmt(d.depth)} cm — rotate freely, pinch to match the scale.`;
                }
            })
            .catch(() => {});
    }

    async function enter() {
        // A second click while getUserMedia is still pending would open a
        // second stream and orphan the first <video> with a live, unstoppable
        // camera track. Ignore re-entry until this attempt resolves.
        if (entering || active) return;
        entering = true;
        let openedStream;
        try {
            openedStream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: 'environment' },
                audio: false,
            });
        } catch (err) {
            entering = false;
            alert(err && err.name === 'NotAllowedError'
                ? 'Camera permission was denied — allow camera access for this site and try again.'
                : 'No camera could be opened on this device, so overlay mode is unavailable.');
            return;
        }
        stream = openedStream;
        videoEl = document.createElement('video');
        videoEl.id = 'cameraOverlayVideo';
        videoEl.autoplay = true;
        videoEl.muted = true;
        videoEl.setAttribute('playsinline', ''); // iOS: stay inline, don't hijack fullscreen
        videoEl.srcObject = stream;
        stage.insertBefore(videoEl, stage.firstChild);

        savedStageBg = stage.style.background;
        stage.style.background = 'transparent';
        document.body.classList.add('camera-overlay-active');
        buildHint();
        button.classList.add('is-active');
        active = true;
        entering = false;
    }

    function exit() {
        stream?.getTracks().forEach((t) => t.stop());
        stream = null;
        videoEl?.remove();
        videoEl = null;
        hintEl?.remove();
        hintEl = null;
        stage.style.background = savedStageBg;
        document.body.classList.remove('camera-overlay-active');
        button.classList.remove('is-active');
        active = false;
    }

    button.addEventListener('click', () => (active ? exit() : enter()));

    // Cross-file bridge: entering fullscreen only fullscreens <model-viewer>,
    // not this sibling <video>, so the camera would keep running invisibly
    // behind a blank fullscreen background. fullscreen-modal.js calls this
    // first so the overlay is off before that happens.
    window._exitCameraOverlay = function() {
        if (active) exit();
    };

    // Never leave the camera running when the page goes away.
    window.addEventListener('pagehide', () => { if (active) exit(); });
});
