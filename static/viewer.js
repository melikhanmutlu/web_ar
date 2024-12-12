document.addEventListener('DOMContentLoaded', function() {
    const modelViewer = document.querySelector('model-viewer');

    // Dark mode toggle
    function toggleDarkMode() {
        document.documentElement.classList.toggle('dark');
        localStorage.theme = document.documentElement.classList.contains('dark') ? 'dark' : 'light';
    }
    window.toggleDarkMode = toggleDarkMode;

    // Set initial dark mode
    if (localStorage.theme === 'dark' || (!('theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
        document.documentElement.classList.add('dark');
    } else {
        document.documentElement.classList.remove('dark');
    }

    // QR Code functions
    function showQRCode() {
        document.getElementById('overlay').style.display = 'block';
        document.getElementById('qr-popup').style.display = 'block';
    }
    window.showQRCode = showQRCode;

    function hideQRCode() {
        document.getElementById('overlay').style.display = 'none';
        document.getElementById('qr-popup').style.display = 'none';
    }
    window.hideQRCode = hideQRCode;

    // Hide AR button on desktop
    const arButton = document.getElementById('ar-button');
    if (!window.matchMedia('(max-width: 768px)').matches) {
        arButton.style.display = 'none';
    }

    // Camera controls
    function setCameraView(view) {
        switch(view) {
            case 'front':
                modelViewer.cameraOrbit = '0deg 90deg 105%';
                break;
            case 'side':
                modelViewer.cameraOrbit = '90deg 90deg 105%';
                break;
            case 'top':
                modelViewer.cameraOrbit = '0deg 0deg 105%';
                break;
        }
    }
    window.setCameraView = setCameraView;

    function resetCamera() {
        modelViewer.cameraOrbit = '0deg 75deg 105%';
        modelViewer.fieldOfView = '30deg';
        document.getElementById('fov').value = 30;
        document.getElementById('fov-value').textContent = '30';
    }
    window.resetCamera = resetCamera;

    // FOV control
    const fovSlider = document.getElementById('fov');
    const fovValue = document.getElementById('fov-value');
    fovSlider.addEventListener('input', (e) => {
        const value = e.target.value;
        modelViewer.fieldOfView = `${value}deg`;
        fovValue.textContent = value;
    });

    // Orbit speed control
    const orbitSpeedSlider = document.getElementById('orbit-speed');
    const orbitSpeedValue = document.getElementById('orbit-speed-value');
    orbitSpeedSlider.addEventListener('input', (e) => {
        const value = e.target.value;
        modelViewer.orbitSensitivity = value;
        orbitSpeedValue.textContent = value;
    });

    // Environment control
    const environmentSelect = document.getElementById('environment');
    environmentSelect.addEventListener('change', (e) => {
        modelViewer.environmentImage = e.target.value;
    });

    // Background color control
    const bgColorPicker = document.getElementById('bg-color');
    bgColorPicker.addEventListener('input', (e) => {
        modelViewer.style.backgroundColor = e.target.value;
    });

    // Shadow controls
    const shadowIntensitySlider = document.getElementById('shadow-intensity');
    shadowIntensitySlider.addEventListener('input', (e) => {
        modelViewer.shadowIntensity = e.target.value;
    });

    const shadowSoftnessSlider = document.getElementById('shadow-softness');
    shadowSoftnessSlider.addEventListener('input', (e) => {
        modelViewer.shadowSoftness = e.target.value;
    });

    // Exposure control
    const exposureSlider = document.getElementById('exposure');
    exposureSlider.addEventListener('input', (e) => {
        modelViewer.exposure = e.target.value;
    });

    // Scale controls
    const scaleX = document.getElementById('scale-x');
    const scaleY = document.getElementById('scale-y');
    const scaleZ = document.getElementById('scale-z');

    function updateScale() {
        modelViewer.scale = `${scaleX.value} ${scaleY.value} ${scaleZ.value}`;
    }

    scaleX.addEventListener('input', updateScale);
    scaleY.addEventListener('input', updateScale);
    scaleZ.addEventListener('input', updateScale);

    // Rotation controls
    const rotationSpeedSlider = document.getElementById('rotation-speed');
    const rotationAxisSelect = document.getElementById('rotation-axis');
    const autoRotateCheckbox = document.getElementById('auto-rotate');

    function updateRotation() {
        const speed = rotationSpeedSlider.value;
        const axis = rotationAxisSelect.value;
        modelViewer.autoRotate = autoRotateCheckbox.checked;
        modelViewer.rotationPerSecond = `${speed}deg`;
    }

    rotationSpeedSlider.addEventListener('input', updateRotation);
    rotationAxisSelect.addEventListener('change', updateRotation);
    autoRotateCheckbox.addEventListener('change', updateRotation);

    // Position controls
    const positionX = document.getElementById('position-x');
    const positionY = document.getElementById('position-y');
    const positionZ = document.getElementById('position-z');

    function updatePosition() {
        modelViewer.cameraTarget = `${positionX.value}m ${positionY.value}m ${positionZ.value}m`;
    }

    positionX.addEventListener('input', updatePosition);
    positionY.addEventListener('input', updatePosition);
    positionZ.addEventListener('input', updatePosition);

    // Measurement Tools
    let measureMode = null;
    let measurePoints = [];
    
    document.getElementById('measure-distance').addEventListener('click', () => {
        measureMode = measureMode === 'distance' ? null : 'distance';
        measurePoints = [];
        updateMeasurementUI();
    });

    document.getElementById('measure-angle').addEventListener('click', () => {
        measureMode = measureMode === 'angle' ? null : 'angle';
        measurePoints = [];
        updateMeasurementUI();
    });

    modelViewer.addEventListener('click', (event) => {
        if (!measureMode) return;

        const hit = modelViewer.positionAndNormalFromPoint(event.clientX, event.clientY);
        if (hit) {
            measurePoints.push(hit.position);
            if ((measureMode === 'distance' && measurePoints.length === 2) ||
                (measureMode === 'angle' && measurePoints.length === 3)) {
                calculateMeasurement();
            }
        }
    });

    function updateMeasurementUI() {
        const resultDiv = document.getElementById('measurement-result');
        resultDiv.classList.toggle('hidden', !measureMode);
        document.getElementById('measurement-value').textContent = '';
    }

    function calculateMeasurement() {
        if (measureMode === 'distance' && measurePoints.length === 2) {
            const distance = calculateDistance(measurePoints[0], measurePoints[1]);
            document.getElementById('measurement-value').textContent = `${distance.toFixed(2)} units`;
        } else if (measureMode === 'angle' && measurePoints.length === 3) {
            const angle = calculateAngle(measurePoints[0], measurePoints[1], measurePoints[2]);
            document.getElementById('measurement-value').textContent = `${angle.toFixed(2)}°`;
        }
        measurePoints = [];
    }

    function calculateDistance(p1, p2) {
        return Math.sqrt(
            Math.pow(p2.x - p1.x, 2) +
            Math.pow(p2.y - p1.y, 2) +
            Math.pow(p2.z - p1.z, 2)
        );
    }

    function calculateAngle(p1, p2, p3) {
        const v1 = {
            x: p1.x - p2.x,
            y: p1.y - p2.y,
            z: p1.z - p2.z
        };
        const v2 = {
            x: p3.x - p2.x,
            y: p3.y - p2.y,
            z: p3.z - p2.z
        };
        const dot = v1.x * v2.x + v1.y * v2.y + v1.z * v2.z;
        const v1mag = Math.sqrt(v1.x * v1.x + v1.y * v1.y + v1.z * v1.z);
        const v2mag = Math.sqrt(v2.x * v2.x + v2.y * v2.y + v2.z * v2.z);
        return Math.acos(dot / (v1mag * v2mag)) * (180 / Math.PI);
    }

    // Cross Section Controls
    const sectionEnabled = document.getElementById('section-enabled');
    const sectionPlane = document.getElementById('section-plane');
    const sectionPosition = document.getElementById('section-position');

    function updateCrossSection() {
        if (!sectionEnabled.checked) {
            modelViewer.removeAttribute('cross-section');
            return;
        }

        const position = sectionPosition.value;
        let orientation = [0, 0, 0];
        switch (sectionPlane.value) {
            case 'xy':
                orientation = [0, 0, 1];
                break;
            case 'yz':
                orientation = [1, 0, 0];
                break;
            case 'xz':
                orientation = [0, 1, 0];
                break;
        }

        modelViewer.setAttribute('cross-section', `${orientation.join(' ')} ${position}`);
    }

    sectionEnabled.addEventListener('change', updateCrossSection);
    sectionPlane.addEventListener('change', updateCrossSection);
    sectionPosition.addEventListener('input', updateCrossSection);

    // Geometry Information
    modelViewer.addEventListener('load', () => {
        // Get the scene graph
        const scene = modelViewer.model.modelViewerScene;
        if (!scene) return;

        // Calculate geometry information
        let vertexCount = 0;
        let faceCount = 0;
        scene.traverse((object) => {
            if (object.geometry) {
                const geometry = object.geometry;
                if (geometry.attributes.position) {
                    vertexCount += geometry.attributes.position.count;
                }
                if (geometry.index) {
                    faceCount += geometry.index.count / 3;
                } else if (geometry.attributes.position) {
                    faceCount += geometry.attributes.position.count / 3;
                }
            }
        });

        // Update geometry information display
        document.getElementById('vertex-count').textContent = vertexCount.toLocaleString();
        document.getElementById('face-count').textContent = Math.floor(faceCount).toLocaleString();

        // Get bounding box dimensions
        const bbox = new THREE.Box3().setFromObject(scene);
        const size = bbox.getSize(new THREE.Vector3());

        document.getElementById('model-width').textContent = size.x.toFixed(2) + ' units';
        document.getElementById('model-height').textContent = size.y.toFixed(2) + ' units';
        document.getElementById('model-depth').textContent = size.z.toFixed(2) + ' units';
    });
});
