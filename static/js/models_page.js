document.addEventListener('DOMContentLoaded', function() {
    // Delete single model
    document.querySelectorAll('.delete-model').forEach(button => {
        button.addEventListener('click', async function() {
            const modelCard = this.closest('.model-card');
            const modelId = modelCard.dataset.modelId;

            if (await window.arConfirm('Are you sure you want to delete this model?', { confirmLabel: 'Delete', danger: true })) {
                fetch(`/delete_model/${modelId}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        modelCard.remove();
                        if (document.querySelectorAll('.model-card').length === 0) {
                            location.reload();
                        }
                    } else {
                        window.arToast('Error deleting model: ' + (data.error || 'Unknown error'), 'error');
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                    window.arToast('Error deleting model', 'error');
                });
            }
        });
    });

    // Delete all models
    document.getElementById('deleteAllBtn').addEventListener('click', async function() {
        if (await window.arConfirm('Are you sure you want to delete all models? This cannot be undone.', { confirmLabel: 'Delete all', danger: true })) {
            fetch('/delete_all_models', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    window.arToast('Error deleting models: ' + (data.error || 'Unknown error'), 'error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                window.arToast('Error deleting models', 'error');
            });
        }
    });
});
