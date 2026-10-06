// Environment switcher (data-action="setEnv" data-env="forest" on the buttons)
window.arActions.setEnv = (e, btn) => setEnv(btn.dataset.env, btn);
function setEnv(preset, btn) {
    const env = document.getElementById('vrEnvironment');
    if (env) {
        env.setAttribute('environment', 'preset', preset);
    }
    // Update active button
    document.querySelectorAll('.env-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
}

// Hide hint when VR session starts
const scene = document.querySelector('a-scene');
scene.addEventListener('enter-vr', () => {
    const hint = document.getElementById('vrHint');
    const overlay = document.getElementById('overlay');
    if (hint) hint.style.display = 'none';
    if (overlay) overlay.style.display = 'none';
});
scene.addEventListener('exit-vr', () => {
    const hint = document.getElementById('vrHint');
    const overlay = document.getElementById('overlay');
    if (hint) hint.style.display = 'block';
    if (overlay) overlay.style.display = 'flex';
});

// Auto-scale model to reasonable size after load
const modelEl = document.getElementById('vrModelEntity');
modelEl.addEventListener('model-loaded', () => {
    const mesh = modelEl.getObject3D('mesh');
    if (!mesh) return;
    const box = new THREE.Box3().setFromObject(mesh);
    const size = new THREE.Vector3();
    box.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z);
    if (maxDim > 0) {
        // Target size: ~1.5 meters max dimension
        const targetSize = 1.5;
        const scale = targetSize / maxDim;
        modelEl.setAttribute('scale', `${scale} ${scale} ${scale}`);
        // Re-center vertically so model sits on floor level
        const center = new THREE.Vector3();
        box.getCenter(center);
        const yOffset = -center.y * scale;
        const currentPos = modelEl.getAttribute('position');
        modelEl.setAttribute('position', `${currentPos.x} ${yOffset} ${currentPos.z}`);
    }
});
