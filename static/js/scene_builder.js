document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.scene-item-checkbox').forEach((checkbox) => {
        checkbox.addEventListener('change', () => {
            const fields = checkbox.closest('.tp-list-item').querySelector('.scene-item-fields');
            fields.classList.toggle('hidden', !checkbox.checked);
            fields.style.display = checkbox.checked ? 'grid' : 'none';
        });
    });

    const buildBtn = document.getElementById('buildSceneBtn');
    buildBtn.addEventListener('click', () => window.withBusy(buildBtn, buildScene, 'Building…'));

    // Returns a promise so withBusy keeps the button disabled while the scene
    // builds (a double-click used to create two scenes).
    function buildScene() {
        const items = [];
        document.querySelectorAll('.scene-item-checkbox:checked').forEach((checkbox) => {
            const row = checkbox.closest('.tp-list-item');
            items.push({
                model_id: checkbox.dataset.modelId,
                position: {
                    x: parseFloat(row.querySelector('.scene-pos-x').value) || 0,
                    y: parseFloat(row.querySelector('.scene-pos-y').value) || 0,
                    z: parseFloat(row.querySelector('.scene-pos-z').value) || 0,
                },
                rotation_y: parseFloat(row.querySelector('.scene-rot-y').value) || 0,
                scale: parseFloat(row.querySelector('.scene-scale').value) || 1,
            });
        });

        const status = document.getElementById('sceneBuildStatus');
        status.classList.remove('hidden');
        status.textContent = 'Building scene…';

        return fetch('/api/scenes/build', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: document.getElementById('sceneName').value, items }),
        })
            .then(r => r.json())
            .then(data => {
                if (!data.success) {
                    status.textContent = data.error || 'Failed to build scene.';
                    return;
                }
                status.textContent = 'Scene ready! Opening viewer…';
                // Keep the button locked while the browser navigates away.
                buildBtn.disabled = true;
                window.location.href = data.viewer_url;
                return new Promise(() => {});
            })
            .catch(() => { status.textContent = 'Failed to build scene.'; });
    }
});
