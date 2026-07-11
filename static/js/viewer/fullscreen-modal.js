// Get all the necessary DOM elements
document.addEventListener('DOMContentLoaded', () => {
    const modelViewer = document.querySelector('model-viewer');
    const viewerStage = document.querySelector('.viewer-stage');
    const fullscreenButton = document.querySelector('#fullscreenButton');
    const downloadButton = document.querySelector('#downloadButton');
    const downloadFormatSelect = document.querySelector('#downloadFormatSelect');
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

    // Download button handler. GLB (the default) downloads the currently
    // loaded model straight from the viewer; any other format re-derives it
    // on the fly server-side (geometry only -- STL/OBJ/PLY don't carry
    // PBR materials/textures, an inherent limitation of those formats).
    downloadButton?.addEventListener('click', async () => {
        try {
            const format = downloadFormatSelect?.value || 'glb';
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
