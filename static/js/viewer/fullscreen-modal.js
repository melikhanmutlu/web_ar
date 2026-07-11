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

    // Fullscreen button handler
    fullscreenButton?.addEventListener('click', async () => {
        try {
            if (!document.fullscreenElement) {
                await modelViewer.requestFullscreen();
            } else {
                await document.exitFullscreen();
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

    downloadFormatModalClose?.addEventListener('click', () => {
        downloadFormatModal?.classList.add('hidden');
    });
    downloadFormatModal?.addEventListener('click', (e) => {
        if (e.target === downloadFormatModal) downloadFormatModal.classList.add('hidden');
    });

    // The viewer is a light-only page; the stage default in CSS is
    // gray-100, but the viewer has always rendered on white.
    document.documentElement.classList.remove('dark');
    localStorage.theme = 'light';
    if (viewerStage) viewerStage.style.background = '#FFFFFF';

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
