// Get all the necessary DOM elements
document.addEventListener('DOMContentLoaded', () => {
    const modelViewer = document.querySelector('model-viewer');
    const viewerStage = document.querySelector('.viewer-stage');
    const fullscreenButton = document.querySelector('#fullscreenButton');
    const downloadButton = document.querySelector('#downloadButton');
    const downloadFormatModal = document.querySelector('#downloadFormatModal');
    const downloadFormatModalOptions = document.querySelector('#downloadFormatModalOptions');
    const downloadFormatModalClose = document.querySelector('#downloadFormatModalClose');
    const screenshotButton = document.getElementById('screenshotButton');
    const modelInfoButton = document.querySelector('#modelInfoButton');
    const modelInfoModal = document.querySelector('#modelInfoModal');
    const closeModalButton = document.querySelector('#closeModalButton');
    const closeModalFooterButton = document.querySelector('#closeModalFooterButton');

    // Model Info Modal handlers
    modelInfoButton?.addEventListener('click', () => {
        modelInfoModal?.classList.remove('hidden');
    });

    closeModalButton?.addEventListener('click', () => {
        modelInfoModal?.classList.add('hidden');
    });

    closeModalFooterButton?.addEventListener('click', () => {
        modelInfoModal?.classList.add('hidden');
    });

    // Close modal when clicking outside
    modelInfoModal?.addEventListener('click', (e) => {
        if (e.target === modelInfoModal) {
            modelInfoModal.classList.add('hidden');
        }
    });

    // Close modal with Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modelInfoModal?.classList.contains('hidden')) {
            modelInfoModal?.classList.add('hidden');
        }
    });

    modelViewer?.addEventListener('load', () => {
        // Pre-initialize slicer internals (delay to let model-viewer finish setup)
        // Uses window. prefix because discoverInternals is defined in a separate scope
        setTimeout(() => {
            if (typeof window._slicerDiscoverInternals === 'function') {
                window._slicerDiscoverInternals();
                window._buildLayersList?.();
                setTimeout(() => { window._slicerDiscoverInternals?.(); window._buildLayersList?.(); }, 1000);
                setTimeout(() => { window._slicerDiscoverInternals?.(); window._buildLayersList?.(); }, 3000);
            }
        }, 500);
    });

    // Fullscreen button handler. iOS Safari has no Fullscreen API for
    // arbitrary elements (only <video>), and older WebKit needs the
    // webkit- prefix — fall through the variants instead of silently
    // console.error-ing while the button appears dead.
    fullscreenButton?.addEventListener('click', async () => {
        try {
            const fullscreenElement = document.fullscreenElement || document.webkitFullscreenElement;
            if (fullscreenElement) {
                await (document.exitFullscreen?.() ?? document.webkitExitFullscreen?.());
                return;
            }
            // Camera overlay mode fullscreens <model-viewer> only; its sibling
            // <video> would be left running behind a blank background.
            window._exitCameraOverlay?.();
            if (modelViewer.requestFullscreen) {
                await modelViewer.requestFullscreen();
            } else if (modelViewer.webkitRequestFullscreen) {
                await modelViewer.webkitRequestFullscreen();
            } else {
                alert('Fullscreen is not supported by this browser. On iPhone, rotate to landscape for a larger view.');
            }
        } catch (error) {
            console.error('Fullscreen error:', error);
        }
    });

    // Download. GLB (the default) downloads the currently loaded model
    // straight from the viewer; any other format re-derives it on the fly
    // server-side (geometry only -- STL/OBJ/PLY don't carry PBR materials/
    // textures, an inherent limitation of those formats, and the backend
    // only allows the owner to fetch them -- see blueprints/model_files.py).
    async function downloadFormat(format) {
        try {
            const modelUrl = format === 'glb'
                ? modelViewer.src
                : '/api/models/' + window.VIEWER_CONFIG.modelId + '/export/' + format;
            if (!modelUrl) {
                throw new Error('Model URL not found');
            }

            const response = await fetch(modelUrl);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = format === 'glb'
                ? window.VIEWER_CONFIG.downloadFilename
                : window.VIEWER_CONFIG.downloadFilename.replace(/\.glb$/i, '') + '.' + format;

            document.body.appendChild(a);
            a.click();

            setTimeout(() => {
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);
            }, 100);
            // Track download
            fetch('/api/models/' + window.VIEWER_CONFIG.modelDbId + '/track-download', { method: 'POST' }).catch(() => {});
        } catch (error) {
            console.error('Download error:', error);
            alert('Failed to download model. Please try again.');
        }
    }

    const hoverCapable = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
    const availableFormats = (downloadButton?.dataset.formats || 'glb').split(',');

    function openDownloadFormatModal() {
        if (!downloadFormatModal || !downloadFormatModalOptions) return;
        downloadFormatModalOptions.innerHTML = '';
        availableFormats.forEach((format) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn-secondary';
            btn.style.width = '100%';
            btn.textContent = 'Download ' + format.toUpperCase();
            btn.addEventListener('click', () => {
                downloadFormatModal.classList.add('hidden');
                downloadFormat(format);
            });
            downloadFormatModalOptions.appendChild(btn);
        });
        downloadFormatModal.classList.remove('hidden');
    }

    // Desktop: hovering #downloadMenu reveals the other formats as a fan-out
    // (CSS above), so a plain click just grabs the default (GLB). Mobile/
    // tablet has no hover, so tapping opens a popup to choose the format.
    downloadButton?.addEventListener('click', () => {
        if (hoverCapable) {
            downloadFormat('glb');
        } else {
            openDownloadFormatModal();
        }
    });

    document.querySelectorAll('.download-fanout-btn').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            downloadFormat(btn.dataset.format);
        });
    });

    // Keep the desktop fan-out open for a moment after the cursor leaves, so
    // moving from the Download button across the gap to a format button doesn't
    // instantly collapse the menu (the arc buttons sit outside the trigger's
    // box, so a pure :hover drops as soon as you cross the empty space).
    const downloadMenu = document.querySelector('#downloadMenu');
    if (downloadMenu && hoverCapable) {
        let closeTimer = null;
        const open = () => {
            if (closeTimer) { clearTimeout(closeTimer); closeTimer = null; }
            downloadMenu.classList.add('is-open');
        };
        const scheduleClose = () => {
            if (closeTimer) clearTimeout(closeTimer);
            closeTimer = setTimeout(() => downloadMenu.classList.remove('is-open'), 350);
        };
        downloadMenu.addEventListener('mouseenter', open);
        downloadMenu.addEventListener('mouseleave', scheduleClose);
    }

    downloadFormatModalClose?.addEventListener('click', () => {
        downloadFormatModal?.classList.add('hidden');
    });
    downloadFormatModal?.addEventListener('click', (e) => {
        if (e.target === downloadFormatModal) downloadFormatModal.classList.add('hidden');
    });

    // The viewer is a light-only page (independent of the model's own
    // background color setting, which the template already applied inline).
    document.documentElement.classList.remove('dark');
    localStorage.theme = 'light';
    // Only fall back to white if the owner hasn't configured a background —
    // this used to unconditionally overwrite the template's inline
    // `background:{{ viewer_settings.background_color }}`, silently making
    // that Embed-panel setting have no effect on the main viewer page.
    if (viewerStage && !viewerStage.style.background) viewerStage.style.background = '#FFFFFF';

    // Screenshot functionality
    screenshotButton?.addEventListener('click', async () => {
        try {
            const blob = await modelViewer.toBlob({
                idealAspect: true,
                quality: 0.9
            });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'model-screenshot.png';
            a.click();
            URL.revokeObjectURL(url);
        } catch (error) {
            console.error('Error taking screenshot:', error);
        }
    });
});
