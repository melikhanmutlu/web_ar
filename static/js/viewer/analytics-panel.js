// Owner-only per-model analytics summary (Faz 2: "Analitik panosunu
// derinleştir"). Consumes the existing /api/models/<id>/analytics endpoint
// (blueprints/engagement.py), which already had no UI reading it.
document.addEventListener('DOMContentLoaded', () => {
    const modelId = window.VIEWER_CONFIG.modelId;
    const totalsEl = document.getElementById('analyticsTotals');
    const referrersEl = document.getElementById('analyticsReferrers');
    if (!totalsEl && !referrersEl) return;

    const EVENT_LABELS = {
        view: 'Page views',
        embed_view: 'Embed views',
        ar_launch: 'AR launches',
        download: 'Downloads',
        share: 'Shares',
        qr_open: 'QR scans',
    };

    fetch(`/api/models/${modelId}/analytics?days=30`)
        .then((r) => r.json())
        .then((data) => {
            if (!data.success) {
                if (totalsEl) totalsEl.innerHTML = '<p class="tp-note">Analytics unavailable.</p>';
                return;
            }
            if (totalsEl) {
                const rows = Object.entries(EVENT_LABELS)
                    .map(([key, label]) => `<div class="tp-dim-row"><span>${label}</span><span>${data.totals?.[key] || 0}</span></div>`)
                    .join('');
                const visitorsRow = `<div class="tp-dim-row tp-dim-total"><span>Unique visitors</span><span>${data.unique_visitors || 0}</span></div>`;
                totalsEl.innerHTML = rows + visitorsRow;
            }
            if (referrersEl) {
                const referrers = (data.referrers || []).slice(0, 5);
                if (referrers.length === 0) {
                    referrersEl.innerHTML = '<p class="tp-note">No referrer data yet</p>';
                } else {
                    referrersEl.innerHTML = referrers
                        .map((r) => `<div class="tp-dim-row"><span>${window.escapeHtml(r.domain)}</span><span>${r.count}</span></div>`)
                        .join('');
                }
            }
        })
        .catch(() => {
            if (totalsEl) totalsEl.innerHTML = '<p class="tp-note">Analytics unavailable.</p>';
        });
});
