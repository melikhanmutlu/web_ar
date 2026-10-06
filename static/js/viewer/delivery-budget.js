// Owner-only "Optimize for mobile": queues the meshopt-compression job and
// reloads the page once it finishes (new asset_version busts the GLB cache).
document.addEventListener('DOMContentLoaded', () => {
    const button = document.getElementById('deliveryOptimizeBtn');
    const text = document.getElementById('deliveryBudgetText');
    if (!button || !text) return;
    const modelId = window.VIEWER_CONFIG.modelDbId;

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

    button.addEventListener('click', async () => {
        button.disabled = true;
        text.textContent = 'Optimizing for mobile… this can take a minute.';
        try {
            const resp = await fetch('/api/models/' + encodeURIComponent(modelId) + '/optimize-mobile', { method: 'POST' });
            const data = await resp.json();
            if (!resp.ok || !data.success) throw new Error(data.error || 'Could not start optimization');
            await poll(data.status_url, data.status_token);
            window.location.reload();
        } catch (err) {
            text.textContent = err.message || 'Optimization failed';
            button.disabled = false;
        }
    });
});
