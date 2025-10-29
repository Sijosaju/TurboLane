// // static/app.js - Professional Download Manager with File Manager
// class DownloadManager {
//     constructor() {
//         this.activeDownloads = new Map();
//         this.updateInterval = null;
//         this.currentPage = 'downloads';
//         this.init();
//     }

//     init() {
//         // Form submission
//         document.getElementById('downloadForm').addEventListener('submit', (e) => {
//             e.preventDefault();
//             this.startDownload();
//         });

//         // Mode change handler
//         document.querySelectorAll('input[name="mode"]').forEach(radio => {
//             radio.addEventListener('change', () => {
//                 this.toggleStreamsControl();
//             });
//         });

//         // Close metrics handler
//         document.getElementById('closeMetrics').addEventListener('click', () => {
//             document.getElementById('metricsCard').classList.add('d-none');
//         });

//         // File Manager handlers
//         document.getElementById('refreshFiles').addEventListener('click', () => {
//             this.loadFiles();
//         });

//         document.getElementById('openDownloadsFolder').addEventListener('click', () => {
//             this.openDownloadsFolder();
//         });

//         // Navigation handlers
//         document.querySelectorAll('.nav-link').forEach(link => {
//             link.addEventListener('click', (e) => {
//                 e.preventDefault();
//                 const page = e.target.closest('.nav-link').dataset.page;
//                 this.switchPage(page);
//             });
//         });

//         this.toggleStreamsControl();
//         this.startUpdateInterval();
//         this.loadFiles(); // Load files on initial page load
//     }

//     switchPage(page) {
//         // Update navigation
//         document.querySelectorAll('.nav-link').forEach(link => {
//             link.classList.remove('active');
//         });
//         document.querySelector(`[data-page="${page}"]`).classList.add('active');

//         // Update page content
//         document.querySelectorAll('.page-section').forEach(section => {
//             section.classList.remove('active');
//         });
//         document.getElementById(`${page}-page`).classList.add('active');

//         this.currentPage = page;

//         // Load files if switching to file manager
//         if (page === 'files') {
//             this.loadFiles();
//         }
//     }

//     toggleStreamsControl() {
//         const mode = document.querySelector('input[name="mode"]:checked').value;
//         const streamsInput = document.getElementById('numStreams');
//         streamsInput.disabled = mode === 'single';
//     }

//     async startDownload() {
//         const url = document.getElementById('url').value;
//         const mode = document.querySelector('input[name="mode"]:checked').value;
//         const numStreams = document.getElementById('numStreams').value;

//         if (!url) {
//             this.showAlert('Please enter a URL', 'danger');
//             return;
//         }

//         if (!url.startsWith('http://') && !url.startsWith('https://')) {
//             this.showAlert('URL must start with http:// or https://', 'danger');
//             return;
//         }

//         try {
//             const response = await fetch('/api/downloads', {
//                 method: 'POST',
//                 headers: {
//                     'Content-Type': 'application/json',
//                 },
//                 body: JSON.stringify({
//                     url: url,
//                     mode: mode,
//                     num_streams: parseInt(numStreams)
//                 })
//             });

//             const data = await response.json();

//             if (response.ok) {
//                 this.addDownloadItem(data.download_id, url, mode);
//                 document.getElementById('url').value = '';
//                 this.showAlert('Download started successfully', 'success');
//             } else {
//                 this.showAlert('Error: ' + data.error, 'danger');
//             }
//         } catch (error) {
//             this.showAlert('Error starting download: ' + error.message, 'danger');
//         }
//     }

//     addDownloadItem(downloadId, url, mode) {
//         // Hide "no active downloads" message
//         const noActiveDownloads = document.getElementById('noActiveDownloads');
//         if (noActiveDownloads) {
//             noActiveDownloads.style.display = 'none';
//         }

//         const template = document.getElementById('downloadItemTemplate');
//         const clone = template.content.cloneNode(true);

//         const downloadItem = clone.querySelector('.download-item');
//         downloadItem.id = `download-${downloadId}`;
//         downloadItem.dataset.downloadId = downloadId;
//         downloadItem.classList.add('downloading');

//         const urlElement = clone.querySelector('.url-text');
//         urlElement.textContent = this.getFilenameFromUrl(url);
//         urlElement.title = url;

//         const modeElement = clone.querySelector('.mode-text');
//         modeElement.textContent = `${mode === 'multi' ? 'Multi-Stream' : 'Single-Stream'} Download`;

//         const statusLine = clone.querySelector('.status-line');
//         statusLine.classList.add('downloading');

//         const progressBar = clone.querySelector('.progress-bar');
//         progressBar.classList.add('downloading');

//         // Add event listeners
//         clone.querySelector('.cancel-download').addEventListener('click', () => {
//             this.cancelDownload(downloadId);
//         });

//         clone.querySelector('.view-metrics').addEventListener('click', () => {
//             this.viewMetrics(downloadId);
//         });

//         document.getElementById('activeDownloads').appendChild(clone);
//         this.activeDownloads.set(downloadId, {
//             url: url,
//             mode: mode,
//             element: downloadItem,
//             status: 'downloading',
//             lastUpdate: Date.now(),
//             lastBytes: 0,
//             speedHistory: []
//         });

//         this.updateActiveCount();
//     }

//     updateActiveCount() {
//         const count = this.activeDownloads.size;
//         document.getElementById('activeCount').textContent = count;
//     }

//     async cancelDownload(downloadId) {
//         try {
//             const response = await fetch(`/api/downloads/${downloadId}/cancel`, {
//                 method: 'POST'
//             });

//             if (response.ok) {
//                 this.showAlert('Download cancelled', 'warning');
//             } else {
//                 const data = await response.json();
//                 this.showAlert('Error: ' + data.error, 'danger');
//             }
//         } catch (error) {
//             this.showAlert('Error cancelling download: ' + error.message, 'danger');
//         }
//     }

//     async viewMetrics(downloadId) {
//         try {
//             const response = await fetch(`/api/downloads/${downloadId}/metrics`);
//             if (response.ok) {
//                 const metrics = await response.json();
//                 this.displayMetrics(metrics, downloadId);
//             } else {
//                 this.showAlert('Metrics not available yet', 'warning');
//             }
//         } catch (error) {
//             this.showAlert('Error fetching metrics: ' + error.message, 'danger');
//         }
//     }

//     displayMetrics(metrics, downloadId) {
//         const metricsCard = document.getElementById('metricsCard');
//         const metricsDisplay = document.getElementById('metricsDisplay');

//         let metricsText = '═'.repeat(80) + '\n';
//         metricsText += '<strong>DOWNLOAD PERFORMANCE METRICS</strong>\n';
//         metricsText += '═'.repeat(80) + '\n\n';

//         if (metrics.num_streams_used !== undefined) {
//             metricsText += '<strong>OVERVIEW</strong>\n';
//             metricsText += '─'.repeat(80) + '\n';
//             metricsText += `Total Time : ${metrics.total_time_seconds?.toFixed(2) || 'N/A'} seconds\n`;
//             metricsText += `File Size : ${metrics.total_size_mb?.toFixed(2) || 'N/A'} MB\n`;
//             metricsText += `Streams Used : ${metrics.num_streams_used || 'N/A'}\n`;
//             metricsText += `Overall Throughput : ${metrics.throughput_mbps?.toFixed(2) || 'N/A'} Mbps (${metrics.throughput_MBps?.toFixed(2) || 'N/A'} MB/s)\n`;
//             metricsText += `Avg Speed/Stream : ${metrics.average_speed_per_stream?.toFixed(2) || 'N/A'} MB/s\n\n`;

//             if (metrics.chunk_metrics && metrics.chunk_metrics.length > 0) {
//                 metricsText += '<strong>STREAM BREAKDOWN</strong>\n';
//                 metricsText += '─'.repeat(80) + '\n';
//                 metricsText += `${'Stream'.padEnd(10)} ${'Size (MB)'.padEnd(15)} ${'Time (s)'.padEnd(15)} ${'Speed (MB/s)'.padEnd(15)}\n`;
//                 metricsText += '─'.repeat(80) + '\n';

//                 metrics.chunk_metrics.forEach(chunk => {
//                     const streamNum = `#${chunk.chunk_id}`;
//                     const size = chunk.size_mb?.toFixed(2) || 'N/A';
//                     const time = chunk.time_seconds?.toFixed(2) || 'N/A';
//                     const speed = chunk.speed_mbps?.toFixed(2) || 'N/A';
//                     metricsText += `${streamNum.padEnd(10)} ${size.padEnd(15)} ${time.padEnd(15)} ${speed.padEnd(15)}\n`;
//                 });

//                 if (metrics.fastest_chunk && metrics.slowest_chunk) {
//                     metricsText += '\n<strong>STATISTICS</strong>\n';
//                     metricsText += '─'.repeat(80) + '\n';
//                     metricsText += `Fastest Stream : #${metrics.fastest_chunk.chunk_id} at ${metrics.fastest_chunk.speed_mbps?.toFixed(2) || 'N/A'} MB/s\n`;
//                     metricsText += `Slowest Stream : #${metrics.slowest_chunk.chunk_id} at ${metrics.slowest_chunk.speed_mbps?.toFixed(2) || 'N/A'} MB/s\n`;
//                 }
//             }
//         } else {
//             metricsText += '<strong>OVERVIEW</strong>\n';
//             metricsText += '─'.repeat(80) + '\n';
//             metricsText += `Total Time : ${metrics.total_time?.toFixed(2) || 'N/A'} seconds\n`;
//             metricsText += `File Size : ${metrics.file_size_mb?.toFixed(2) || 'N/A'} MB\n`;
//             metricsText += `Download Mode : Single-Stream\n`;
//             metricsText += `Overall Throughput : ${metrics.throughput_mbps?.toFixed(2) || 'N/A'} Mbps (${metrics.throughput_MBps?.toFixed(2) || 'N/A'} MB/s)\n`;
//         }

//         metricsText += '\n' + '═'.repeat(80);

//         metricsDisplay.innerHTML = metricsText;
//         metricsCard.classList.remove('d-none');
//         metricsCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
//     }

//     async updateDownloadStatuses() {
//         if (this.activeDownloads.size === 0) return;

//         for (const [downloadId, info] of this.activeDownloads) {
//             try {
//                 const response = await fetch(`/api/downloads/${downloadId}`);
//                 if (response.ok) {
//                     const status = await response.json();
//                     this.updateDownloadUI(downloadId, status);

//                     if (['completed', 'failed', 'cancelled'].includes(status.status) && info.status === 'downloading') {
//                         info.status = status.status;
//                         setTimeout(() => {
//                             this.moveToHistory(downloadId, status);
//                         }, 3000);
//                     }
//                 }
//             } catch (error) {
//                 console.error('Error updating download status:', error);
//             }
//         }
//     }

//     updateDownloadUI(downloadId, status) {
//         const info = this.activeDownloads.get(downloadId);
//         if (!info) return;

//         const progressBar = info.element.querySelector('.progress-bar');
//         const speedText = info.element.querySelector('.speed-text');
//         const statusElement = info.element.querySelector('.status-text');
//         const statusLine = info.element.querySelector('.status-line');
//         const progressPercent = info.element.querySelector('.progress-percent');

//         const progress = Math.round(status.progress || 0);
//         progressBar.style.width = `${progress}%`;
//         progressPercent.textContent = `${progress}%`;

//         if (!info.speedHistory) info.speedHistory = [];

//         const now = Date.now();
//         const timeDiff = (now - info.lastUpdate) / 1000;
//         const bytesDiff = status.downloaded_size - info.lastBytes;
//         const frontendSpeed = timeDiff > 0 ? (bytesDiff / (1024 * 1024)) / timeDiff : status.speed || 0;

//         const currentSpeed = status.speed > 0 ? status.speed : frontendSpeed;

//         info.speedHistory.push(currentSpeed);
//         if (info.speedHistory.length > 5) info.speedHistory.shift();

//         const avgSpeed = info.speedHistory.reduce((sum, val) => sum + val, 0) / info.speedHistory.length;

//         if (status.total_size && status.downloaded_size !== undefined) {
//             const downloadedMB = (status.downloaded_size / (1024 * 1024)).toFixed(2);
//             const totalMB = (status.total_size / (1024 * 1024)).toFixed(2);
//             speedText.textContent = status.status === 'downloading' && avgSpeed > 0
//                 ? `${avgSpeed.toFixed(2)} MB/s • ${downloadedMB}/${totalMB} MB`
//                 : `${downloadedMB} MB / ${totalMB} MB`;
//         } else {
//             speedText.textContent = 'Calculating...';
//         }

//         info.lastUpdate = now;
//         info.lastBytes = status.downloaded_size || 0;

//         let statusClass = 'downloading';
//         let statusText = 'Downloading...';
//         let iconHtml = '<i class="fas fa-spinner fa-spin"></i>';

//         switch (status.status) {
//             case 'completed':
//                 statusClass = 'completed';
//                 statusText = 'Download completed';
//                 iconHtml = '<i class="fas fa-check-circle"></i>';
//                 // Refresh file manager when download completes
//                 if (this.currentPage === 'files') {
//                     this.loadFiles();
//                 }
//                 break;
//             case 'failed':
//                 statusClass = 'failed';
//                 statusText = `Failed: ${status.error || 'Unknown error'}`;
//                 iconHtml = '<i class="fas fa-exclamation-circle"></i>';
//                 break;
//             case 'cancelled':
//                 statusClass = 'cancelled';
//                 statusText = 'Download cancelled';
//                 iconHtml = '<i class="fas fa-times-circle"></i>';
//                 break;
//         }

//         statusElement.textContent = statusText;
//         statusLine.className = `status-line ${statusClass}`;
//         statusLine.querySelector('i').outerHTML = iconHtml;

//         progressBar.className = `progress-bar ${statusClass}`;
//         info.element.className = `download-item ${statusClass}`;
//     }

//     moveToHistory(downloadId, status) {
//         const info = this.activeDownloads.get(downloadId);
//         if (!info) return;

//         info.element.remove();
//         this.activeDownloads.delete(downloadId);

//         this.updateActiveCount();

//         if (this.activeDownloads.size === 0) {
//             const noActiveDownloads = document.getElementById('noActiveDownloads');
//             if (noActiveDownloads) {
//                 noActiveDownloads.style.display = 'block';
//             }
//         }

//         this.addToHistory(downloadId, info.url, info.mode, status);
//     }

//     addToHistory(downloadId, url, mode, status) {
//         const historyContainer = document.getElementById('downloadHistory');
//         const currentContent = historyContainer.innerHTML;

//         if (currentContent.includes('No download history yet')) {
//             historyContainer.innerHTML = '';
//         }

//         const template = document.getElementById('downloadItemTemplate');
//         const clone = template.content.cloneNode(true);

//         const historyItem = clone.querySelector('.download-item');
//         historyItem.className = `download-item ${status.status}`;
//         historyItem.id = `history-${downloadId}`;

//         const urlElement = clone.querySelector('.url-text');
//         urlElement.textContent = this.getFilenameFromUrl(url);
//         urlElement.title = url;

//         const modeElement = clone.querySelector('.mode-text');
//         const statusCapitalized = status.status.charAt(0).toUpperCase() + status.status.slice(1);
//         modeElement.textContent = `${mode === 'multi' ? 'Multi-Stream' : 'Single-Stream'} • ${statusCapitalized}`;

//         const statusElement = clone.querySelector('.status-text');
//         let statusText = statusCapitalized;
//         if (status.status === 'failed' && status.error) {
//             statusText = `Failed: ${status.error}`;
//         }
//         statusElement.textContent = statusText;

//         const statusLine = clone.querySelector('.status-line');
//         statusLine.className = `status-line ${status.status}`;

//         const icon = statusLine.querySelector('i');
//         if (status.status === 'completed') {
//             icon.className = 'fas fa-check-circle';
//         } else if (status.status === 'failed') {
//             icon.className = 'fas fa-exclamation-circle';
//         } else {
//             icon.className = 'fas fa-times-circle';
//         }

//         const progressBar = clone.querySelector('.progress-bar');
//         progressBar.style.width = '100%';
//         progressBar.className = `progress-bar ${status.status}`;

//         const progressPercent = clone.querySelector('.progress-percent');
//         progressPercent.textContent = '100%';

//         const speedText = clone.querySelector('.speed-text');
//         if (status.total_size) {
//             const totalMB = (status.total_size / (1024 * 1024)).toFixed(2);
//             speedText.textContent = `${totalMB} MB`;
//         } else if (status.metrics && status.metrics.total_time_seconds) {
//             speedText.textContent = `${status.metrics.total_time_seconds.toFixed(2)}s`;
//         } else if (status.metrics && status.metrics.total_time) {
//             speedText.textContent = `${status.metrics.total_time.toFixed(2)}s`;
//         } else {
//             speedText.textContent = 'Completed';
//         }

//         const cancelBtn = clone.querySelector('.cancel-download');
//         cancelBtn.remove();

//         const metricsBtn = clone.querySelector('.view-metrics');
//         metricsBtn.addEventListener('click', () => {
//             this.viewMetrics(downloadId);
//         });

//         if (status.status === 'completed' && status.filename) {
//             const openBtn = document.createElement('button');
//             openBtn.className = 'action-btn success';
//             openBtn.innerHTML = '<i class="fas fa-folder-open"></i>';
//             openBtn.title = 'Open File';
//             openBtn.onclick = () => {
//                 this.openFile(status.filename);
//             };
//             metricsBtn.parentNode.appendChild(openBtn);
//         }

//         historyContainer.appendChild(clone);
//     }

//     // File Manager Methods
//     async loadFiles() {
//         try {
//             const response = await fetch('/api/files');
//             if (response.ok) {
//                 const files = await response.json();
//                 console.log('Loaded files:', files); // Debug log
//                 this.displayFiles(files);
//             } else {
//                 this.showAlert('Error loading files', 'danger');
//             }
//         } catch (error) {
//             console.error('Error loading files:', error);
//             this.showAlert('Error loading files: ' + error.message, 'danger');
//         }
//     }

//     displayFiles(files) {
//         const fileManager = document.getElementById('fileManager');
//         const fileCount = document.getElementById('fileCount');
        
//         fileCount.textContent = files.length;

//         if (files.length === 0) {
//             fileManager.innerHTML = `
//                 <div class="empty-state">
//                     <i class="fas fa-folder-open"></i>
//                     <p>No files downloaded yet</p>
//                     <small class="text-muted">Downloaded files will appear here</small>
//                 </div>
//             `;
//             return;
//         }

//         fileManager.innerHTML = '';
//         const template = document.getElementById('fileItemTemplate');

//         files.forEach(file => {
//             const clone = template.content.cloneNode(true);
//             const fileItem = clone.querySelector('.file-item');
            
//             // Set file name
//             const fileName = clone.querySelector('.file-name');
//             fileName.textContent = file.name;
//             fileName.title = file.name;
            
//             // Set file size
//             const fileSize = clone.querySelector('.file-size');
//             fileSize.textContent = this.formatFileSize(file.size);
            
//             // Set file date with proper debugging
//             const fileDate = clone.querySelector('.file-date');
//             console.log('File timestamp:', file.name, file.modified, typeof file.modified); // Debug log
//             fileDate.textContent = this.formatFileDate(file.modified);
            
//             // Set file type icon
//             const fileIcon = clone.querySelector('.file-icon i');
//             const fileType = this.getFileType(file.name);
//             fileIcon.className = this.getFileIcon(fileType);
//             fileItem.classList.add(`file-${fileType}`);
            
//             // Add event listeners
//             clone.querySelector('.open-file').addEventListener('click', () => {
//                 this.openFile(file.name);
//             });
            
//             clone.querySelector('.download-file').addEventListener('click', () => {
//                 this.downloadFile(file.name);
//             });
            
//             clone.querySelector('.delete-file').addEventListener('click', () => {
//                 this.deleteFile(file.name);
//             });

//             fileManager.appendChild(clone);
//         });
//     }

//     getFileType(filename) {
//         const extension = filename.split('.').pop().toLowerCase();
//         const imageTypes = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg'];
//         const videoTypes = ['mp4', 'avi', 'mov', 'wmv', 'flv', 'webm', 'mkv'];
//         const audioTypes = ['mp3', 'wav', 'ogg', 'flac', 'aac', 'wma'];
//         const documentTypes = ['pdf', 'doc', 'docx', 'txt', 'rtf'];
//         const archiveTypes = ['zip', 'rar', '7z', 'tar', 'gz'];
//         const executableTypes = ['exe', 'msi', 'dmg', 'pkg', 'deb', 'rpm'];

//         if (imageTypes.includes(extension)) return 'image';
//         if (videoTypes.includes(extension)) return 'video';
//         if (audioTypes.includes(extension)) return 'audio';
//         if (documentTypes.includes(extension)) return 'document';
//         if (archiveTypes.includes(extension)) return 'zip';
//         if (executableTypes.includes(extension)) return 'executable';
//         return 'file';
//     }

//     getFileIcon(fileType) {
//         const icons = {
//             'image': 'fas fa-file-image',
//             'video': 'fas fa-file-video',
//             'audio': 'fas fa-file-audio',
//             'document': 'fas fa-file-pdf',
//             'zip': 'fas fa-file-archive',
//             'executable': 'fas fa-cog',
//             'file': 'fas fa-file'
//         };
//         return icons[fileType] || icons.file;
//     }

//     formatFileSize(bytes) {
//         if (bytes === 0) return '0 Bytes';
//         const k = 1024;
//         const sizes = ['Bytes', 'KB', 'MB', 'GB'];
//         const i = Math.floor(Math.log(bytes) / Math.log(k));
//         return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
//     }

//     formatFileDate(timestamp) {
//         try {
//             // If timestamp is in seconds (common from os.path.getmtime), convert to milliseconds
//             let date;
            
//             if (timestamp > 10000000000) {
//                 // Likely already in milliseconds
//                 date = new Date(timestamp);
//             } else {
//                 // Likely in seconds, convert to milliseconds
//                 date = new Date(timestamp * 1000);
//             }
            
//             // Validate the date
//             if (isNaN(date.getTime())) {
//                 console.warn('Invalid timestamp:', timestamp);
//                 return 'Invalid date';
//             }
            
//             // Format: "YYYY-MM-DD HH:MM:SS"
//             const year = date.getFullYear();
//             const month = String(date.getMonth() + 1).padStart(2, '0');
//             const day = String(date.getDate()).padStart(2, '0');
//             const hours = String(date.getHours()).padStart(2, '0');
//             const minutes = String(date.getMinutes()).padStart(2, '0');
//             const seconds = String(date.getSeconds()).padStart(2, '0');
            
//             return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
//         } catch (error) {
//             console.error('Error formatting date:', error);
//             return 'Date error';
//         }
//     }

//     async deleteFile(filename) {
//         if (!confirm(`Are you sure you want to delete "${filename}"?`)) {
//             return;
//         }

//         try {
//             // Properly encode the filename for URL
//             const encodedFilename = encodeURIComponent(filename);
//             const response = await fetch(`/api/files/${encodedFilename}`, {
//                 method: 'DELETE'
//             });

//             if (response.ok) {
//                 this.showAlert('File deleted successfully', 'success');
//                 this.loadFiles(); // Refresh the file list
//             } else {
//                 const data = await response.json();
//                 this.showAlert('Error: ' + data.error, 'danger');
//             }
//         } catch (error) {
//             this.showAlert('Error deleting file: ' + error.message, 'danger');
//         }
//     }

//     openDownloadsFolder() {
//         window.open('/downloads/', '_blank');
//     }

//     openFile(filename) {
//         // Create a temporary link to trigger automatic download/open
//         const link = document.createElement('a');
//         link.href = `/downloads/${encodeURIComponent(filename)}`;
//         link.download = filename; // Fallback for browsers that don't support inline opening
//         document.body.appendChild(link);
//         link.click();
//         document.body.removeChild(link);
//     }

//     downloadFile(filename) {
//         const link = document.createElement('a');
//         link.href = `/downloads/${encodeURIComponent(filename)}`;
//         link.download = filename;
//         document.body.appendChild(link);
//         link.click();
//         document.body.removeChild(link);
//     }

//     startUpdateInterval() {
//         this.updateInterval = setInterval(() => {
//             this.updateDownloadStatuses();
//         }, 1000);
//     }

//     showAlert(message, type) {
//         // Remove existing alerts
//         const existingAlerts = document.querySelectorAll('.alert');
//         existingAlerts.forEach(alert => {
//             if (alert.parentNode) {
//                 alert.remove();
//             }
//         });

//         // Create new alert
//         const alert = document.createElement('div');
//         alert.className = `alert alert-${type}`;

//         let icon = 'info-circle';
//         if (type === 'success') icon = 'check-circle';
//         if (type === 'danger') icon = 'exclamation-circle';
//         if (type === 'warning') icon = 'exclamation-triangle';

//         alert.innerHTML = `
//             <i class="fas fa-${icon}"></i>
//             <span>${message}</span>
//         `;

//         // Add close button
//         const closeBtn = document.createElement('button');
//         closeBtn.type = 'button';
//         closeBtn.className = 'btn-close';
//         closeBtn.innerHTML = '×';
//         closeBtn.onclick = () => {
//             if (alert.parentNode) {
//                 alert.remove();
//             }
//         };
//         alert.appendChild(closeBtn);

//         // Find the current active page and insert alert there
//         const activePage = document.querySelector('.page-section.active');
//         if (activePage) {
//             const pageHeader = activePage.querySelector('.page-header');
//             if (pageHeader && pageHeader.nextSibling) {
//                 activePage.insertBefore(alert, pageHeader.nextSibling);
//             } else {
//                 activePage.appendChild(alert);
//             }
//         } else {
//             // Fallback: insert at top of main content
//             const mainContent = document.querySelector('.main-content');
//             if (mainContent) {
//                 mainContent.insertBefore(alert, mainContent.firstChild);
//             }
//         }

//         // Auto-remove after 5 seconds
//         setTimeout(() => {
//             if (alert.parentNode) {
//                 alert.remove();
//             }
//         }, 5000);
//     }

//     getFilenameFromUrl(url) {
//         try {
//             const urlObj = new URL(url);
//             const pathname = urlObj.pathname;
//             const filename = pathname.substring(pathname.lastIndexOf('/') + 1);
//             return filename || url;
//         } catch (e) {
//             return url;
//         }
//     }
// }

// document.addEventListener('DOMContentLoaded', () => {
//     new DownloadManager();
// });
// static/app.js - Professional Download Manager with SMOOTH ANIMATIONS
class DownloadManager {
    constructor() {
        this.activeDownloads = new Map();
        this.updateInterval = null;
        this.currentPage = 'downloads';
        this.animationFrameId = null;
        this.init();
    }

    init() {
        // Form submission
        document.getElementById('downloadForm').addEventListener('submit', (e) => {
            e.preventDefault();
            this.startDownload();
        });

        // Mode change handler
        document.querySelectorAll('input[name="mode"]').forEach(radio => {
            radio.addEventListener('change', () => {
                this.toggleStreamsControl();
            });
        });

        // Close metrics handler
        document.getElementById('closeMetrics').addEventListener('click', () => {
            document.getElementById('metricsCard').classList.add('d-none');
        });

        // File Manager handlers
        document.getElementById('refreshFiles').addEventListener('click', () => {
            this.loadFiles();
        });

        document.getElementById('openDownloadsFolder').addEventListener('click', () => {
            this.openDownloadsFolder();
        });

        // Navigation handlers
        document.querySelectorAll('.nav-link').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const page = e.target.closest('.nav-link').dataset.page;
                this.switchPage(page);
            });
        });

        this.toggleStreamsControl();
        this.startUpdateInterval();
        this.loadFiles();
    }

    switchPage(page) {
        // Update navigation
        document.querySelectorAll('.nav-link').forEach(link => {
            link.classList.remove('active');
        });
        document.querySelector(`[data-page="${page}"]`).classList.add('active');

        // Update page content
        document.querySelectorAll('.page-section').forEach(section => {
            section.classList.remove('active');
        });
        document.getElementById(`${page}-page`).classList.add('active');

        this.currentPage = page;

        // Load files if switching to file manager
        if (page === 'files') {
            this.loadFiles();
        }
    }

    toggleStreamsControl() {
        const mode = document.querySelector('input[name="mode"]:checked').value;
        const streamsInput = document.getElementById('numStreams');
        streamsInput.disabled = mode === 'single';
    }

    async startDownload() {
        const url = document.getElementById('url').value;
        const mode = document.querySelector('input[name="mode"]:checked').value;
        const numStreams = document.getElementById('numStreams').value;

        if (!url) {
            this.showAlert('Please enter a URL', 'danger');
            return;
        }

        if (!url.startsWith('http://') && !url.startsWith('https://')) {
            this.showAlert('URL must start with http:// or https://', 'danger');
            return;
        }

        try {
            const response = await fetch('/api/downloads', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    url: url,
                    mode: mode,
                    num_streams: parseInt(numStreams)
                })
            });

            const data = await response.json();

            if (response.ok) {
                this.addDownloadItem(data.download_id, url, mode);
                document.getElementById('url').value = '';
                this.showAlert('Download started successfully', 'success');
            } else {
                this.showAlert('Error: ' + data.error, 'danger');
            }
        } catch (error) {
            this.showAlert('Error starting download: ' + error.message, 'danger');
        }
    }

    addDownloadItem(downloadId, url, mode) {
        // Hide "no active downloads" message
        const noActiveDownloads = document.getElementById('noActiveDownloads');
        if (noActiveDownloads) {
            noActiveDownloads.style.display = 'none';
        }

        const template = document.getElementById('downloadItemTemplate');
        const clone = template.content.cloneNode(true);

        const downloadItem = clone.querySelector('.download-item');
        downloadItem.id = `download-${downloadId}`;
        downloadItem.dataset.downloadId = downloadId;
        downloadItem.classList.add('downloading');

        const urlElement = clone.querySelector('.url-text');
        urlElement.textContent = this.getFilenameFromUrl(url);
        urlElement.title = url;

        const modeElement = clone.querySelector('.mode-text');
        modeElement.textContent = `${mode === 'multi' ? 'Multi-Stream' : 'Single-Stream'} Download`;

        const statusLine = clone.querySelector('.status-line');
        statusLine.classList.add('downloading');

        const progressBar = clone.querySelector('.progress-bar');
        progressBar.classList.add('downloading');
        progressBar.style.width = '0%'; // Start at 0%

        // Add event listeners
        clone.querySelector('.cancel-download').addEventListener('click', () => {
            this.cancelDownload(downloadId);
        });

        clone.querySelector('.view-metrics').addEventListener('click', () => {
            this.viewMetrics(downloadId);
        });

        document.getElementById('activeDownloads').appendChild(clone);
        this.activeDownloads.set(downloadId, {
            url: url,
            mode: mode,
            element: downloadItem,
            status: 'downloading',
            lastUpdate: Date.now(),
            lastBytes: 0,
            speedHistory: [],
            animation: {
                currentProgress: 0,
                targetProgress: 0,
                startTime: null,
                duration: 1000, // 1 second animation
                running: false
            }
        });

        this.updateActiveCount();
    }

    updateActiveCount() {
        const count = this.activeDownloads.size;
        document.getElementById('activeCount').textContent = count;
    }

    async cancelDownload(downloadId) {
        try {
            const response = await fetch(`/api/downloads/${downloadId}/cancel`, {
                method: 'POST'
            });

            if (response.ok) {
                this.showAlert('Download cancelled', 'warning');
            } else {
                const data = await response.json();
                this.showAlert('Error: ' + data.error, 'danger');
            }
        } catch (error) {
            this.showAlert('Error cancelling download: ' + error.message, 'danger');
        }
    }

    async viewMetrics(downloadId) {
        try {
            const response = await fetch(`/api/downloads/${downloadId}/metrics`);
            if (response.ok) {
                const metrics = await response.json();
                this.displayMetrics(metrics, downloadId);
            } else {
                this.showAlert('Metrics not available yet', 'warning');
            }
        } catch (error) {
            this.showAlert('Error fetching metrics: ' + error.message, 'danger');
        }
    }

    displayMetrics(metrics, downloadId) {
        const metricsCard = document.getElementById('metricsCard');
        const metricsDisplay = document.getElementById('metricsDisplay');

        let metricsText = '═'.repeat(80) + '\n';
        metricsText += '<strong>DOWNLOAD PERFORMANCE METRICS</strong>\n';
        metricsText += '═'.repeat(80) + '\n\n';

        if (metrics.num_streams_used !== undefined) {
            metricsText += '<strong>OVERVIEW</strong>\n';
            metricsText += '─'.repeat(80) + '\n';
            metricsText += `Total Time : ${metrics.total_time_seconds?.toFixed(2) || 'N/A'} seconds\n`;
            metricsText += `File Size : ${metrics.total_size_mb?.toFixed(2) || 'N/A'} MB\n`;
            metricsText += `Streams Used : ${metrics.num_streams_used || 'N/A'}\n`;
            metricsText += `Overall Throughput : ${metrics.throughput_mbps?.toFixed(2) || 'N/A'} Mbps (${metrics.throughput_MBps?.toFixed(2) || 'N/A'} MB/s)\n`;
            metricsText += `Avg Speed/Stream : ${metrics.average_speed_per_stream?.toFixed(2) || 'N/A'} MB/s\n\n`;

            if (metrics.chunk_metrics && metrics.chunk_metrics.length > 0) {
                metricsText += '<strong>STREAM BREAKDOWN</strong>\n';
                metricsText += '─'.repeat(80) + '\n';
                metricsText += `${'Stream'.padEnd(10)} ${'Size (MB)'.padEnd(15)} ${'Time (s)'.padEnd(15)} ${'Speed (MB/s)'.padEnd(15)}\n`;
                metricsText += '─'.repeat(80) + '\n';

                metrics.chunk_metrics.forEach(chunk => {
                    const streamNum = `#${chunk.chunk_id}`;
                    const size = chunk.size_mb?.toFixed(2) || 'N/A';
                    const time = chunk.time_seconds?.toFixed(2) || 'N/A';
                    const speed = chunk.speed_mbps?.toFixed(2) || 'N/A';
                    metricsText += `${streamNum.padEnd(10)} ${size.padEnd(15)} ${time.padEnd(15)} ${speed.padEnd(15)}\n`;
                });

                if (metrics.fastest_chunk && metrics.slowest_chunk) {
                    metricsText += '\n<strong>STATISTICS</strong>\n';
                    metricsText += '─'.repeat(80) + '\n';
                    metricsText += `Fastest Stream : #${metrics.fastest_chunk.chunk_id} at ${metrics.fastest_chunk.speed_mbps?.toFixed(2) || 'N/A'} MB/s\n`;
                    metricsText += `Slowest Stream : #${metrics.slowest_chunk.chunk_id} at ${metrics.slowest_chunk.speed_mbps?.toFixed(2) || 'N/A'} MB/s\n`;
                }
            }
        } else {
            metricsText += '<strong>OVERVIEW</strong>\n';
            metricsText += '─'.repeat(80) + '\n';
            metricsText += `Total Time : ${metrics.total_time?.toFixed(2) || 'N/A'} seconds\n`;
            metricsText += `File Size : ${metrics.file_size_mb?.toFixed(2) || 'N/A'} MB\n`;
            metricsText += `Download Mode : Single-Stream\n`;
            metricsText += `Overall Throughput : ${metrics.throughput_mbps?.toFixed(2) || 'N/A'} Mbps (${metrics.throughput_MBps?.toFixed(2) || 'N/A'} MB/s)\n`;
        }

        metricsText += '\n' + '═'.repeat(80);

        metricsDisplay.innerHTML = metricsText;
        metricsCard.classList.remove('d-none');
        metricsCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    async updateDownloadStatuses() {
        if (this.activeDownloads.size === 0) return;

        for (const [downloadId, info] of this.activeDownloads) {
            try {
                const response = await fetch(`/api/downloads/${downloadId}`);
                if (response.ok) {
                    const status = await response.json();
                    this.updateDownloadUI(downloadId, status);

                    if (['completed', 'failed', 'cancelled'].includes(status.status) && info.status === 'downloading') {
                        info.status = status.status;
                        setTimeout(() => {
                            this.moveToHistory(downloadId, status);
                        }, 3000);
                    }
                }
            } catch (error) {
                console.error('Error updating download status:', error);
            }
        }
    }

    // 🆕 SMOOTH ANIMATION VERSION
    updateDownloadUI(downloadId, status) {
        const info = this.activeDownloads.get(downloadId);
        if (!info) return;

        const progressBar = info.element.querySelector('.progress-bar');
        const speedText = info.element.querySelector('.speed-text');
        const statusElement = info.element.querySelector('.status-text');
        const statusLine = info.element.querySelector('.status-line');
        const progressPercent = info.element.querySelector('.progress-percent');

        const targetProgress = Math.round(status.progress || 0);
        
        // Update animation target
        info.animation.targetProgress = targetProgress;
        
        // Start animation if not running
        if (!info.animation.running) {
            info.animation.running = true;
            this.animateProgressBar(info, progressBar, progressPercent);
        }

        // Update speed and status immediately (no animation needed)
        this.updateSpeedText(info, status, speedText);
        this.updateStatus(info, status, statusElement, statusLine, progressBar);
    }

    // 🆕 SMOOTH ANIMATION ENGINE
    animateProgressBar(info, progressBar, progressPercent) {
        const now = performance.now();
        
        if (!info.animation.startTime) {
            info.animation.startTime = now;
        }
        
        const elapsed = now - info.animation.startTime;
        const progress = Math.min(elapsed / info.animation.duration, 1);
        
        // Smooth easing function
        const easeOutQuart = (t) => 1 - Math.pow(1 - t, 4);
        const easedProgress = easeOutQuart(progress);
        
        // Calculate current animated progress
        const currentAnimatedProgress = info.animation.currentProgress + 
            (info.animation.targetProgress - info.animation.currentProgress) * easedProgress;
        
        // Update progress bar and text
        progressBar.style.width = `${currentAnimatedProgress}%`;
        progressPercent.textContent = `${Math.round(currentAnimatedProgress)}%`;
        
        if (progress < 1) {
            // Continue animation
            requestAnimationFrame(() => this.animateProgressBar(info, progressBar, progressPercent));
        } else {
            // Animation complete
            info.animation.currentProgress = info.animation.targetProgress;
            info.animation.startTime = null;
            info.animation.running = false;
            
            // If target changed during animation, restart
            if (Math.round(info.animation.currentProgress) !== info.animation.targetProgress) {
                info.animation.startTime = performance.now();
                requestAnimationFrame(() => this.animateProgressBar(info, progressBar, progressPercent));
            }
        }
    }

    updateSpeedText(info, status, speedText) {
        if (!info.speedHistory) info.speedHistory = [];

        const now = Date.now();
        const timeDiff = (now - info.lastUpdate) / 1000;
        const bytesDiff = status.downloaded_size - info.lastBytes;
        const frontendSpeed = timeDiff > 0 ? (bytesDiff / (1024 * 1024)) / timeDiff : status.speed || 0;

        const currentSpeed = status.speed > 0 ? status.speed : frontendSpeed;

        info.speedHistory.push(currentSpeed);
        if (info.speedHistory.length > 5) info.speedHistory.shift();

        const avgSpeed = info.speedHistory.reduce((sum, val) => sum + val, 0) / info.speedHistory.length;

        if (status.total_size && status.downloaded_size !== undefined) {
            const downloadedMB = (status.downloaded_size / (1024 * 1024)).toFixed(2);
            const totalMB = (status.total_size / (1024 * 1024)).toFixed(2);
            speedText.textContent = status.status === 'downloading' && avgSpeed > 0
                ? `${avgSpeed.toFixed(2)} MB/s • ${downloadedMB}/${totalMB} MB`
                : `${downloadedMB} MB / ${totalMB} MB`;
        } else {
            speedText.textContent = 'Calculating...';
        }

        info.lastUpdate = now;
        info.lastBytes = status.downloaded_size || 0;
    }

    updateStatus(info, status, statusElement, statusLine, progressBar) {
        let statusClass = 'downloading';
        let statusText = 'Downloading...';
        let iconHtml = '<i class="fas fa-spinner fa-spin"></i>';

        switch (status.status) {
            case 'completed':
                statusClass = 'completed';
                statusText = 'Download completed';
                iconHtml = '<i class="fas fa-check-circle"></i>';
                // Refresh file manager when download completes
                if (this.currentPage === 'files') {
                    this.loadFiles();
                }
                break;
            case 'failed':
                statusClass = 'failed';
                statusText = `Failed: ${status.error || 'Unknown error'}`;
                iconHtml = '<i class="fas fa-exclamation-circle"></i>';
                break;
            case 'cancelled':
                statusClass = 'cancelled';
                statusText = 'Download cancelled';
                iconHtml = '<i class="fas fa-times-circle"></i>';
                break;
        }

        statusElement.textContent = statusText;
        statusLine.className = `status-line ${statusClass}`;
        statusLine.querySelector('i').outerHTML = iconHtml;

        progressBar.className = `progress-bar ${statusClass}`;
        info.element.className = `download-item ${statusClass}`;
    }

    moveToHistory(downloadId, status) {
        const info = this.activeDownloads.get(downloadId);
        if (!info) return;

        info.element.remove();
        this.activeDownloads.delete(downloadId);

        this.updateActiveCount();

        if (this.activeDownloads.size === 0) {
            const noActiveDownloads = document.getElementById('noActiveDownloads');
            if (noActiveDownloads) {
                noActiveDownloads.style.display = 'block';
            }
        }

        this.addToHistory(downloadId, info.url, info.mode, status);
    }

    addToHistory(downloadId, url, mode, status) {
        const historyContainer = document.getElementById('downloadHistory');
        const currentContent = historyContainer.innerHTML;

        if (currentContent.includes('No download history yet')) {
            historyContainer.innerHTML = '';
        }

        const template = document.getElementById('downloadItemTemplate');
        const clone = template.content.cloneNode(true);

        const historyItem = clone.querySelector('.download-item');
        historyItem.className = `download-item ${status.status}`;
        historyItem.id = `history-${downloadId}`;

        const urlElement = clone.querySelector('.url-text');
        urlElement.textContent = this.getFilenameFromUrl(url);
        urlElement.title = url;

        const modeElement = clone.querySelector('.mode-text');
        const statusCapitalized = status.status.charAt(0).toUpperCase() + status.status.slice(1);
        modeElement.textContent = `${mode === 'multi' ? 'Multi-Stream' : 'Single-Stream'} • ${statusCapitalized}`;

        const statusElement = clone.querySelector('.status-text');
        let statusText = statusCapitalized;
        if (status.status === 'failed' && status.error) {
            statusText = `Failed: ${status.error}`;
        }
        statusElement.textContent = statusText;

        const statusLine = clone.querySelector('.status-line');
        statusLine.className = `status-line ${status.status}`;

        const icon = statusLine.querySelector('i');
        if (status.status === 'completed') {
            icon.className = 'fas fa-check-circle';
        } else if (status.status === 'failed') {
            icon.className = 'fas fa-exclamation-circle';
        } else {
            icon.className = 'fas fa-times-circle';
        }

        const progressBar = clone.querySelector('.progress-bar');
        progressBar.style.width = '100%';
        progressBar.className = `progress-bar ${status.status}`;

        const progressPercent = clone.querySelector('.progress-percent');
        progressPercent.textContent = '100%';

        const speedText = clone.querySelector('.speed-text');
        if (status.total_size) {
            const totalMB = (status.total_size / (1024 * 1024)).toFixed(2);
            speedText.textContent = `${totalMB} MB`;
        } else if (status.metrics && status.metrics.total_time_seconds) {
            speedText.textContent = `${status.metrics.total_time_seconds.toFixed(2)}s`;
        } else if (status.metrics && status.metrics.total_time) {
            speedText.textContent = `${status.metrics.total_time.toFixed(2)}s`;
        } else {
            speedText.textContent = 'Completed';
        }

        const cancelBtn = clone.querySelector('.cancel-download');
        cancelBtn.remove();

        const metricsBtn = clone.querySelector('.view-metrics');
        metricsBtn.addEventListener('click', () => {
            this.viewMetrics(downloadId);
        });

        if (status.status === 'completed' && status.filename) {
            const openBtn = document.createElement('button');
            openBtn.className = 'action-btn success';
            openBtn.innerHTML = '<i class="fas fa-folder-open"></i>';
            openBtn.title = 'Open File';
            openBtn.onclick = () => {
                this.openFile(status.filename);
            };
            metricsBtn.parentNode.appendChild(openBtn);
        }

        historyContainer.appendChild(clone);
    }

    // File Manager Methods
    async loadFiles() {
        try {
            const response = await fetch('/api/files');
            if (response.ok) {
                const files = await response.json();
                console.log('Loaded files:', files);
                this.displayFiles(files);
            } else {
                this.showAlert('Error loading files', 'danger');
            }
        } catch (error) {
            console.error('Error loading files:', error);
            this.showAlert('Error loading files: ' + error.message, 'danger');
        }
    }

    displayFiles(files) {
        const fileManager = document.getElementById('fileManager');
        const fileCount = document.getElementById('fileCount');
        
        fileCount.textContent = files.length;

        if (files.length === 0) {
            fileManager.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-folder-open"></i>
                    <p>No files downloaded yet</p>
                    <small class="text-muted">Downloaded files will appear here</small>
                </div>
            `;
            return;
        }

        fileManager.innerHTML = '';
        const template = document.getElementById('fileItemTemplate');

        files.forEach(file => {
            const clone = template.content.cloneNode(true);
            const fileItem = clone.querySelector('.file-item');
            
            // Set file name
            const fileName = clone.querySelector('.file-name');
            fileName.textContent = file.name;
            fileName.title = file.name;
            
            // Set file size
            const fileSize = clone.querySelector('.file-size');
            fileSize.textContent = this.formatFileSize(file.size);
            
            // Set file date
            const fileDate = clone.querySelector('.file-date');
            console.log('File timestamp:', file.name, file.modified, typeof file.modified);
            fileDate.textContent = this.formatFileDate(file.modified);
            
            // Set file type icon
            const fileIcon = clone.querySelector('.file-icon i');
            const fileType = this.getFileType(file.name);
            fileIcon.className = this.getFileIcon(fileType);
            fileItem.classList.add(`file-${fileType}`);
            
            // Add event listeners
            clone.querySelector('.open-file').addEventListener('click', () => {
                this.openFile(file.name);
            });
            
            clone.querySelector('.download-file').addEventListener('click', () => {
                this.downloadFile(file.name);
            });
            
            clone.querySelector('.delete-file').addEventListener('click', () => {
                this.deleteFile(file.name);
            });

            fileManager.appendChild(clone);
        });
    }

    getFileType(filename) {
        const extension = filename.split('.').pop().toLowerCase();
        const imageTypes = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg'];
        const videoTypes = ['mp4', 'avi', 'mov', 'wmv', 'flv', 'webm', 'mkv'];
        const audioTypes = ['mp3', 'wav', 'ogg', 'flac', 'aac', 'wma'];
        const documentTypes = ['pdf', 'doc', 'docx', 'txt', 'rtf'];
        const archiveTypes = ['zip', 'rar', '7z', 'tar', 'gz'];
        const executableTypes = ['exe', 'msi', 'dmg', 'pkg', 'deb', 'rpm'];

        if (imageTypes.includes(extension)) return 'image';
        if (videoTypes.includes(extension)) return 'video';
        if (audioTypes.includes(extension)) return 'audio';
        if (documentTypes.includes(extension)) return 'document';
        if (archiveTypes.includes(extension)) return 'zip';
        if (executableTypes.includes(extension)) return 'executable';
        return 'file';
    }

    getFileIcon(fileType) {
        const icons = {
            'image': 'fas fa-file-image',
            'video': 'fas fa-file-video',
            'audio': 'fas fa-file-audio',
            'document': 'fas fa-file-pdf',
            'zip': 'fas fa-file-archive',
            'executable': 'fas fa-cog',
            'file': 'fas fa-file'
        };
        return icons[fileType] || icons.file;
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    formatFileDate(timestamp) {
        try {
            let date;
            
            if (timestamp > 10000000000) {
                date = new Date(timestamp);
            } else {
                date = new Date(timestamp * 1000);
            }
            
            if (isNaN(date.getTime())) {
                console.warn('Invalid timestamp:', timestamp);
                return 'Invalid date';
            }
            
            const year = date.getFullYear();
            const month = String(date.getMonth() + 1).padStart(2, '0');
            const day = String(date.getDate()).padStart(2, '0');
            const hours = String(date.getHours()).padStart(2, '0');
            const minutes = String(date.getMinutes()).padStart(2, '0');
            const seconds = String(date.getSeconds()).padStart(2, '0');
            
            return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
        } catch (error) {
            console.error('Error formatting date:', error);
            return 'Date error';
        }
    }

    async deleteFile(filename) {
        if (!confirm(`Are you sure you want to delete "${filename}"?`)) {
            return;
        }

        try {
            const encodedFilename = encodeURIComponent(filename);
            const response = await fetch(`/api/files/${encodedFilename}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                this.showAlert('File deleted successfully', 'success');
                this.loadFiles();
            } else {
                const data = await response.json();
                this.showAlert('Error: ' + data.error, 'danger');
            }
        } catch (error) {
            this.showAlert('Error deleting file: ' + error.message, 'danger');
        }
    }

    openDownloadsFolder() {
        window.open('/downloads/', '_blank');
    }

    openFile(filename) {
        const link = document.createElement('a');
        link.href = `/downloads/${encodeURIComponent(filename)}`;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    downloadFile(filename) {
        const link = document.createElement('a');
        link.href = `/downloads/${encodeURIComponent(filename)}`;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    startUpdateInterval() {
        this.updateInterval = setInterval(() => {
            this.updateDownloadStatuses();
        }, 1000);
    }

    showAlert(message, type) {
        const existingAlerts = document.querySelectorAll('.alert');
        existingAlerts.forEach(alert => {
            if (alert.parentNode) {
                alert.remove();
            }
        });

        const alert = document.createElement('div');
        alert.className = `alert alert-${type}`;

        let icon = 'info-circle';
        if (type === 'success') icon = 'check-circle';
        if (type === 'danger') icon = 'exclamation-circle';
        if (type === 'warning') icon = 'exclamation-triangle';

        alert.innerHTML = `
            <i class="fas fa-${icon}"></i>
            <span>${message}</span>
        `;

        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'btn-close';
        closeBtn.innerHTML = '×';
        closeBtn.onclick = () => {
            if (alert.parentNode) {
                alert.remove();
            }
        };
        alert.appendChild(closeBtn);

        const activePage = document.querySelector('.page-section.active');
        if (activePage) {
            const pageHeader = activePage.querySelector('.page-header');
            if (pageHeader && pageHeader.nextSibling) {
                activePage.insertBefore(alert, pageHeader.nextSibling);
            } else {
                activePage.appendChild(alert);
            }
        } else {
            const mainContent = document.querySelector('.main-content');
            if (mainContent) {
                mainContent.insertBefore(alert, mainContent.firstChild);
            }
        }

        setTimeout(() => {
            if (alert.parentNode) {
                alert.remove();
            }
        }, 5000);
    }

    getFilenameFromUrl(url) {
        try {
            const urlObj = new URL(url);
            const pathname = urlObj.pathname;
            const filename = pathname.substring(pathname.lastIndexOf('/') + 1);
            return filename || url;
        } catch (e) {
            return url;
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new DownloadManager();
});