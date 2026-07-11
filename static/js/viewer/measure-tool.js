        document.addEventListener('DOMContentLoaded', () => {
            const viewer = document.getElementById('modelViewer');
            const button = document.getElementById('measureToolButton');
            const result = document.getElementById('measureToolResult');
            let active = false;
            let points = [];
            button?.addEventListener('click', () => {
                active = !active; points = [];
                button.textContent = active ? 'Measuring…' : 'Measure';
                result.style.display = active ? 'block' : 'none';
                result.textContent = 'Select two points';
            });
            viewer?.addEventListener('click', (event) => {
                if (!active || typeof viewer.positionAndNormalFromPoint !== 'function') return;
                const hit = viewer.positionAndNormalFromPoint(event.clientX, event.clientY);
                if (!hit?.position) return;
                points.push(hit.position);
                if (points.length === 2) {
                    const [a, b] = points;
                    const meters = Math.hypot(b.x - a.x, b.y - a.y, b.z - a.z);
                    result.textContent = `${(meters * 100).toFixed(2)} cm (${meters.toFixed(3)} m)`;
                    points = [];
                } else {
                    result.textContent = 'Select the second point';
                }
            });
        });
