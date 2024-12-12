// Model Management Functions
async function deleteModel(modelId) {
    const confirmed = confirm('Are you sure you want to delete this model?');
    if (!confirmed) return;

    try {
        const response = await fetch(`/delete_model/${modelId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (response.ok) {
            displayToast('Model deleted successfully', 'success');
            location.reload();
        } else {
            throw new Error('Failed to delete model');
        }
    } catch (error) {
        console.error('Error:', error);
        displayToast('Failed to delete model', 'error');
    }
}

async function deleteSelectedModels() {
    if (selectedModels.size === 0) return;

    const confirmed = confirm(`Are you sure you want to delete ${selectedModels.size} selected model(s)?`);
    if (!confirmed) return;

    let successCount = 0;
    let failCount = 0;

    try {
        const promises = Array.from(selectedModels).map(modelId =>
            fetch(`/delete_model/${modelId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            })
            .then(async response => {
                if (response.ok || response.status === 404) {
                    // Consider both successful deletion and "not found" as success
                    // since the end result is the same - model is gone
                    successCount++;
                    return true;
                } else {
                    const errorData = await response.json();
                    console.error('Error deleting model:', errorData);
                    failCount++;
                    return false;
                }
            })
            .catch(error => {
                console.error('Error:', error);
                failCount++;
                return false;
            })
        );

        await Promise.all(promises);

        if (successCount > 0) {
            displayToast(`Successfully removed ${successCount} model${successCount > 1 ? 's' : ''}${failCount > 0 ? `, failed to delete ${failCount}` : ''}`, 'success');
            location.reload();
        } else {
            displayToast('Failed to delete models', 'error');
        }
    } catch (error) {
        console.error('Error:', error);
        displayToast('Failed to delete models', 'error');
    }
}

function viewModel(modelId) {
<<<<<<< HEAD
    window.location.href = `/view/${modelId}`;
=======
    window.location.href = `/view_model/${modelId}`;
>>>>>>> 4093290bd781a426eb457d791906d2fd7644ee15
}

// Folder Management Functions
function deleteFolder(folderId) {
    if (!confirm('Are you sure you want to delete this folder and all its contents?')) {
        return;
    }

    fetch(`/delete_folder/${folderId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            displayToast('Folder deleted successfully', 'success');
            location.reload();
        } else {
            displayToast(data.error || 'Failed to delete folder', 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        displayToast('An error occurred while deleting the folder', 'error');
    });
}

function deleteSelectedFolders() {
    const selectedFolders = Array.from(document.querySelectorAll('.folder-checkbox:checked')).map(cb => cb.value);
    
    if (selectedFolders.length === 0) {
        displayToast('Please select at least one folder to delete', 'warning');
        return;
    }

    if (!confirm(`Are you sure you want to delete ${selectedFolders.length} folder${selectedFolders.length > 1 ? 's' : ''}? All models in these folders will be moved to the root folder.`)) {
        return;
    }

    // Delete each folder
    let successCount = 0;
    let failCount = 0;
    let promises = selectedFolders.map(folderId => 
        fetch(`/delete_folder/${folderId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                successCount++;
            } else {
                failCount++;
                console.error(`Failed to delete folder ${folderId}:`, data.message);
            }
        })
        .catch(error => {
            failCount++;
            console.error(`Error deleting folder ${folderId}:`, error);
        })
    );

    // Wait for all deletions to complete
    Promise.all(promises)
        .then(() => {
            if (successCount > 0) {
                displayToast(`Successfully deleted ${successCount} folder${successCount > 1 ? 's' : ''}${failCount > 0 ? `, failed to delete ${failCount}` : ''}`, 'success');
                location.reload();
            } else {
                displayToast(`Failed to delete folders`, 'error');
            }
        });
}

function showCreateFolderModal() {
    const modal = document.getElementById('createFolderModal');
    if (modal) {
        modal.style.display = 'block';
    }
}

function hideCreateFolderModal() {
    const modal = document.getElementById('createFolderModal');
    if (modal) {
        modal.style.display = 'none';
        // Reset form
        const form = document.getElementById('createFolderForm');
        if (form) {
            form.reset();
        }
    }
}

function createFolder(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    fetch('/create_folder', {
        method: 'POST',
        body: formData
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        window.location.reload();
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Failed to create folder');
    });
}

// Model Movement Functions
let selectedModelId = null;

function showMoveToFolderModal(modelId) {
    selectedModelId = modelId;
    document.getElementById('moveToFolderModal').style.display = 'block';
}

function moveModelToFolder(modelIdOrFolderId, folderId = null) {
    // If only one parameter is provided, it's the folder ID (modal case)
<<<<<<< HEAD
    const targetFolderId = folderId !== null ? folderId : (modelIdOrFolderId === 'null' ? null : parseInt(modelIdOrFolderId));
    const targetModelId = folderId !== null ? parseInt(modelIdOrFolderId) : selectedModelId;
=======
    const targetFolderId = folderId !== null ? folderId : modelIdOrFolderId;
    const targetModelId = folderId !== null ? modelIdOrFolderId : selectedModelId;
>>>>>>> 4093290bd781a426eb457d791906d2fd7644ee15

    if (!targetModelId) {
        displayToast('No model selected', 'error');
        return;
    }

    fetch('/move_model', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            model_id: targetModelId,
            folder_id: targetFolderId
        })
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(data => {
                throw new Error(data.error || 'Failed to move model');
            });
        }
        return response.json();
    })
    .then(data => {
        if (data.success) {
            // Remove the model card from the current view
            const modelCard = document.querySelector(`[data-model-id="${targetModelId}"]`);
            if (modelCard) {
                modelCard.remove();
            }
            displayToast('Model moved successfully', 'success');
            hideMoveToFolderModal();
<<<<<<< HEAD
            location.reload();
=======
>>>>>>> 4093290bd781a426eb457d791906d2fd7644ee15
        } else {
            throw new Error(data.error || 'Failed to move model');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        displayToast(error.message, 'error');
    });
}

function hideMoveToFolderModal() {
    document.getElementById('moveToFolderModal').style.display = 'none';
    selectedModelId = null;
}

function showMoveSelectedModal() {
    if (selectedModels.size === 0) {
        displayToast('Please select at least one model to move', 'warning');
        return;
    }
    document.getElementById('moveSelectedModal').classList.remove('hidden');
}

function hideMoveSelectedModal() {
    document.getElementById('moveSelectedModal').classList.add('hidden');
}

function moveSelectedModels() {
    const targetFolderId = document.getElementById('targetFolderId').value;
    
    fetch('/move_selected_models', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            model_ids: Array.from(selectedModels),
            folder_id: targetFolderId || null
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            hideMoveSelectedModal();
            displayToast('Models moved successfully', 'success');
            setTimeout(() => {
                location.reload();
            }, 1000);
        } else {
            throw new Error(data.error || 'Failed to move models');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        displayToast(error.message || 'Failed to move models', 'error');
    });
}

// Model Selection Functions
let selectedModels = new Set();

function toggleModelSelection(event, modelId, card) {
    event.preventDefault();
    event.stopPropagation();
    
    if (selectedModels.has(modelId)) {
        selectedModels.delete(modelId);
        card.classList.remove('selected');
        card.querySelector('.selected-overlay').style.opacity = '0';
    } else {
        selectedModels.add(modelId);
        card.classList.add('selected');
        card.querySelector('.selected-overlay').style.opacity = '0.3';
    }
    
    // Update delete button visibility
    const deleteButton = document.getElementById('deleteSelectedBtn');
    if (deleteButton) {
        deleteButton.classList.toggle('hidden', selectedModels.size === 0);
    }
}

function updateDeleteButtonVisibility() {
    const deleteButton = document.getElementById('deleteSelectedBtn');
    if (deleteButton) {
        deleteButton.style.display = selectedModels.size > 0 ? 'inline-flex' : 'none';
    }
}

// Navigation Functions
function navigateToFolder(folderId) {
    window.location.href = `/my_models/${folderId}`;
}

function navigateBack() {
    window.history.back();
}

function showUploadModal() {
    window.location.href = "/";  // Redirect to home page for upload
}

// Drag and Drop Functions
function handleDragStart(event) {
    event.dataTransfer.setData('text/plain', event.target.dataset.modelId);
    event.target.classList.add('dragging');
}

function handleDragEnd(event) {
    event.target.classList.remove('dragging');
}

function handleDragOver(event) {
    event.preventDefault();
    const folderCard = event.target.closest('.folder-card');
    if (folderCard) {
        folderCard.classList.add('drag-over');
    }
}

function handleDragLeave(event) {
    event.preventDefault();
    const folderCard = event.target.closest('.folder-card');
    if (folderCard) {
        folderCard.classList.remove('drag-over');
    }
}

function handleDrop(event) {
    event.preventDefault();
    const folderCard = event.target.closest('.folder-card');
    if (!folderCard) return;

    folderCard.classList.remove('drag-over');
    const modelId = event.dataTransfer.getData('text/plain');
    const folderId = folderCard.dataset.folderId;

    moveModelToFolder(modelId, folderId);
}

// Utility Functions
function displayToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `fixed bottom-4 right-4 p-4 rounded-lg shadow-lg ${
        type === 'error' ? 'bg-red-500' : 
        type === 'success' ? 'bg-green-500' : 
        type === 'warning' ? 'bg-yellow-500' : 
        'bg-blue-500'
    } text-white z-50`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.remove();
    }, 3000);
}

function updateDeleteButtonVisibility() {
    const selectedCount = document.querySelectorAll('.model-checkbox:checked').length;
    const deleteButton = document.getElementById('deleteSelectedBtn');
    if (selectedCount > 0) {
        deleteButton.classList.remove('hidden');
        deleteButton.textContent = `Delete Selected (${selectedCount})`;
    } else {
        deleteButton.classList.add('hidden');
    }
}

// Event Listeners
document.addEventListener('DOMContentLoaded', function() {
    // Form Listeners
    const createFolderForm = document.getElementById('createFolderForm');
    if (createFolderForm) {
        createFolderForm.addEventListener('submit', function(event) {
            event.preventDefault();
            createFolder(event);
        });
    }

    // Folder Checkbox Listeners
    const folderCheckboxes = document.querySelectorAll('.folder-checkbox');
    folderCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', updateDeleteFoldersButtonVisibility);
    });

    // Modal Listeners
    const createFolderModal = document.getElementById('createFolderModal');
    if (createFolderModal) {
        createFolderModal.addEventListener('click', function(e) {
            if (e.target === this) {
                hideCreateFolderModal();
            }
        });
    }

    // Initialize select all checkbox
    const selectAllCheckbox = document.getElementById('selectAllModels');
    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', function() {
            toggleAllModels(this);
        });
    }

    // Initialize model checkboxes
    document.querySelectorAll('.model-checkbox').forEach(checkbox => {
        checkbox.addEventListener('change', function(e) {
            const modelId = this.dataset.modelId;
            const card = this.closest('.model-card');
            toggleModelSelection(e, modelId, card);
        });
    });

    // Initialize color picker checkbox
    const colorPickerCheckbox = document.getElementById('useColor');
    const colorPickerContainer = document.getElementById('colorPickerContainer');
    if (colorPickerCheckbox && colorPickerContainer) {
        colorPickerCheckbox.addEventListener('change', function() {
            if (this.checked) {
                colorPickerContainer.classList.remove('hidden');
            } else {
                colorPickerContainer.classList.add('hidden');
            }
        });
    }
});

// Search functionality
const modelSearch = document.getElementById('modelSearch');
const sortFilter = document.getElementById('sortFilter');
const modelsGrid = document.querySelector('.grid');

function filterModels() {
    const searchTerm = modelSearch.value.toLowerCase();
    const modelCards = document.querySelectorAll('.grid > div');

    modelCards.forEach(card => {
        const modelName = card.querySelector('h3').textContent.toLowerCase();
        if (modelName.includes(searchTerm)) {
            card.style.display = '';
        } else {
            card.style.display = 'none';
        }
    });
}

function sortModels() {
    const modelCards = Array.from(document.querySelectorAll('.grid > div'));
    const sortValue = sortFilter.value;

    modelCards.sort((a, b) => {
        const aName = a.querySelector('h3').textContent;
        const bName = b.querySelector('h3').textContent;
        const aDate = a.querySelector('.upload-date').textContent;
        const bDate = b.querySelector('.upload-date').textContent;
        const aSize = a.querySelector('.file-size').textContent;
        const bSize = b.querySelector('.file-size').textContent;

        switch (sortValue) {
            case 'name':
                return aName.localeCompare(bName);
            case 'newest':
                return new Date(bDate) - new Date(aDate);
            case 'oldest':
                return new Date(aDate) - new Date(bDate);
            case 'size':
                return parseFloat(bSize) - parseFloat(aSize);
            default:
                return 0;
        }
    });

    const parent = document.querySelector('.grid');
    modelCards.forEach(card => parent.appendChild(card));
}

modelSearch.addEventListener('input', filterModels);
sortFilter.addEventListener('change', sortModels);

// Initialize drag and drop when document is ready
document.addEventListener('DOMContentLoaded', function() {
    // Initialize drag events for model cards
    document.querySelectorAll('.model-card').forEach(card => {
        card.setAttribute('draggable', 'true');
        card.addEventListener('dragstart', handleDragStart);
        card.addEventListener('dragend', handleDragEnd);
    });

    // Initialize drop events for folder cards
    document.querySelectorAll('.folder-card').forEach(folder => {
        folder.addEventListener('dragover', handleDragOver);
        folder.addEventListener('dragleave', handleDragLeave);
        folder.addEventListener('drop', handleDrop);
    });
});
