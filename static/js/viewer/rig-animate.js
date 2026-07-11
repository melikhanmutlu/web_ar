document.addEventListener('DOMContentLoaded', () => {
        if (window.VIEWER_CONFIG.isOwner) {
        // ===================================================================
        // AI RIG & ANIMATE
        // ===================================================================
        (function () {
            const rigModelId = window.VIEWER_CONFIG.modelDbId;
            const grid = document.getElementById('rigAnimationGrid');
            const countLabel = document.getElementById('rigAnimCount');
            const startBtn = document.getElementById('startRigBtn');
            const statusBox = document.getElementById('rigStatus');
            const progressBar = document.getElementById('rigProgressBar');
            const statusText = document.getElementById('rigStatusText');
            const errorBox = document.getElementById('rigError');
            if (!grid || !startBtn) return;

            const MAX_ANIMATIONS = 10;
            let selected = [];

            function updateCount() {
                countLabel.textContent = selected.length + '/' + MAX_ANIMATIONS;
            }

            fetch('/static/data/meshy_animation_presets.json')
                .then(r => r.json())
                .then(data => {
                    grid.innerHTML = '';
                    (data.categories || []).forEach(cat => {
                        const heading = document.createElement('div');
                        heading.className = 'rig-anim-category';
                        heading.textContent = cat.name;
                        grid.appendChild(heading);
                        (cat.actions || []).forEach(action => {
                            const label = document.createElement('label');
                            label.className = 'rig-anim-item';
                            const checkbox = document.createElement('input');
                            checkbox.type = 'checkbox';
                            checkbox.className = 'tp-checkbox';
                            checkbox.value = action.id;
                            checkbox.addEventListener('change', () => {
                                if (checkbox.checked) {
                                    if (selected.length >= MAX_ANIMATIONS) {
                                        checkbox.checked = false;
                                        return;
                                    }
                                    selected.push(action.id);
                                } else {
                                    selected = selected.filter(id => id !== action.id);
                                }
                                updateCount();
                            });
                            label.appendChild(checkbox);
                            label.appendChild(document.createTextNode(' ' + action.label));
                            grid.appendChild(label);
                        });
                    });
                })
                .catch(() => {
                    grid.innerHTML = '<p class="tp-note">Failed to load animation presets.</p>';
                });

            function setRigProgress(pct, msg) {
                progressBar.style.width = pct + '%';
                if (msg) statusText.textContent = msg;
            }

            startBtn.addEventListener('click', async () => {
                errorBox.classList.add('hidden'); errorBox.textContent = '';
                const height = parseFloat(document.getElementById('rigHeight').value);
                if (!height || height < 0.05 || height > 10) {
                    errorBox.textContent = 'Enter a valid height (0.05–10 meters).';
                    errorBox.classList.remove('hidden');
                    return;
                }
                if (!selected.length) {
                    errorBox.textContent = 'Select at least one animation.';
                    errorBox.classList.remove('hidden');
                    return;
                }

                startBtn.disabled = true;
                statusBox.classList.remove('hidden');
                setRigProgress(2, 'Starting…');

                try {
                    const r = await fetch('/api/models/' + rigModelId + '/rig', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ height_meters: height, animation_action_ids: selected })
                    });
                    const d = await r.json();
                    if (!d.success) throw new Error(d.error || 'Failed to start');
                    const jobId = d.job_id;

                    const STAGE_LABELS = {
                        remeshing: 'Reducing polygon count…',
                        rigging: 'Rigging…',
                        animating: 'Applying animations…',
                        finalizing: 'Saving result…'
                    };
                    let done = false, tries = 0;
                    while (!done && tries < 200) {
                        await new Promise(res => setTimeout(res, 2500));
                        tries++;
                        const sr = await fetch('/api/rig-jobs/' + jobId + '/status');
                        const sd = await sr.json();
                        if (!sd.success) throw new Error(sd.error || 'Status check failed');
                        setRigProgress(Math.max(2, sd.progress || 0), STAGE_LABELS[sd.stage] || 'Working…');
                        if (sd.status === 'ready' && sd.viewer_url) {
                            setRigProgress(100, 'Done');
                            window.location.href = sd.viewer_url;
                            done = true;
                        } else if (sd.status === 'failed') {
                            throw new Error(sd.error || 'Rigging failed');
                        }
                    }
                    if (!done) throw new Error('Timed out. Please try again.');
                } catch (e) {
                    errorBox.textContent = e.message;
                    errorBox.classList.remove('hidden');
                } finally {
                    startBtn.disabled = false;
                }
            });
        })();
        }
});
