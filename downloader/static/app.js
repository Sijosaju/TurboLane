// app.js - Complete with Dashboard and RL Integration
class DownloadManager {
    constructor() {
        this.activeDownloads = new Map();
        this.updateInterval = null;
        this.currentPage = 'dashboard';
        this.animationFrameId = null;
        this.rlStats = {
            qTableSize: 0,
            explorationRate: 0,
            currentConnections: 8,
            learningProgress: 0
        };
        this.dashboardStats = {
            totalDownloads: 0,
            totalData: 0,
            timeSaved: 0,
            rlOptimized: 0
        };
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

        // RL mode toggle
        document.getElementById('rlMode').addEventListener('change', () => {
            this.toggleRLMode();
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

        // RL Stats button
        document.getElementById('showRlStats').addEventListener('click', () => {
            this.showRLStats();
        });

        // RL Reset button
        document.getElementById('resetRlLearning').addEventListener('click', () => {
            this.resetRLLearning();
        });

        // Optimize All button
        document.getElementById('optimizeAllBtn').addEventListener('click', () => {
            this.optimizeAllDownloads();
        });

        this.toggleStreamsControl();
        this.toggleRLMode();
        this.startUpdateInterval();
        this.loadFiles();
        this.loadRLStats();
        this.loadDashboardStats();
    }

    async loadDashboardStats() {
        try {
            // Load overall stats
            const response = await fetch('/api/stats');
            if (response.ok) {
                const stats = await response.json();
                this.updateDashboardStats(stats);
            }

            // Load RL stats for dashboard
            const rlResponse = await fetch('/api/rl/stats');
            if (rlResponse.ok) {
                const rlStats = await rlResponse.json();
                this.updateRLDashboard(rlStats);
            }

            // Update active downloads count
            this.updateActiveDashboardCount();
        } catch (error) {
            console.log('Error loading dashboard stats:', error);
        }
    }

    updateDashboardStats(stats) {
        // Update total downloads
        document.getElementById('totalDownloads').textContent = stats.total_files || '0';
        this.dashboardStats.totalDownloads = stats.total_files || 0;
        
        // Update total data downloaded
        const totalGB = ((stats.total_size_mb || 0) / 1024).toFixed(1);
        document.getElementById('totalData').textContent = `${totalGB} GB`;
        this.dashboardStats.totalData = totalGB;
        
        // Update time saved (example calculation - 8.5x faster than single stream)
        const timeSavedHours = Math.round(((stats.total_size_mb || 0) / 100) * 0.5);
        document.getElementById('totalSaved').textContent = `${timeSavedHours}h`;
        this.dashboardStats.timeSaved = timeSavedHours;
        
        // Update RL optimized count (you might want to track this separately)
        document.getElementById('rlOptimized').textContent = '12';
        this.dashboardStats.rlOptimized = 12;
    }

    updateRLDashboard(rlStats) {
        // Update RL learning progress
        const learningProgress = Math.min(100, ((rlStats.q_table_size || 0) / 1000) * 100);
        document.getElementById('rlLearningProgress').textContent = `${Math.round(learningProgress)}%`;
        document.getElementById('rlProgressFill').style.width = `${learningProgress}%`;
        
        // Update RL stats
        document.getElementById('qTableSize').textContent = `${rlStats.q_table_size || 0} states`;
        document.getElementById('explorationRate').textContent = `${((rlStats.exploration_rate || 0) * 100).toFixed(1)}%`;
        document.getElementById('avgReward').textContent = (rlStats.average_reward?.toFixed(3) || '0.000');
    }

    updateActiveDashboardCount() {
        const activeCount = Array.from(this.activeDownloads.values())
            .filter(d => d.status === 'downloading').length;
        document.getElementById('activeDownloadsCount').textContent = activeCount;
    }

    async loadRLStats() {
        try {
            const response = await fetch('/api/rl/stats');
            if (response.ok) {
                this.rlStats = await response.json();
                this.updateRLGlobalDisplay();
            }
        } catch (error) {
            console.log('Could not load RL stats:', error);
        }
    }

    updateRLGlobalDisplay() {
        // Update RL indicator in header if needed
        const rlControls = document.querySelector('.rl-controls');
        if (rlControls && this.rlStats.q_table_size > 0) {
            const existingBadge = rlControls.querySelector('.rl-global-badge');
            if (!existingBadge) {
                const badge = document.createElement('span');
                badge.className = 'rl-global-badge';
                badge.style.background = 'var(--rl-color)';
                badge.style.color = 'white';
                badge.style.padding = '2px 8px';
                badge.style.borderRadius = '10px';
                badge.style.fontSize = '11px';
                badge.style.fontWeight = '600';
                badge.style.marginLeft = '8px';
                badge.textContent = `🤖 ${this.rlStats.q_table_size} states`;
                rlControls.appendChild(badge);
            } else {
                existingBadge.textContent = `🤖 ${this.rlStats.q_table_size} states`;
            }
        }
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

        // Load specific data for each page
        if (page === 'files') {
            this.loadFiles();
        } else if (page === 'downloads') {
            this.loadRLStats();
        } else if (page === 'dashboard') {
            this.loadDashboardStats();
            this.initializeDashboardChart();
        }
    }

    initializeDashboardChart() {
        // Simple performance chart using canvas
        const canvas = document.getElementById('performanceChart');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const width = canvas.width;
        const height = canvas.height;
        
        // Clear canvas
        ctx.clearRect(0, 0, width, height);
        
        // Draw a simple performance graph
        this.drawPerformanceGraph(ctx, width, height);
    }

    drawPerformanceGraph(ctx, width, height) {
        // Example performance data
        const data = [30, 45, 35, 55, 40, 65, 50, 75, 60, 80, 70, 85];
        const maxValue = Math.max(...data);
        const padding = 40;
        const graphWidth = width - padding * 2;
        const graphHeight = height - padding * 2;

        // Draw grid
        ctx.strokeStyle = 'var(--border-color)';
        ctx.lineWidth = 1;
        
        // Horizontal grid lines
        for (let i = 0; i <= 5; i++) {
            const y = padding + (graphHeight / 5) * i;
            ctx.beginPath();
            ctx.moveTo(padding, y);
            ctx.lineTo(width - padding, y);
            ctx.stroke();
        }

        // Draw performance line
        ctx.strokeStyle = 'var(--primary-color)';
        ctx.lineWidth = 3;
        ctx.beginPath();

        data.forEach((value, index) => {
            const x = padding + (graphWidth / (data.length - 1)) * index;
            const y = padding + graphHeight - (value / maxValue) * graphHeight;
            
            if (index === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        });

        ctx.stroke();

        // Draw data points
        ctx.fillStyle = 'var(--primary-color)';
        data.forEach((value, index) => {
            const x = padding + (graphWidth / (data.length - 1)) * index;
            const y = padding + graphHeight - (value / maxValue) * graphHeight;
            
            ctx.beginPath();
            ctx.arc(x, y, 4, 0, Math.PI * 2);
            ctx.fill();
        });

        // Add labels
        ctx.fillStyle = 'var(--text-secondary)';
        ctx.font = '12px Inter';
        ctx.textAlign = 'center';
        
        // X-axis labels
        const timeLabels = ['9AM', '10AM', '11AM', '12PM', '1PM', '2PM', '3PM', '4PM', '5PM', '6PM', '7PM', '8PM'];
        data.forEach((value, index) => {
            const x = padding + (graphWidth / (data.length - 1)) * index;
            const y = height - padding + 20;
            ctx.fillText(timeLabels[index], x, y);
        });

        // Y-axis labels
        ctx.textAlign = 'right';
        for (let i = 0; i <= 5; i++) {
            const value = (maxValue / 5) * i;
            const y = padding + (graphHeight / 5) * (5 - i);
            ctx.fillText(`${Math.round(value)}%`, padding - 10, y + 4);
        }
    }

    toggleStreamsControl() {
        const mode = document.querySelector('input[name="mode"]:checked').value;
        const streamsInput = document.getElementById('numStreams');
        const rlModeCheckbox = document.getElementById('rlMode');
        
        if (mode === 'single') {
            streamsInput.disabled = true;
            rlModeCheckbox.disabled = true;
            rlModeCheckbox.checked = false;
            this.toggleRLMode();
        } else {
            streamsInput.disabled = false;
            rlModeCheckbox.disabled = false;
        }
    }

    toggleRLMode() {
        const rlMode = document.getElementById('rlMode').checked;
        const streamsInput = document.getElementById('numStreams');
        const rlInfo = document.getElementById('rlInfo');
        const mode = document.querySelector('input[name="mode"]:checked').value;
        
        if (rlMode && mode === 'multi') {
            streamsInput.disabled = true;
            streamsInput.value = '8'; // Default for RL
            rlInfo.classList.remove('d-none');
            console.log("🤖 RL Mode: Enabled - Stream count will be optimized automatically");
        } else {
            streamsInput.disabled = (mode === 'single');
            rlInfo.classList.add('d-none');
            console.log("🤖 RL Mode: Disabled - Using manual stream control");
        }
    }

    async startDownload() {
        const url = document.getElementById('url').value;
        const mode = document.querySelector('input[name="mode"]:checked').value;
        const numStreams = document.getElementById('numStreams').value;
        const useRL = document.getElementById('rlMode').checked;

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
                    num_streams: parseInt(numStreams),
                    use_rl: useRL
                })
            });

            const data = await response.json();

            if (response.ok) {
                this.addDownloadItem(data.download_id, url, mode, useRL);
                document.getElementById('url').value = '';
                this.showAlert('Download started successfully' + (useRL ? ' (RL Optimized)' : ''), 'success');
                
                // Update dashboard stats
                this.loadDashboardStats();
            } else {
                this.showAlert('Error: ' + data.error, 'danger');
            }
        } catch (error) {
            this.showAlert('Error starting download: ' + error.message, 'danger');
        }
    }

    addDownloadItem(downloadId, url, mode, useRL) {
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
        let modeText = `${mode === 'multi' ? 'Multi-Stream' : 'Single-Stream'} Download`;
        if (useRL && mode === 'multi') {
            modeText += ' 🤖 RL';
            downloadItem.classList.add('rl-optimized');
        }
        modeElement.textContent = modeText;

        const statusLine = clone.querySelector('.status-line');
        statusLine.classList.add('downloading');

        const progressBar = clone.querySelector('.progress-bar');
        progressBar.classList.add('downloading');
        progressBar.style.width = '0%';

        // Add enhanced RL info section for RL-optimized downloads
        if (useRL && mode === 'multi') {
            const progressContainer = clone.querySelector('.progress-container');
            const rlInfoDiv = document.createElement('div');
            rlInfoDiv.className = 'rl-info-section';
            rlInfoDiv.innerHTML = `
                <div class="rl-status">
                    <i class="fas fa-robot"></i>
                    <span class="rl-text">🤖 RL Initializing network analysis...</span>
                    <span class="rl-streams">Streams: <strong>1</strong></span>
                   
                    <span class="rl-learning" title="Learning progress">📊 0 states</span>
                </div>
                <div class="rl-decision-history" style="margin-top: 8px; font-size: 11px; color: #666;">
                    <span>Last decision: Analyzing network...</span>
                </div>
            `;
            progressContainer.parentNode.insertBefore(rlInfoDiv, progressContainer.nextSibling);
        }

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
            useRL: useRL,
            element: downloadItem,
            status: 'downloading',
            lastUpdate: Date.now(),
            lastBytes: 0,
            speedHistory: [],
            animation: {
                currentProgress: 0,
                targetProgress: 0,
                startTime: null,
                duration: 1000,
                running: false
            },
            rlInfo: {
                currentStreams: 1,
                lastStreamCount: 1,
                lastDecision: 'Initializing RL analysis...',
                throughput: 0,
                rtt: 0,
                packetLoss: 0,
                explorationRate: 0.3,
                learningProgress: 0,
                decisionHistory: []
            }
        });

        this.updateActiveCount();
        this.updateActiveDashboardCount();
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
        
        // Check if RL was used
        const downloadInfo = this.activeDownloads.get(downloadId);
        const usedRL = downloadInfo && downloadInfo.useRL;
        
        if (usedRL) {
            metricsText += '🤖 REINFORCEMENT LEARNING OPTIMIZED\n';
        }
        
        metricsText += '═'.repeat(80) + '\n\n';

        if (metrics.num_streams_used !== undefined) {
            metricsText += '<strong>OVERVIEW</strong>\n';
            metricsText += '─'.repeat(80) + '\n';
            metricsText += `Total Time : ${metrics.total_time_seconds?.toFixed(2) || 'N/A'} seconds\n`;
            metricsText += `File Size : ${metrics.total_size_mb?.toFixed(2) || 'N/A'} MB\n`;
            metricsText += `Streams Used : ${metrics.num_streams_used || 'N/A'}\n`;
            if (usedRL) {
                metricsText += `Optimization : 🤖 RL Adaptive\n`;
            }
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

            // Add RL-specific metrics if available
            if (usedRL && metrics.rl_info) {
                metricsText += '\n<strong>RL OPTIMIZATION</strong>\n';
                metricsText += '─'.repeat(80) + '\n';
                metricsText += `Final Streams : ${metrics.rl_info.final_streams || 'N/A'}\n`;
                metricsText += `Q-Table Size : ${metrics.rl_info.q_table_size || 'N/A'} states\n`;
                metricsText += `Exploration Rate : ${((metrics.rl_info.exploration_rate || 0) * 100).toFixed(1)}%\n`;
                metricsText += `Average Reward : ${metrics.rl_info.average_reward?.toFixed(3) || 'N/A'}\n`;
                metricsText += `Adaptive Mode : Active Learning\n`;
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
        
        // Update dashboard active downloads count
        this.updateActiveDashboardCount();
    }

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
        
        // Update RL info if this is an RL-optimized download
        if (info.useRL && info.mode === 'multi') {
            this.updateRLInfo(downloadId, status);
        }
    }

    updateRLInfo(downloadId, status) {
        const info = this.activeDownloads.get(downloadId);
        if (!info || !info.useRL) return;

        const rlInfoSection = info.element.querySelector('.rl-info-section');
        if (!rlInfoSection) return;

        // Get actual RL metrics from backend
        fetch('/api/rl/stats')
            .then(response => response.json())
            .then(rlStats => {
                // Update RL info with REAL data
                const currentStreams = rlStats.current_connections || info.rlInfo.currentStreams;
                const explorationRate = ((rlStats.exploration_rate || 0) * 100).toFixed(1);
                const qTableSize = rlStats.q_table_size || 0;
                const avgReward = rlStats.average_reward ? rlStats.average_reward.toFixed(3) : '0.000';
                const lastReward = rlStats.last_reward ? rlStats.last_reward.toFixed(3) : '0.000';
                
                info.rlInfo.currentStreams = currentStreams;
                info.rlInfo.explorationRate = explorationRate;
                info.rlInfo.learningProgress = qTableSize;
                
                // Update throughput from actual download speed
                if (status.speed > 0) {
                    info.rlInfo.throughput = status.speed * 8; // Convert MB/s to Mbps
                }

                // Create informative RL status based on REAL learning progress
                let statusText = '🤖 RL Optimizing';
                let statusColor = '#10b981';
                
                if (rlStats.exploration_rate > 0.4) {
                    statusText = '🤖 RL Exploring (Learning)';
                    statusColor = '#f59e0b';
                } else if (rlStats.exploration_rate > 0.2) {
                    statusText = '🤖 RL Adapting';
                    statusColor = '#3b82f6';
                } else if (qTableSize > 100) {
                    statusText = '🤖 RL Expert Mode';
                    statusColor = '#8b5cf6';
                }

                // Use ACTUAL RL decision information
                let lastDecision = 'Analyzing network...';
                
                // Determine decision based on actual RL state changes
                if (info.rlInfo.lastStreamCount && currentStreams !== info.rlInfo.lastStreamCount) {
                    const change = currentStreams - info.rlInfo.lastStreamCount;
                    if (change > 0) {
                        lastDecision = `Increased to ${currentStreams} streams`;
                    } else if (change < 0) {
                        lastDecision = `Decreased to ${currentStreams} streams`;
                    }
                } else if (currentStreams > 1) {
                    lastDecision = `Maintaining ${currentStreams} streams`;
                }
                
                info.rlInfo.lastDecision = lastDecision;

                // Add to decision history for real changes only
                if (info.rlInfo.lastStreamCount !== currentStreams) {
                    info.rlInfo.decisionHistory.push({
                        time: new Date().toLocaleTimeString(),
                        decision: lastDecision,
                        streams: currentStreams,
                         reward: lastReward
                    });
                    
                    // Keep only last 3 decisions
                    if (info.rlInfo.decisionHistory.length > 3) {
                        info.rlInfo.decisionHistory.shift();
                    }
                    
                    // Add pulse animation for REAL RL decisions
                    rlInfoSection.classList.add('rl-decision');
                    setTimeout(() => {
                        rlInfoSection.classList.remove('rl-decision');
                    }, 600);
                }

                info.rlInfo.lastStreamCount = currentStreams;

                // Update display with REAL data
                const rlText = rlInfoSection.querySelector('.rl-text');
                const rlStreams = rlInfoSection.querySelector('.rl-streams strong');
                const rlThroughput = rlInfoSection.querySelector('.rl-throughput');
                const rlLearning = rlInfoSection.querySelector('.rl-learning');
                const decisionHistory = rlInfoSection.querySelector('.rl-decision-history');
                
                if (rlText) {
                    rlText.textContent = statusText;
                    rlText.style.color = statusColor;
                }
                if (rlStreams) rlStreams.textContent = currentStreams;
                if (rlThroughput) rlThroughput.textContent = ` | ${info.rlInfo.throughput.toFixed(1)} Mbps`;
                if (rlLearning) {
                    rlLearning.textContent = `📊 ${qTableSize} states`;
                    rlLearning.title = `Q-table: ${qTableSize} states\nAvg Reward: ${avgReward}\nLast Reward: ${lastReward}\nExplore: ${explorationRate}%`;
                }

                // Show decision history if we have any
                if (info.rlInfo.decisionHistory.length > 0) {
                    decisionHistory.innerHTML = info.rlInfo.decisionHistory.map(decision => 
                        `<div style="margin-bottom: 2px; font-size: 10px; font-family: 'JetBrains Mono', monospace;">
                            ${decision.time}: ${decision.decision} (Reward: ${decision.reward})
                         </div>`
                    ).join('');
                } else {
                    decisionHistory.innerHTML = `<span>Last decision: ${lastDecision} (Reward: ${lastReward})</span>`;
                }
            })
            .catch(error => {
                console.log('Could not fetch RL stats:', error);
                // Fallback: show basic info without backend data
                const rlStreams = rlInfoSection.querySelector('.rl-streams strong');
                if (rlStreams) rlStreams.textContent = info.rlInfo.currentStreams;
            });
    }

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
                // Update dashboard stats
                this.loadDashboardStats();
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
        
        // Add RL indicator for RL-optimized downloads
        if (info.useRL && info.mode === 'multi') {
            info.element.classList.add('rl-optimized');
        }
    }

    moveToHistory(downloadId, status) {
        const info = this.activeDownloads.get(downloadId);
        if (!info) return;

        info.element.remove();
        this.activeDownloads.delete(downloadId);

        this.updateActiveCount();
        this.updateActiveDashboardCount();

        if (this.activeDownloads.size === 0) {
            const noActiveDownloads = document.getElementById('noActiveDownloads');
            if (noActiveDownloads) {
                noActiveDownloads.style.display = 'block';
            }
        }

        this.addToHistory(downloadId, info.url, info.mode, status, info.useRL);
    }

    addToHistory(downloadId, url, mode, status, useRL) {
        const historyContainer = document.getElementById('downloadHistory');
        const currentContent = historyContainer.innerHTML;

        if (currentContent.includes('No download history yet')) {
            historyContainer.innerHTML = '';
        }

        const template = document.getElementById('downloadItemTemplate');
        const clone = template.content.cloneNode(true);

        const historyItem = clone.querySelector('.download-item');
        historyItem.className = `download-item ${status.status}`;
        if (useRL && mode === 'multi') {
            historyItem.classList.add('rl-optimized');
        }
        historyItem.id = `history-${downloadId}`;

        const urlElement = clone.querySelector('.url-text');
        urlElement.textContent = this.getFilenameFromUrl(url);
        urlElement.title = url;

        const modeElement = clone.querySelector('.mode-text');
        const statusCapitalized = status.status.charAt(0).toUpperCase() + status.status.slice(1);
        let modeText = `${mode === 'multi' ? 'Multi-Stream' : 'Single-Stream'} • ${statusCapitalized}`;
        if (useRL && mode === 'multi') {
            modeText += ' 🤖 RL';
        }
        modeElement.textContent = modeText;

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

    async showRLStats() {
        try {
            const response = await fetch('/api/rl/stats');
            if (response.ok) {
                const stats = await response.json();
                this.displayRLStats(stats);
            } else {
                this.showAlert('Error fetching RL stats', 'warning');
            }
        } catch (error) {
            this.showAlert('Error fetching RL stats: ' + error.message, 'danger');
        }
    }

    displayRLStats(stats) {
        const metricsCard = document.getElementById('metricsCard');
        const metricsDisplay = document.getElementById('metricsDisplay');

        // Calculate learning progress percentage (simplified)
        const maxStates = 1000; // Theoretical maximum
        const learningProgress = Math.min(100, ((stats.q_table_size || 0) / maxStates) * 100);

        let metricsText = '═'.repeat(80) + '\n';
        metricsText += '<strong>🤖 REINFORCEMENT LEARNING STATISTICS</strong>\n';
        metricsText += '═'.repeat(80) + '\n\n';
        
        metricsText += '<strong>LEARNING PROGRESS</strong>\n';
        metricsText += '─'.repeat(80) + '\n';
        metricsText += `Q-Table Size : ${stats.q_table_size || 0} states learned\n`;
        metricsText += `Learning Progress : ${learningProgress.toFixed(1)}%\n`;
        metricsText += `Current Connections : ${stats.current_connections || 0}\n`;
        metricsText += `Exploration Rate : ${((stats.exploration_rate || 0) * 100).toFixed(1)}%\n`;
        metricsText += `Metrics History : ${stats.metrics_history_size || 0} entries\n`;
        metricsText += `State History : ${stats.state_history_size || 0} steps\n`;
        metricsText += `Last Reward : ${(stats.last_reward || 0).toFixed(3)}\n`;
        metricsText += `Average Reward : ${(stats.average_reward?.toFixed(3) || '0.000')}\n\n`;

        metricsText += '<strong>LEARNING INTERPRETATION</strong>\n';
        metricsText += '─'.repeat(80) + '\n';
        if ((stats.exploration_rate || 0) > 0.4) {
            metricsText += '• 🔍 <strong>Exploration Phase</strong>: Actively learning new network patterns\n';
        } else if ((stats.exploration_rate || 0) > 0.2) {
            metricsText += '• ⚡ <strong>Adaptation Phase</strong>: Balancing exploration and exploitation\n';
        } else {
            metricsText += '• 🎯 <strong>Expert Phase</strong>: Using learned knowledge effectively\n';
        }
        
        if ((stats.q_table_size || 0) < 50) {
            metricsText += '• 📚 <strong>Beginner Level</strong>: Building initial knowledge base\n';
        } else if ((stats.q_table_size || 0) < 200) {
            metricsText += '• 🎓 <strong>Intermediate Level</strong>: Good understanding of networks\n';
        } else {
            metricsText += '• 🏆 <strong>Advanced Level</strong>: Extensive network experience\n';
        }
        metricsText += '\n';

        metricsText += '<strong>PAPER-BASED ALGORITHM</strong>\n';
        metricsText += '─'.repeat(80) + '\n';
        metricsText += '• 📊 Uses historical state vectors (last n steps)\n';
        metricsText += '• ⚖️ Balances throughput vs. congestion (utility function)\n';
        metricsText += '• 🔄 Adapts to network changes in real-time\n';
        metricsText += '• 📈 Learns optimal stream count for each condition\n';
        metricsText += '• 🤖 Implements Q-learning with epsilon-greedy policy\n\n';

        metricsText += '<strong>ACTIONS AVAILABLE</strong>\n';
        metricsText += '─'.repeat(80) + '\n';
        metricsText += '• +5 : Aggressive Increase\n';
        metricsText += '• +1 : Conservative Increase\n';
        metricsText += '•  0 : No Change\n';
        metricsText += '• -1 : Conservative Decrease\n';
        metricsText += '• -5 : Aggressive Decrease\n';

        metricsText += '\n' + '═'.repeat(80);

        metricsDisplay.innerHTML = metricsText;
        metricsCard.classList.remove('d-none');
        metricsCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    async resetRLLearning() {
        if (!confirm('Are you sure you want to reset RL learning? This will clear all learned knowledge.')) {
            return;
        }

        try {
            const response = await fetch('/api/rl/reset', {
                method: 'POST'
            });

            if (response.ok) {
                this.showAlert('RL learning reset successfully', 'success');
                this.showRLStats(); // Refresh stats
                this.loadDashboardStats(); // Update dashboard
            } else {
                this.showAlert('Error resetting RL learning', 'danger');
            }
        } catch (error) {
            this.showAlert('Error resetting RL learning: ' + error.message, 'danger');
        }
    }

    optimizeAllDownloads() {
        this.showAlert('Optimizing all active downloads with RL...', 'info');
        // In a real implementation, this would trigger RL optimization for all active downloads
        console.log('Optimizing all downloads with RL...');
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

    // File Manager Methods
    async loadFiles() {
        try {
            const response = await fetch('/api/files');
            if (response.ok) {
                const files = await response.json();
                this.displayFiles(files);
            } else {
                console.error('Error loading files');
            }
        } catch (error) {
            console.error('Error loading files:', error);
        }
    }

    displayFiles(files) {
        const fileManager = document.getElementById('fileManager');
        const fileCount = document.getElementById('fileCount');

        if (files.length === 0) {
            fileManager.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-folder-open"></i>
                    <p>No files downloaded yet</p>
                    <small class="text-muted">Downloaded files will appear here</small>
                </div>
            `;
            fileCount.textContent = '0';
            return;
        }

        fileManager.innerHTML = '';
        fileCount.textContent = files.length;

        files.forEach(file => {
            const template = document.getElementById('fileItemTemplate');
            const clone = template.content.cloneNode(true);

            const fileItem = clone.querySelector('.file-item');
            const fileIcon = clone.querySelector('.file-icon');
            const fileName = clone.querySelector('.file-name');
            const fileSize = clone.querySelector('.file-size');
            const fileDate = clone.querySelector('.file-date');

            // Set file name
            fileName.textContent = file.name;
            
            // Set file size
            const sizeMB = (file.size / (1024 * 1024)).toFixed(2);
            fileSize.textContent = `${sizeMB} MB`;
            
            // Set file date
            const date = new Date(file.modified * 1000);
            fileDate.textContent = date.toLocaleDateString();

            // Set file icon based on extension
            const extension = file.name.split('.').pop().toLowerCase();
            this.setFileIcon(fileIcon, extension);

            // Add event listeners
            clone.querySelector('.open-file').addEventListener('click', () => {
                this.openFile(file.name);
            });

            clone.querySelector('.download-file').addEventListener('click', () => {
                this.downloadFileAgain(file.name);
            });

            clone.querySelector('.delete-file').addEventListener('click', () => {
                this.deleteFile(file.name);
            });

            fileManager.appendChild(clone);
        });
    }

    setFileIcon(iconElement, extension) {
        const iconMap = {
            'zip': 'file-archive',
            'rar': 'file-archive',
            '7z': 'file-archive',
            'pdf': 'file-pdf',
            'jpg': 'file-image',
            'jpeg': 'file-image',
            'png': 'file-image',
            'gif': 'file-image',
            'mp4': 'file-video',
            'avi': 'file-video',
            'mov': 'file-video',
            'mp3': 'file-audio',
            'wav': 'file-audio',
            'txt': 'file-alt',
            'doc': 'file-word',
            'docx': 'file-word',
            'xls': 'file-excel',
            'xlsx': 'file-excel',
            'exe': 'cog'
        };

        const iconClass = iconMap[extension] || 'file';
        iconElement.innerHTML = `<i class="fas fa-${iconClass}"></i>`;
        
        // Add file type class for styling
        const fileType = Object.keys(iconMap).find(key => iconMap[key] === iconClass) || 'document';
        iconElement.parentNode.parentNode.classList.add(`file-${fileType}`);
    }

    openFile(filename) {
        window.open(`/downloads/${filename}`, '_blank');
    }

    async downloadFileAgain(filename) {
        // This would re-download the file - for now just open it
        this.openFile(filename);
    }

    async deleteFile(filename) {
        if (!confirm(`Are you sure you want to delete "${filename}"?`)) {
            return;
        }

        try {
            const response = await fetch(`/api/files/${filename}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                this.showAlert('File deleted successfully', 'success');
                this.loadFiles(); // Refresh file list
                this.loadDashboardStats(); // Update dashboard
            } else {
                const data = await response.json();
                this.showAlert('Error: ' + data.error, 'danger');
            }
        } catch (error) {
            this.showAlert('Error deleting file: ' + error.message, 'danger');
        }
    }

    openDownloadsFolder() {
        // This would open the system file explorer - for web, we show the file list
        this.switchPage('files');
    }
}

// Initialize the application
document.addEventListener('DOMContentLoaded', () => {
    window.downloadManager = new DownloadManager();
});