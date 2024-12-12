document.addEventListener('DOMContentLoaded', function() {
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const fileList = document.getElementById('fileList');
    const selectedFiles = document.getElementById('selectedFiles');
    const overallProgress = document.getElementById('overallProgress');
    const overallProgressBar = document.getElementById('overallProgressBar');
    const overallProgressText = document.getElementById('overallProgressText');
    const convertButton = document.getElementById('convertButton');
    const uploadForm = document.getElementById('uploadForm');

    // Prevent default drag behaviors
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
        document.body.addEventListener(eventName, preventDefaults, false);
    });

    // Highlight drop zone when item is dragged over it
    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, highlight, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, unhighlight, false);
    });

    // Handle dropped files
    dropZone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        handleFiles(dt.files);
    });

    // Handle selected files
    fileInput.addEventListener('change', (e) => {
        handleFiles(e.target.files);
    });

    function handleFiles(files) {
        Array.from(files).forEach(file => {
            // Check file size
            if (file.size > 50 * 1024 * 1024) { // 50MB limit
                showError(`File ${file.name} exceeds 50MB limit`);
                return;
            }

            // Check file type
            const ext = file.name.split('.').pop().toLowerCase();
            if (!['obj', 'fbx', 'stl'].includes(ext)) {
                showError(`File ${file.name} is not a supported format`);
                return;
            }

            // Add to file list
            const fileItem = createFileListItem(file);
            fileList.appendChild(fileItem);
        });

        selectedFiles.classList.remove('hidden');
        updateConvertButtonState();
    }

    function createFileListItem(file) {
        const div = document.createElement('div');
        div.className = 'flex items-center justify-between p-2 bg-gray-50 dark:bg-gray-700 rounded-lg';
        
        const fileInfo = document.createElement('div');
        fileInfo.className = 'flex items-center space-x-2';
        
        const fileName = document.createElement('span');
        fileName.className = 'text-sm text-gray-700 dark:text-gray-300';
        fileName.textContent = file.name;
        
        const fileSize = document.createElement('span');
        fileSize.className = 'text-xs text-gray-500 dark:text-gray-400';
        fileSize.textContent = formatFileSize(file.size);
        
        const removeButton = document.createElement('button');
        removeButton.className = 'text-red-500 hover:text-red-700 dark:hover:text-red-400';
        removeButton.innerHTML = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>';
        removeButton.onclick = () => {
            div.remove();
            updateConvertButtonState();
        };
        
        fileInfo.appendChild(fileName);
        fileInfo.appendChild(fileSize);
        div.appendChild(fileInfo);
        div.appendChild(removeButton);
        
        return div;
    }

    function updateConvertButtonState() {
        const hasFiles = fileList.children.length > 0;
        convertButton.disabled = !hasFiles;
        if (hasFiles) {
            convertButton.classList.remove('opacity-50', 'cursor-not-allowed');
        } else {
            convertButton.classList.add('opacity-50', 'cursor-not-allowed');
        }
    }

    uploadForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        const formData = new FormData();
        const files = Array.from(fileList.children).map(item => {
            const fileName = item.querySelector('span').textContent;
            return Array.from(fileInput.files).find(file => file.name === fileName);
        }).filter(Boolean);
        
        if (files.length === 0) {
            showError('Please select at least one file');
            return;
        }
        
        files.forEach(file => {
            formData.append('files[]', file);
        });
        
        // Show progress
        overallProgress.classList.remove('hidden');
        convertButton.disabled = true;
        
        try {
            const response = await fetch('/convert_multiple', {
                method: 'POST',
                body: formData
            });
            
            if (!response.ok) {
                const data = await response.json();
                throw new Error(data.error || 'Conversion failed');
            }
            
            const data = await response.json();
            
            if (data.success) {
                // Download zip file
                window.location.href = data.zip_url;
                
                // Show appropriate message based on authentication status
                if (!data.is_authenticated) {
                    showLoginPrompt(data.login_url);
                } else {
                    showSuccess('Conversion complete! Downloading files... Your models have been saved to your account.');
                }
                
                // Clear file list
                fileList.innerHTML = '';
                selectedFiles.classList.add('hidden');
                updateConvertButtonState();
            } else {
                throw new Error(data.error || 'Conversion failed');
            }
        } catch (error) {
            showError('Conversion error: ' + error.message);
            console.error('Conversion error:', error);
        } finally {
            overallProgress.classList.add('hidden');
            convertButton.disabled = false;
        }
    });

    function formatFileSize(bytes) {
        const units = ['B', 'KB', 'MB', 'GB'];
        let size = bytes;
        let unitIndex = 0;
        
        while (size >= 1024 && unitIndex < units.length - 1) {
            size /= 1024;
            unitIndex++;
        }
        
        return `${size.toFixed(1)} ${units[unitIndex]}`;
    }

    function showError(message) {
        // Implement error notification
        alert(message);
    }

    function showSuccess(message) {
        // Implement success notification
        alert(message);
    }

    function showLoginPrompt(loginUrl) {
        const message = `
            <div class="fixed inset-0 bg-gray-600 bg-opacity-50 flex items-center justify-center">
                <div class="bg-white dark:bg-gray-800 p-6 rounded-lg shadow-xl max-w-md w-full mx-4">
                    <h3 class="text-lg font-semibold mb-4 text-gray-900 dark:text-white">Save Your Models</h3>
                    <p class="text-gray-600 dark:text-gray-300 mb-6">
                        Your models have been converted successfully! To access them later, please log in or create an account.
                    </p>
                    <div class="flex justify-end space-x-4">
                        <button onclick="this.closest('div.fixed').remove()" class="px-4 py-2 text-gray-600 dark:text-gray-400">
                            Maybe Later
                        </button>
                        <a href="${loginUrl}" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
                            Log In / Sign Up
                        </a>
                    </div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', message);
    }

    function highlight(e) {
        dropZone.classList.add('border-primary');
    }

    function unhighlight(e) {
        dropZone.classList.remove('border-primary');
    }

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }
});
