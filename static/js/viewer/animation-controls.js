document.addEventListener('DOMContentLoaded', () => {
    const modelViewer = document.querySelector('model-viewer');

        // ANIMATION PANEL
        // ===================================================================
        const animSelect = document.getElementById('animationSelect');
        const playBtn = document.getElementById('playAnimation');
        const pauseBtn = document.getElementById('pauseAnimation');
        const stopBtn = document.getElementById('stopAnimationBtn');
        const animInfo = document.getElementById('animationInfo');
        const animPanel = document.getElementById('animationPanel');

        modelViewer?.addEventListener('load', () => {
            const anims = modelViewer.availableAnimations || [];
            if (anims.length === 0) {
                if (animPanel) animPanel.classList.add('hidden');
                return;
            }
            // Show animation panel
            if (animPanel) animPanel.classList.remove('hidden');
            if (animInfo) animInfo.textContent = anims.length + ' animation(s) available';

            // Populate dropdown
            if (animSelect) {
                animSelect.innerHTML = '<option value="">-- No Animation --</option>';
                anims.forEach(name => {
                    const opt = document.createElement('option');
                    opt.value = name;
                    opt.textContent = name;
                    animSelect.appendChild(opt);
                });
            }
        });

        animSelect?.addEventListener('change', (e) => {
            if (e.target.value) {
                modelViewer.animationName = e.target.value;
                modelViewer.pause();
                if (playBtn) playBtn.classList.remove('hidden');
                if (pauseBtn) pauseBtn.classList.add('hidden');
            } else {
                modelViewer.animationName = undefined;
                modelViewer.pause();
            }
        });

        playBtn?.addEventListener('click', () => {
            if (animSelect && !animSelect.value) {
                const anims = modelViewer.availableAnimations || [];
                if (anims.length > 0) {
                    modelViewer.animationName = anims[0];
                    animSelect.value = anims[0];
                }
            }
            modelViewer.play({ repetitions: Infinity });
            playBtn.classList.add('hidden');
            if (pauseBtn) pauseBtn.classList.remove('hidden');
        });

        pauseBtn?.addEventListener('click', () => {
            modelViewer.pause();
            pauseBtn.classList.add('hidden');
            if (playBtn) playBtn.classList.remove('hidden');
        });

        stopBtn?.addEventListener('click', () => {
            modelViewer.pause();
            modelViewer.currentTime = 0;
            if (pauseBtn) pauseBtn.classList.add('hidden');
            if (playBtn) playBtn.classList.remove('hidden');
        });

});
