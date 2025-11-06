
<script>
// ========== MODEL SLICER (V2 - THREE.JS CLIPPING) ==========
document.addEventListener('DOMContentLoaded', () => {
    const modelViewer = document.querySelector('model-viewer');
    let slicerEnabled = false;
    let showOriginal = false;
    let meshBounds = null; // Will store { min: [x,y,z], max: [x,y,z], center: [x,y,z] }

    // Multi-plane support state
    let activePlanes = new Set(['x']); // Default active plane
    let planeSettings = {
        x: { position: 50, keepSide: 'above' }, // position in percent, keepSide 'above' or 'below'
        y: { position: 50, keepSide: 'above' },
        z: { position: 50, keepSide: 'above' }
    };

    const toggleSlicerBtn = document.getElementById('toggleSlicer');
    const slicerControls = document.getElementById('slicerControls');
    const applySliceBtn = document.getElementById('applySlice');

    // Gets the internal THREE object from model-viewer
    function getTHREE() {
        return window.THREE;
    }

    // Applies Three.js clipping planes to the model for live preview
    function applyThreeJSClipping() {
        const THREE = getTHREE();
        const scene = getInternalScene();

        if (!THREE || !scene || !meshBounds || !slicerEnabled) {
            removeThreeJSClipping(); // Ensure clipping is off if something is wrong
            return;
        }

        const planes = [];
        activePlanes.forEach(planeAxis => {
            const settings = planeSettings[planeAxis];
            const percent = settings.position;
            const keepSide = settings.keepSide;

            const axisIndex = planeAxis === 'x' ? 0 : (planeAxis === 'y' ? 1 : 2);
            const range = meshBounds.max[axisIndex] - meshBounds.min[axisIndex];
            const position = meshBounds.min[axisIndex] + (percent / 100) * range;

            let normal;
            let constant = -position;

            if (planeAxis === 'x') normal = new THREE.Vector3(1, 0, 0);
            if (planeAxis === 'y') normal = new THREE.Vector3(0, 1, 0);
            if (planeAxis === 'z') normal = new THREE.Vector3(0, 0, 1);

            if (keepSide === 'below') {
                normal.negate();
                constant = -constant;
            }

            planes.push(new THREE.Plane(normal, constant));
        });

        // Apply clipping planes to all materials
        scene.traverse((child) => {
            if (child.isMesh && child.material) {
                const materials = Array.isArray(child.material) ? child.material : [child.material];
                materials.forEach(mat => {
                    mat.clippingPlanes = planes;
                    mat.clipIntersection = false; // Render the intersection line
                    mat.clipShadows = true;
                    mat.needsUpdate = true;
                });
            }
        });

        // Enable clipping on the renderer
        const renderer = modelViewer[Object.getOwnPropertySymbols(modelViewer).find(s => s.description === 'renderer')];
        if(renderer) {
            renderer.localClippingEnabled = true;
        }

        // Update dimension display
        updateDimensionDisplay(1.0);
    }

    // Removes all clipping planes to show the full model
    function removeThreeJSClipping() {
        const scene = getInternalScene();
        if (!scene) return;

        scene.traverse((child) => {
            if (child.isMesh && child.material) {
                const materials = Array.isArray(child.material) ? child.material : [child.material];
                materials.forEach(mat => {
                    mat.clippingPlanes = null; // Use null to disable
                    mat.needsUpdate = true;
                });
            }
        });

        const renderer = modelViewer[Object.getOwnPropertySymbols(modelViewer).find(s => s.description === 'renderer')];
        if(renderer) {
            renderer.localClippingEnabled = false;
        }
    }

    // Creates the UI for individual plane controls
    function createPlaneControls() {
        const container = document.getElementById('planeControlsContainer');
        container.innerHTML = '';

        activePlanes.forEach(plane => {
            const settings = planeSettings[plane];
            const planeColor = plane === 'x' ? 'red' : (plane === 'y' ? 'green' : 'blue');

            const controlDiv = document.createElement('div');
            controlDiv.className = `mb-4 p-3 bg-${planeColor}-50 dark:bg-${planeColor}-900/20 rounded-lg border border-${planeColor}-200 dark:border-${planeColor}-800`;
            const keepAbove = settings.keepSide === 'above';

            controlDiv.innerHTML = `
                <div class="flex items-center justify-between mb-2">
                    <span class="text-xs font-semibold text-${planeColor}-700 dark:text-${planeColor}-300">${plane.toUpperCase()} Axis</span>
                    <span class="plane-percent text-xs text-${planeColor}-600 dark:text-${planeColor}-400 font-semibold">${settings.position}%</span>
                </div>
                <input type="range" class="plane-slider w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 mb-2"
                       data-plane="${plane}" min="0" max="100" step="1" value="${settings.position}">
                <div class="flex gap-2">
                    <button class="plane-keep-btn nav-button flex-1 text-xs justify-center ${keepAbove ? 'bg-green-100 dark:bg-green-900/50 border-green-500' : ''}"
                            data-plane="${plane}" data-side="above">Keep Above</button>
                    <button class="plane-keep-btn nav-button flex-1 text-xs justify-center ${!keepAbove ? 'bg-green-100 dark:bg-green-900/50 border-green-500' : ''}"
                            data-plane="${plane}" data-side="below">Keep Below</button>
                </div>
            `;
            container.appendChild(controlDiv);
        });

        attachPlaneControlListeners();
    }

    // Attaches event listeners to the dynamically created plane controls
    function attachPlaneControlListeners() {
        document.querySelectorAll('.plane-slider').forEach(slider => {
            slider.addEventListener('input', (e) => {
                const plane = e.target.dataset.plane;
                const percent = parseInt(e.target.value);
                planeSettings[plane].position = percent;
                e.target.parentElement.querySelector('.plane-percent').textContent = percent + '%';
                applyThreeJSClipping();
            });
        });

        document.querySelectorAll('.plane-keep-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const plane = btn.dataset.plane;
                const side = btn.dataset.side;
                planeSettings[plane].keepSide = side;

                const controlDiv = btn.closest('div').parentElement;
                controlDiv.querySelectorAll('.plane-keep-btn').forEach(b => {
                    b.classList.toggle('bg-green-100', b.dataset.side === side);
                    b.classList.toggle('dark:bg-green-900/50', b.dataset.side === side);
                    b.classList.toggle('border-green-500', b.dataset.side === side);
                });

                applyThreeJSClipping();
            });
        });
    }

    // Fetches the model's bounding box from the backend
    async function loadMeshBounds() {
        try {
            const modelId = getCurrentModelId();
            const response = await fetch(`/get_mesh_bounds/${modelId}`);
            const result = await response.json();

            if (result.success) {
                meshBounds = result.bounds;
                if (slicerEnabled) applyThreeJSClipping(); // Apply clipping now that we have bounds
            } else {
                console.error('Failed to load mesh bounds:', result.error);
            }
        } catch (error) {
            console.error('Error loading mesh bounds:', error);
        }
    }

    // Main toggle for the slicer feature
    toggleSlicerBtn.addEventListener('click', async () => {
        slicerEnabled = !slicerEnabled;

        if (slicerEnabled) {
            toggleSlicerBtn.textContent = 'Disable Slicer';
            toggleSlicerBtn.classList.add('bg-red-100', 'dark:bg-red-900/50', 'border-red-500');
            slicerControls.classList.remove('hidden');

            await loadMeshBounds();
            createPlaneControls();
            applyThreeJSClipping();
        } else {
            toggleSlicerBtn.textContent = 'Enable Slicer';
            toggleSlicerBtn.classList.remove('bg-red-100', 'dark:bg-red-900/50', 'border-red-500');
            slicerControls.classList.add('hidden');
            removeThreeJSClipping();
        }
    });

    // Listeners for X, Y, Z axis selection buttons
    document.querySelectorAll('.plane-toggle-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const plane = btn.dataset.plane;

            if (activePlanes.has(plane)) {
                if (activePlanes.size > 1) activePlanes.delete(plane); // Don't allow removing the last plane
            } else {
                activePlanes.add(plane);
            }

            // Update button styles
            document.querySelectorAll('.plane-toggle-btn').forEach(b => {
                const p = b.dataset.plane;
                const color = p === 'x' ? 'red' : p === 'y' ? 'green' : 'blue';
                const isActive = activePlanes.has(p);

                b.classList.toggle(`border-${color}-500`, isActive);
                b.classList.toggle(`bg-${color}-50`, isActive);
                b.classList.toggle(`dark:bg-${color}-900/30`, isActive);
                b.classList.toggle(`text-${color}-700`, isActive);
                b.classList.toggle(`dark:text-${color}-300`, isActive);
                b.classList.toggle('font-semibold', isActive);

                b.classList.toggle('border-gray-300', !isActive);
                b.classList.toggle('dark:border-gray-600', !isActive);
                b.classList.toggle('bg-white', !isActive);
                b.classList.toggle('dark:bg-gray-700', !isActive);
                b.classList.toggle('text-gray-700', !isActive);
                b.classList.toggle('dark:text-gray-300', !isActive);
                b.classList.toggle('font-medium', !isActive);
            });

            createPlaneControls();
            applyThreeJSClipping();
        });
    });

    // Handler for the "Apply Slice" button
    applySliceBtn.addEventListener('click', async () => {
         if (!meshBounds || activePlanes.size === 0) {
            alert('Please enable slicing and select a plane first.');
            return;
        }

        if (!confirm(`This will permanently cut the model based on the ${activePlanes.size} active plane(s). Continue?`)) {
            return;
        }

        const originalHTML = applySliceBtn.innerHTML;
        applySliceBtn.disabled = true;
        applySliceBtn.innerHTML = `<svg class="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">...</svg> Slicing...`;

        try {
            const modelId = getCurrentModelId();
            let currentBounds = meshBounds; // Start with original bounds

            // Apply each slice sequentially
            for (const planeAxis of activePlanes) {
                const settings = planeSettings[planeAxis];
                const axisIndex = planeAxis === 'x' ? 0 : (planeAxis === 'y' ? 1 : 2);
                const range = currentBounds.max[axisIndex] - currentBounds.min[axisIndex];
                const position = currentBounds.min[axisIndex] + (settings.position / 100) * range;

                let planeOrigin = [...currentBounds.center];
                planeOrigin[axisIndex] = position;

                let planeNormal = [0, 0, 0];
                planeNormal[axisIndex] = 1;

                const response = await fetch('/slice_model', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        model_id: modelId,
                        plane_origin: planeOrigin,
                        plane_normal: planeNormal,
                        keep_side: settings.keepSide === 'above' ? 'positive' : 'negative'
                    })
                });

                const result = await response.json();
                if (!result.success) throw new Error(result.error || 'A slice operation failed.');

                // Update bounds with the new data from the server
                if (result.new_bounds) {
                    currentBounds = result.new_bounds;
                } else {
                    // Fallback to fetching bounds if not returned by slice_model
                    const boundsResponse = await fetch(`/get_mesh_bounds/${modelId}`);
                    const boundsResult = await boundsResponse.json();
                    if (boundsResult.success) {
                        currentBounds = boundsResult.bounds;
                    } else {
                        throw new Error('Could not reload bounds between slices.');
                    }
                }
            }

            applySliceBtn.innerHTML = `Success! Reloading...`;
            setTimeout(() => {
                // Bust cache to ensure the new model is loaded
                window.location.href = window.location.pathname + '?t=' + new Date().getTime();
            }, 1500);

        } catch (error) {
            alert('Failed to slice model: ' + error.message);
            applySliceBtn.innerHTML = originalHTML;
            applySliceBtn.disabled = false;
        }
    });

    // Toggle for showing the original model
    const showOriginalToggle = document.getElementById('showOriginalToggle');
    const showOriginalText = document.getElementById('showOriginalText');

    showOriginalToggle.addEventListener('click', () => {
        showOriginal = !showOriginal;
        if (showOriginal) {
            removeThreeJSClipping();
            showOriginalText.textContent = 'Show Sliced';
        } else {
            applyThreeJSClipping();
            showOriginalText.textContent = 'Show Original';
        }
    });

    // Update dimension display
    function updateDimensionDisplay(scale) {
        if (!meshBounds) return;

        const width = ((meshBounds.max[0] - meshBounds.min[0]) * scale * 100).toFixed(1);
        const height = ((meshBounds.max[1] - meshBounds.min[1]) * scale * 100).toFixed(1);
        const depth = ((meshBounds.max[2] - meshBounds.min[2]) * scale * 100).toFixed(1);

        document.getElementById('dimWidth').textContent = `${width} cm`;
        document.getElementById('dimHeight').textContent = `${height} cm`;
        document.getElementById('dimDepth').textContent = `${depth} cm`;
    }
});
</script>
