// Selection Management
let selectedModels = new Set();
let isSelectionMode = false;

// Make functions globally accessible
window.toggleSelectMode = function() {
    isSelectionMode = !isSelectionMode;
    
    const body = document.body;
    const selectModeBtn = document.getElementById('selectModeBtn');
    const cancelSelectBtn = document.getElementById('cancelSelectBtn');
    const selectionControls = document.getElementById('selectionControls');
    
    if (isSelectionMode) {
        // Enter selection mode
        body.classList.add('selection-mode');
        selectModeBtn.classList.add('hidden');
        cancelSelectBtn.classList.remove('hidden');
        selectionControls.classList.remove('hidden');
        selectionControls.classList.add('flex');
    } else {
        // Exit selection mode
        body.classList.remove('selection-mode');
        selectModeBtn.classList.remove('hidden');
        cancelSelectBtn.classList.add('hidden');
        selectionControls.classList.add('hidden');
        selectionControls.classList.remove('flex');
        
        // Clear all selections
        clearSelection();
    }
}

function updateSelectionUI() {
    const count = selectedModels.size;
    const deleteBtn = document.getElementById('deleteSelectedBtn');
    const moveBtn = document.getElementById('moveSelectedBtn');
    const selectionCount = document.getElementById('selectionCount');
    const selectAllCheckbox = document.getElementById('selectAllCheckbox');

    // Update count badge
    selectionCount.textContent = `${count} selected`;

    // Show/hide bulk action buttons
    if (count > 0) {
        deleteBtn.classList.remove('hidden');
        moveBtn?.classList.remove('hidden');
    } else {
        deleteBtn.classList.add('hidden');
        moveBtn?.classList.add('hidden');
    }
    
    // Update select all checkbox
    const totalModels = document.querySelectorAll('.model-card').length;
    if (count === totalModels && totalModels > 0) {
        selectAllCheckbox.checked = true;
        selectAllCheckbox.indeterminate = false;
    } else if (count > 0) {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = true;
    } else {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = false;
    }
}

window.toggleModelSelection = function(event, modelId, cardElement) {
    // Only allow selection in selection mode
    if (!isSelectionMode) {
        // In normal mode, navigate to model view
        if (event.target.tagName !== 'BUTTON' && event.target.tagName !== 'A') {
            viewModel(modelId);
        }
        return;
    }
    
    // In selection mode, toggle selection
    if (event.target.tagName !== 'BUTTON' && event.target.tagName !== 'A') {
        event.preventDefault();
        event.stopPropagation();
        
        const checkbox = cardElement.querySelector('.model-checkbox');
        
        if (selectedModels.has(modelId)) {
            selectedModels.delete(modelId);
            cardElement.classList.remove('selected');
            if (checkbox) checkbox.checked = false;
        } else {
            selectedModels.add(modelId);
            cardElement.classList.add('selected');
            if (checkbox) checkbox.checked = true;
        }
        
        updateSelectionUI();
    }
}

window.toggleSelectAll = function(checked) {
    const modelCards = document.querySelectorAll('.model-card');
    
    if (checked) {
        modelCards.forEach(card => {
            const modelId = card.dataset.modelId;
            selectedModels.add(modelId);
            card.classList.add('selected');
            const checkbox = card.querySelector('.model-checkbox');
            if (checkbox) checkbox.checked = true;
        });
    } else {
        clearSelection();
    }
    
    updateSelectionUI();
}

window.clearSelection = function() {
    selectedModels.clear();
    document.querySelectorAll('.model-card').forEach(card => {
        card.classList.remove('selected');
        const checkbox = card.querySelector('.model-checkbox');
        if (checkbox) checkbox.checked = false;
    });
    updateSelectionUI();
}

// Model Management Functions
async function deleteModel(modelId) {
    const confirmed = confirm('Move this model to trash? You can restore it later from the Trash section.');
    if (!confirmed) return;

    try {
        const response = await fetch(`/delete_model/${modelId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (response.ok) {
            displayToast('Model moved to trash', 'success');
            location.reload();
        } else {
            throw new Error('Failed to delete model');
        }
    } catch (error) {
        console.error('Error:', error);
        displayToast('Failed to move model to trash', 'error');
    }
}

async function restoreModel(modelId) {
    try {
        const response = await fetch(`/restore_model/${modelId}`, { method: 'POST' });
        if (!response.ok) throw new Error('Restore failed');
        displayToast('Model restored', 'success');
        location.reload();
    } catch (error) {
        console.error('Error:', error);
        displayToast('Failed to restore model', 'error');
    }
}

async function deleteForever(modelId) {
    const confirmed = confirm('Permanently delete this model? This cannot be undone.');
    if (!confirmed) return;

    try {
        const response = await fetch(`/delete_model/${modelId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ permanent: true })
        });
        if (!response.ok) throw new Error('Delete failed');
        document.querySelector(`.trash-row[data-model-id="${modelId}"]`)?.remove();
        displayToast('Model permanently deleted', 'success');
    } catch (error) {
        console.error('Error:', error);
        displayToast('Failed to delete model', 'error');
    }
}

async function deleteSelectedModels() {
    if (selectedModels.size === 0) return;

    const confirmed = confirm(`Move ${selectedModels.size} selected model(s) to trash?`);
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
    window.location.href = `/view/${modelId}`;
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
let bulkMoveMode = false;

function showMoveToFolderModal(modelId) {
    selectedModelId = modelId;
    bulkMoveMode = false;
    document.getElementById('moveToFolderModal').style.display = 'block';
}

function showBulkMoveModal() {
    if (selectedModels.size === 0) {
        displayToast('Select at least one model first', 'warning');
        return;
    }
    selectedModelId = null;
    bulkMoveMode = true;
    document.getElementById('moveToFolderModal').style.display = 'block';
}

function moveSelectedToFolder(folderId) {
    fetch('/move_selected_models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            model_ids: Array.from(selectedModels),
            folder_id: folderId
        })
    })
    .then(response => response.json())
    .then(data => {
        if (!data.success) throw new Error(data.error || 'Failed to move models');
        hideMoveToFolderModal();
        displayToast(`Moved ${selectedModels.size} model(s)`, 'success');
        setTimeout(() => location.reload(), 600);
    })
    .catch(error => {
        console.error('Error:', error);
        displayToast(error.message || 'Failed to move models', 'error');
    });
}

function moveModelToFolder(modelIdOrFolderId, folderId = null) {
    // Bulk mode: the modal option passes only the target folder id (or null=root)
    if (bulkMoveMode && folderId === null) {
        moveSelectedToFolder(modelIdOrFolderId);
        return;
    }

    // If only one parameter is provided, it's the folder ID (modal case)
    const targetFolderId = folderId !== null ? folderId : modelIdOrFolderId;
    const targetModelId = folderId !== null ? modelIdOrFolderId : selectedModelId;

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
    bulkMoveMode = false;
}

// ── Inline rename (model display_name / folder name) ──
function inlineRename(h3, onSave) {
    if (!h3 || h3.querySelector('input')) return;
    const oldName = h3.textContent.trim();
    const input = document.createElement('input');
    input.type = 'text';
    input.value = oldName;
    input.className = 'rename-input';
    input.addEventListener('click', e => e.stopPropagation());
    h3.textContent = '';
    h3.appendChild(input);
    input.focus();
    input.select();

    let done = false;
    function finish(save) {
        if (done) return;
        done = true;
        const value = input.value.trim();
        h3.textContent = (save && value) ? value : oldName;
        if (save && value && value !== oldName) onSave(value, () => { h3.textContent = oldName; });
    }
    input.addEventListener('keydown', e => {
        e.stopPropagation();
        if (e.key === 'Enter') finish(true);
        if (e.key === 'Escape') finish(false);
    });
    input.addEventListener('blur', () => finish(true));
}

function startRenameModel(modelId) {
    const h3 = document.querySelector(`.model-name[data-model-id="${modelId}"]`);
    inlineRename(h3, (value, revert) => {
        fetch(`/api/models/${modelId}/metadata`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ display_name: value })
        })
        .then(r => {
            if (!r.ok) throw new Error('Rename failed');
            displayToast('Model renamed', 'success');
        })
        .catch(() => { revert(); displayToast('Failed to rename model', 'error'); });
    });
}

function startRenameFolder(folderId) {
    const h3 = document.querySelector(`.folder-name[data-folder-id="${folderId}"]`);
    inlineRename(h3, (value, revert) => {
        fetch(`/rename_folder/${folderId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: value })
        })
        .then(r => r.json())
        .then(data => {
            if (!data.success) throw new Error(data.error || 'Rename failed');
            displayToast('Folder renamed', 'success');
        })
        .catch(err => { revert(); displayToast(err.message || 'Failed to rename folder', 'error'); });
    });
}

// ── Copy share link ──
function copyModelLink(modelId) {
    const url = `${location.origin}/view/${modelId}`;
    navigator.clipboard.writeText(url)
        .then(() => displayToast('Link copied to clipboard', 'success'))
        .catch(() => {
            // Fallback for non-secure contexts
            const ta = document.createElement('textarea');
            ta.value = url;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            ta.remove();
            displayToast('Link copied to clipboard', 'success');
        });
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
    toast.className = `library-toast library-toast--${type}`;
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
    // Note: createFolderForm submits via its inline onsubmit="createFolder(event)";
    // a second submit listener here would double-POST and create duplicate folders.

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

    // Note: .model-checkbox selection is handled by its inline onclick only;
    // adding a change listener here would double-toggle and cancel the selection.

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
const modelsGrid = document.getElementById('modelsGrid');

// ── Batched rendering: show cards in chunks to keep first paint light ──
const BATCH_SIZE = 24;
let visibleCount = BATCH_SIZE;

function applyBatch() {
    if (!modelsGrid) return;
    const cards = Array.from(modelsGrid.querySelectorAll('.model-card'));
    const loadMoreBtn = document.getElementById('loadMoreBtn');
    const searching = modelSearch && modelSearch.value.trim() !== '';
    if (searching) {
        loadMoreBtn?.classList.add('hidden');
        return; // filterModels controls visibility while searching
    }
    cards.forEach((card, i) => {
        card.style.display = i < visibleCount ? '' : 'none';
    });
    loadMoreBtn?.classList.toggle('hidden', visibleCount >= cards.length);
}

function revealNextBatch() {
    visibleCount += BATCH_SIZE;
    applyBatch();
}

function filterModels() {
    if (!modelSearch) return;
    const searchTerm = modelSearch.value.trim().toLowerCase();

    if (modelsGrid) {
        if (searchTerm === '') {
            applyBatch(); // restore batched view
        } else {
            modelsGrid.querySelectorAll('.model-card').forEach(card => {
                const modelName = (card.querySelector('h3')?.textContent || '').toLowerCase();
                card.style.display = modelName.includes(searchTerm) ? '' : 'none';
            });
            document.getElementById('loadMoreBtn')?.classList.add('hidden');
        }
    }

    // Folders are searchable too
    document.querySelectorAll('.library-folder').forEach(card => {
        const folderName = (card.querySelector('h3')?.textContent || '').toLowerCase();
        card.style.display = (searchTerm === '' || folderName.includes(searchTerm)) ? '' : 'none';
    });
}

function sortModels() {
    if (!sortFilter || !modelsGrid) return;
    const modelCards = Array.from(modelsGrid.querySelectorAll('.model-card'));
    const sortValue = sortFilter.value;

    // Sort on data attributes (raw timestamp / byte count) rather than the
    // formatted display text, which is locale-dependent and unit-suffixed.
    modelCards.sort((a, b) => {
        switch (sortValue) {
            case 'name': {
                const aName = a.querySelector('h3')?.textContent || '';
                const bName = b.querySelector('h3')?.textContent || '';
                return aName.localeCompare(bName);
            }
            case 'newest':
                return parseFloat(b.dataset.uploadTs || 0) - parseFloat(a.dataset.uploadTs || 0);
            case 'oldest':
                return parseFloat(a.dataset.uploadTs || 0) - parseFloat(b.dataset.uploadTs || 0);
            case 'size':
                return parseFloat(b.dataset.sizeBytes || 0) - parseFloat(a.dataset.sizeBytes || 0);
            default:
                return 0;
        }
    });

    modelCards.forEach(card => modelsGrid.appendChild(card));
    applyBatch(); // card order changed; re-apply which ones are visible
}

modelSearch?.addEventListener('input', filterModels);
sortFilter?.addEventListener('change', () => {
    localStorage.setItem('myModelsSort', sortFilter.value);
    sortModels();
});

// Restore persisted sort + initial batch on load
document.addEventListener('DOMContentLoaded', () => {
    const savedSort = localStorage.getItem('myModelsSort');
    if (savedSort && sortFilter && [...sortFilter.options].some(o => o.value === savedSort)) {
        sortFilter.value = savedSort;
        sortModels();
    } else {
        applyBatch();
    }
});

// ── Hover 3D preview: swap the screenshot for a live <model-viewer> ──
// Only on devices with real hover (skip touch); only one viewer alive at a time.
(function initHoverPreview() {
    if (!window.matchMedia('(hover: hover) and (pointer: fine)').matches) return;

    let scriptInjected = false;
    let activeViewer = null;

    function ensureModelViewerScript() {
        if (scriptInjected || customElements.get('model-viewer')) { scriptInjected = true; return; }
        scriptInjected = true;
        const s = document.createElement('script');
        s.type = 'module';
        s.src = 'https://unpkg.com/@google/model-viewer@4.2.0/dist/model-viewer.min.js';
        document.head.appendChild(s);
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('.library-preview[data-glb]').forEach(box => {
            let timer = null;

            box.addEventListener('mouseenter', () => {
                if (document.body.classList.contains('selection-mode')) return;
                ensureModelViewerScript();
                timer = setTimeout(() => {
                    if (activeViewer) activeViewer.remove();
                    const mv = document.createElement('model-viewer');
                    mv.src = box.dataset.glb;
                    mv.setAttribute('auto-rotate', '');
                    mv.setAttribute('disable-zoom', '');
                    mv.setAttribute('interaction-prompt', 'none');
                    mv.className = 'hover-preview';
                    box.appendChild(mv);
                    activeViewer = mv;
                }, 350);
            });

            box.addEventListener('mouseleave', () => {
                clearTimeout(timer);
                if (activeViewer && activeViewer.parentElement === box) {
                    activeViewer.remove();
                    activeViewer = null;
                }
            });
        });
    });
})();

// Drag & drop handlers are wired via inline attributes in the template
// (ondragstart/ondragend on cards, ondragover/ondragleave/ondrop on folders).
// Registering them again here would fire each drop twice (double POST/toast).
