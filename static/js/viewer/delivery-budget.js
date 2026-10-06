// Owner-only delivery-budget actions: "Optimize for mobile" queues the
// meshopt-compression job, "Simplify" queues a triangle-reduction job (the
// original stays in History). The page reloads once the job finishes (the new
// asset_version busts the GLB cache).
document.addEventListener('DOMContentLoaded', () => {
    const compressBtn = document.getElementById('deliveryOptimizeBtn');
    const simplifyBtn = document.getElementById('deliverySimplifyBtn');
    const text = document.getElementById('deliveryBudgetText');
    if ((!compressBtn && !simplifyBtn) || !text) return;
    const modelId = window.VIEWER_CONFIG.modelDbId;
    const buttons = [compressBtn, simplifyBtn].filter(Boolean);

    async function poll(statusUrl, token) {
        for (let i = 0; i < 300; i++) {
            await new Promise(resolve => setTimeout(resolve, 2000));
            const resp = await fetch(statusUrl, { headers: { 'X-Job-Status-Token': token } });
            const job = await resp.json();
            if (job.status === 'completed') return;
            if (job.status === 'failed') throw new Error(job.error || 'Optimization failed');
        }
        throw new Error('Optimization is taking longer than expected. Reload the page in a moment.');
    }

    async function run(body, busyText) {
        buttons.forEach(b => { b.disabled = true; });
        text.textContent = busyText;
        try {
            const resp = await fetch('/api/models/' + encodeURIComponent(modelId) + '/optimize-mobile', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await resp.json();
            if (!resp.ok || !data.success) throw new Error(data.error || 'Could not start optimization');
            await poll(data.status_url, data.status_token);
            window.location.reload();
        } catch (err) {
            text.textContent = err.message || 'Optimization failed';
            buttons.forEach(b => { b.disabled = false; });
        }
    }

    if (compressBtn) {
        compressBtn.addEventListener('click', () => run(
            { mode: 'compress' }, 'Optimizing for mobile… this can take a minute.'));
    }
    if (simplifyBtn) {
        simplifyBtn.addEventListener('click', async () => {
            const target = parseInt(simplifyBtn.dataset.targetTriangles, 10);
            if (!await window.arConfirm('Simplify this model to about ' + target.toLocaleString() +
                ' triangles? Fine detail is lost, but your original is kept in the History tab.',
                { confirmLabel: 'Simplify' })) return;
            run({ mode: 'simplify', target_triangles: target },
                'Simplifying for mobile… this can take a few minutes.');
        });
    }
});
