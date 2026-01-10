"""
app.py - TurboLane Download Manager Web Interface
FIXED VERSION with all errors resolved
"""

from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
import os
import threading
import time
import json
import mimetypes
import glob
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from downloader.downloader import MultiStreamDownloader
from downloader.simple_downloader import SimpleDownloader
from downloader.config import (
    DOWNLOAD_FOLDER,
    TEMP_FOLDER,
    COMPLETED_FOLDER,
    FAILED_FOLDER,
    FLASK_HOST,
    FLASK_PORT,
    FLASK_DEBUG,
    RL_ALGORITHM,
    DEFAULT_NUM_STREAMS,
    MIN_STREAMS,
    MAX_STREAMS,
    MAX_DOWNLOAD_SIZE,
    ALLOWED_DOMAINS
)

# Initialize Flask app
app = Flask(__name__, 
           template_folder='templates',
           static_folder='static')
app.config['SECRET_KEY'] = 'turbolane-secret-key-2024'
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

# Ensure download directories exist
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(TEMP_FOLDER, exist_ok=True)
os.makedirs(COMPLETED_FOLDER, exist_ok=True)
os.makedirs(FAILED_FOLDER, exist_ok=True)


class DownloadManager:
    """
    Manages active downloads with thread-safe operations.
    FIXED: Proper JSON serialization and type safety
    """
    
    def __init__(self):
        self.active_downloads = {}
        self.completed_downloads = {}
        self.failed_downloads = {}
        self.lock = threading.Lock()
        
        # Load previous session data
        self._load_session_data()
    
    def _load_session_data(self):
        """Load previous download session data - FIXED VERSION"""
        try:
            session_file = os.path.join(DOWNLOAD_FOLDER, 'session.json')
            if os.path.exists(session_file):
                with open(session_file, 'r') as f:
                    data = json.load(f)
                    
                    # Load only serializable data, not downloader objects
                    self.completed_downloads = data.get('completed', {})
                    self.failed_downloads = data.get('failed', {})
                    
                    # Convert string numbers to integers
                    for downloads_dict in [self.completed_downloads, self.failed_downloads]:
                        for download_id, download_info in downloads_dict.items():
                            if isinstance(download_info.get('total_size'), str):
                                try:
                                    download_info['total_size'] = int(float(download_info['total_size']))
                                except (ValueError, TypeError):
                                    download_info['total_size'] = 0
                    
                    print(f"✅ Loaded session data: {len(self.completed_downloads)} completed, "
                          f"{len(self.failed_downloads)} failed downloads")
        except json.JSONDecodeError as e:
            print(f"⚠️ Corrupted session file: {e}")
            # Create fresh session file
            self._save_session_data()
        except Exception as e:
            print(f"⚠️ Could not load session data: {e}")
    
    def _save_session_data(self):
        """Save download session data - FIXED to be JSON serializable"""
        try:
            session_file = os.path.join(DOWNLOAD_FOLDER, 'session.json')
            
            # Create serializable data WITHOUT downloader objects
            serializable_data = {
                'completed': {},
                'failed': {},
                'timestamp': time.time(),
                'version': '2.0'
            }
            
            # Convert completed downloads to serializable format
            for download_id, download_info in self.completed_downloads.items():
                serializable_data['completed'][download_id] = self._make_serializable(download_info)
            
            # Convert failed downloads to serializable format
            for download_id, download_info in self.failed_downloads.items():
                serializable_data['failed'][download_id] = self._make_serializable(download_info)
            
            # Save with pretty formatting
            with open(session_file, 'w') as f:
                json.dump(serializable_data, f, indent=2, default=str)
                
        except Exception as e:
            print(f"⚠️ Could not save session data: {e}")
    
    def _make_serializable(self, download_info):
        """Convert download info to serializable format - FIXED VERSION"""
        # Create a copy without the downloader object and thread
        serializable = {
            'url': download_info.get('url', ''),
            'mode': download_info.get('mode', 'multi'),
            'status': download_info.get('status', 'unknown'),
            'progress': download_info.get('progress', 0),
            'speed': download_info.get('speed', '0 Mbps'),
            'speed_mbps': download_info.get('speed_mbps', 0),
            'start_time': download_info.get('start_time', time.time()),
            'end_time': download_info.get('end_time'),
            'filename': download_info.get('filename'),
            'error': download_info.get('error'),
            'total_size': download_info.get('total_size', 0),
            'downloaded_size': download_info.get('downloaded_size', 0),
            'use_rl': download_info.get('use_rl', False),
            'algorithm': download_info.get('algorithm', RL_ALGORITHM),
            'num_streams': download_info.get('num_streams', DEFAULT_NUM_STREAMS),
            'current_streams': download_info.get('current_streams', DEFAULT_NUM_STREAMS),
            'user_id': download_info.get('user_id'),
            'metadata': download_info.get('metadata', {}),
            'metrics': download_info.get('metrics', {}),
            'result_path': download_info.get('result_path'),
            'download_time': download_info.get('download_time'),
            'average_speed_mbps': download_info.get('average_speed_mbps', 0)
        }
        
        # Ensure numeric types are numbers, not strings
        for key in ['total_size', 'downloaded_size', 'speed_mbps', 'average_speed_mbps']:
            if key in serializable and isinstance(serializable[key], str):
                try:
                    serializable[key] = float(serializable[key])
                except (ValueError, TypeError):
                    serializable[key] = 0
        
        return serializable
    
    def start_download(self, url, mode="multi", num_streams=None, 
                       use_rl=False, algorithm=None, user_id=None):
        """
        Start a new download.
        """
        download_id = str(uuid.uuid4())
        
        try:
            # Validate URL
            if not url.startswith(('http://', 'https://')):
                raise ValueError("URL must start with http:// or https://")
            
            # Validate domain if restrictions exist
            if ALLOWED_DOMAINS:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                if domain not in ALLOWED_DOMAINS:
                    raise ValueError(f"Domain {domain} is not allowed")
            
            # Use configured algorithm if not specified
            if algorithm is None:
                algorithm = RL_ALGORITHM
            
            # Set default number of streams
            if num_streams is None:
                num_streams = DEFAULT_NUM_STREAMS
            
            # Validate stream count
            num_streams = max(MIN_STREAMS, min(MAX_STREAMS, num_streams))
            
            # Create appropriate downloader
            if mode == "single":
                downloader = SimpleDownloader(url, progress_callback=None)
            else:
                downloader = MultiStreamDownloader(
                    url, 
                    num_streams=num_streams, 
                    progress_callback=None,
                    use_rl=use_rl,
                    algorithm=algorithm
                )
            
            # Create download info
            download_info = {
                'downloader': downloader,
                'url': url,
                'mode': mode,
                'status': 'queued',
                'progress': 0,
                'speed': 0,
                'speed_mbps': 0,
                'start_time': time.time(),
                'end_time': None,
                'thread': None,
                'filename': None,
                'error': None,
                'total_size': 0,
                'downloaded_size': 0,
                'use_rl': use_rl,
                'algorithm': algorithm,
                'num_streams': num_streams,
                'current_streams': num_streams,
                'user_id': user_id,
                'metadata': {},
                'metrics': {}
            }
            
            # Store download
            with self.lock:
                self.active_downloads[download_id] = download_info
            
            # Start download in thread
            thread = threading.Thread(
                target=self._download_thread,
                args=(download_id,),
                daemon=True
            )
            thread.start()
            
            with self.lock:
                self.active_downloads[download_id]['thread'] = thread
                self.active_downloads[download_id]['status'] = 'downloading'
            
            print(f"📥 Started download {download_id}: {url}")
            print(f"   Mode: {mode}, Streams: {num_streams}, RL: {use_rl}, Algorithm: {algorithm}")
            
            return download_id
            
        except Exception as e:
            print(f"❌ Error starting download: {str(e)}")
            raise
    
    def _download_thread(self, download_id):
        """Download thread worker function."""
        download_info = self.active_downloads.get(download_id)
        if not download_info:
            return
        
        downloader = download_info['downloader']
        
        try:
            # Get file info
            if hasattr(downloader, 'check_download_support'):
                supports_ranges, file_size, filename = downloader.check_download_support()
                download_info['total_size'] = int(file_size) if file_size else 0
                download_info['filename'] = filename
            
            # Validate file size
            if download_info['total_size'] > MAX_DOWNLOAD_SIZE:
                raise ValueError(f"File size {download_info['total_size']} exceeds maximum allowed size")
            
            # Start download
            result = downloader.download()
            
            if result:
                # Download successful
                download_info['status'] = 'completed'
                download_info['result_path'] = result
                download_info['filename'] = os.path.basename(result)
                download_info['end_time'] = time.time()
                download_info['downloaded_size'] = download_info['total_size']
                download_info['progress'] = 100
                
                # Get metrics
                try:
                    if hasattr(downloader, 'get_detailed_metrics'):
                        download_info['metrics'] = downloader.get_detailed_metrics()
                except Exception as e:
                    print(f"⚠️ Error getting metrics: {str(e)}")
                    download_info['metrics'] = {}
                
                # Calculate download time and speed
                elapsed = download_info['end_time'] - download_info['start_time']
                if elapsed > 0:
                    download_info['download_time'] = elapsed
                    download_info['average_speed_mbps'] = (
                        download_info['total_size'] * 8 / (elapsed * 1024 * 1024)
                    )
                
                # Move to completed
                with self.lock:
                    self.completed_downloads[download_id] = self._make_serializable(download_info)
                
                print(f"✅ Download {download_id} completed successfully")
                
            else:
                # Download failed
                download_info['status'] = 'failed'
                download_info['error'] = 'Download failed or cancelled'
                download_info['end_time'] = time.time()
                
                with self.lock:
                    self.failed_downloads[download_id] = self._make_serializable(download_info)
                
                print(f"❌ Download {download_id} failed")
                
        except Exception as e:
            # Download error
            error_msg = str(e)
            download_info['status'] = 'failed'
            download_info['error'] = error_msg
            download_info['end_time'] = time.time()
            
            with self.lock:
                self.failed_downloads[download_id] = self._make_serializable(download_info)
            
            print(f"❌ Download error for {download_id}: {error_msg}")
        
        finally:
            # Clean up active download
            with self.lock:
                if download_id in self.active_downloads:
                    del self.active_downloads[download_id]
            
            # Save session data
            self._save_session_data()
    
    def get_download_status(self, download_id):
        """Get current status of a download."""
        with self.lock:
            if download_id in self.active_downloads:
                download_info = self.active_downloads[download_id]
                
                # Update progress if downloader exists
                if download_info['downloader']:
                    downloader = download_info['downloader']
                    try:
                        if hasattr(downloader, 'downloaded_bytes') and hasattr(downloader, 'file_size'):
                            if downloader.file_size > 0:
                                progress = (downloader.downloaded_bytes / downloader.file_size) * 100
                                download_info['progress'] = progress
                                download_info['downloaded_size'] = downloader.downloaded_bytes
                                download_info['total_size'] = downloader.file_size
                            
                            # Get current speed
                            if hasattr(downloader, 'calculate_throughput'):
                                speed_mbps = downloader.calculate_throughput()
                                download_info['speed_mbps'] = speed_mbps
                                download_info['speed'] = f"{speed_mbps:.2f} Mbps"
                            
                            # Get current stream count for RL
                            if hasattr(downloader, 'current_stream_count'):
                                download_info['current_streams'] = downloader.current_stream_count
                    except Exception as e:
                        print(f"⚠️ Error updating progress: {str(e)}")
                
                return self._serialize_download_info(download_info)
            
            elif download_id in self.completed_downloads:
                return self._serialize_download_info(self.completed_downloads[download_id])
            
            elif download_id in self.failed_downloads:
                return self._serialize_download_info(self.failed_downloads[download_id])
            
            else:
                return None
    
    def _serialize_download_info(self, download_info):
        """Convert download info to serializable format for API."""
        serializable = {
            'id': None,  # Will be set by caller
            'url': download_info.get('url', ''),
            'filename': download_info.get('filename'),
            'mode': download_info.get('mode', 'multi'),
            'status': download_info.get('status', 'unknown'),
            'progress': download_info.get('progress', 0),
            'speed': download_info.get('speed', '0 Mbps'),
            'speed_mbps': download_info.get('speed_mbps', 0),
            'start_time': download_info.get('start_time', 0),
            'end_time': download_info.get('end_time'),
            'total_size': download_info.get('total_size', 0),
            'downloaded_size': download_info.get('downloaded_size', 0),
            'error': download_info.get('error'),
            'use_rl': download_info.get('use_rl', False),
            'algorithm': download_info.get('algorithm', RL_ALGORITHM),
            'num_streams': download_info.get('num_streams', DEFAULT_NUM_STREAMS),
            'current_streams': download_info.get('current_streams', DEFAULT_NUM_STREAMS),
            'user_id': download_info.get('user_id'),
            'metadata': download_info.get('metadata', {}),
            'metrics': download_info.get('metrics', {}),
            'result_path': download_info.get('result_path'),
            'download_time': download_info.get('download_time'),
            'average_speed_mbps': download_info.get('average_speed_mbps', 0)
        }
        
        # Add formatted timestamps
        if serializable['start_time']:
            serializable['start_time_formatted'] = datetime.fromtimestamp(
                serializable['start_time']
            ).strftime('%Y-%m-%d %H:%M:%S')
        
        if serializable['end_time']:
            serializable['end_time_formatted'] = datetime.fromtimestamp(
                serializable['end_time']
            ).strftime('%Y-%m-%d %H:%M:%S')
        
        # Add human-readable size
        total_bytes = serializable['total_size']
        serializable['total_size_human'] = self._human_readable_size(total_bytes)
        
        # Add download speed human readable
        speed_mbps = serializable['average_speed_mbps']
        serializable['average_speed'] = f"{speed_mbps:.2f} Mbps" if speed_mbps > 0 else "0 Mbps"
        
        return serializable
    
    def get_all_downloads(self):
        """Get status of all downloads."""
        all_downloads = []
        
        with self.lock:
            # Active downloads
            for download_id, download_info in self.active_downloads.items():
                status = self._serialize_download_info(download_info)
                status['id'] = download_id
                all_downloads.append(status)
            
            # Completed downloads (last 50)
            completed_items = list(self.completed_downloads.items())[-50:]
            for download_id, download_info in completed_items:
                status = self._serialize_download_info(download_info)
                status['id'] = download_id
                all_downloads.append(status)
            
            # Failed downloads (last 20)
            failed_items = list(self.failed_downloads.items())[-20:]
            for download_id, download_info in failed_items:
                status = self._serialize_download_info(download_info)
                status['id'] = download_id
                all_downloads.append(status)
        
        # Sort by start time (newest first)
        all_downloads.sort(key=lambda x: x.get('start_time', 0), reverse=True)
        
        return all_downloads
    
    def cancel_download(self, download_id):
        """Cancel an active download."""
        with self.lock:
            if download_id in self.active_downloads:
                download_info = self.active_downloads[download_id]
                if download_info['downloader']:
                    try:
                        download_info['downloader'].cancel()
                    except:
                        pass
                
                download_info['status'] = 'cancelled'
                download_info['error'] = 'Cancelled by user'
                download_info['end_time'] = time.time()
                
                # Move to failed
                self.failed_downloads[download_id] = self._make_serializable(download_info)
                
                # Remove from active
                del self.active_downloads[download_id]
                
                self._save_session_data()
                return True
        
        return False
    
    def clear_completed(self):
        """Clear completed downloads history."""
        with self.lock:
            self.completed_downloads.clear()
            self._save_session_data()
        return True
    
    def clear_failed(self):
        """Clear failed downloads history."""
        with self.lock:
            self.failed_downloads.clear()
            self._save_session_data()
        return True
    
    def get_statistics(self):
        """Get download statistics - FIXED VERSION with type safety."""
        with self.lock:
            stats = {
                'active': len(self.active_downloads),
                'completed': len(self.completed_downloads),
                'failed': len(self.failed_downloads),
                'total': len(self.completed_downloads) + len(self.failed_downloads),
                'rl_enabled': True,  # Always enabled now
                'algorithm': RL_ALGORITHM,
                'max_streams': MAX_STREAMS,
                'default_streams': DEFAULT_NUM_STREAMS
            }
            
            # Calculate total downloaded bytes - SAFELY
            total_bytes = 0
            for download_info in self.completed_downloads.values():
                size = download_info.get('total_size', 0)
                
                # Convert to int safely
                if isinstance(size, str):
                    try:
                        size = float(size)
                    except (ValueError, TypeError):
                        size = 0
                elif not isinstance(size, (int, float)):
                    size = 0
                
                total_bytes += int(size)
            
            stats['total_downloaded_bytes'] = int(total_bytes)
            
            # Format human-readable sizes
            stats['total_downloaded'] = self._human_readable_size(total_bytes)
            
            return stats
    
    def _human_readable_size(self, size_bytes):
        """Convert bytes to human readable format."""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        
        return f"{size_bytes:.2f} {size_names[i]}"


# Initialize download manager
download_manager = DownloadManager()


# ==================== Flask Routes ====================

@app.route('/')
def index():
    """Main page with download interface."""
    return render_template('index.html',
                         rl_available=True,
                         algorithm=RL_ALGORITHM,
                         default_streams=DEFAULT_NUM_STREAMS,
                         min_streams=MIN_STREAMS,
                         max_streams=MAX_STREAMS)


@app.route('/dashboard')
def dashboard():
    """Dashboard with download statistics."""
    stats = download_manager.get_statistics()
    return render_template('dashboard.html',
                         stats=stats,
                         rl_available=True,
                         algorithm=RL_ALGORITHM)


@app.route('/api/downloads', methods=['POST'])
def start_download():
    """
    Start a new download.
    """
    data = request.json
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    url = data.get('url', '').strip()
    mode = data.get('mode', 'multi')
    num_streams = data.get('num_streams', DEFAULT_NUM_STREAMS)
    use_rl = data.get('use_rl', True)
    algorithm = data.get('algorithm', RL_ALGORITHM)
    
    # Validation
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    if not url.startswith(('http://', 'https://')):
        return jsonify({'error': 'URL must start with http:// or https://'}), 400
    
    if mode not in ['single', 'multi']:
        return jsonify({'error': 'Mode must be "single" or "multi"'}), 400
    
    if not isinstance(num_streams, int) or num_streams < MIN_STREAMS or num_streams > MAX_STREAMS:
        return jsonify({'error': f'Number of streams must be between {MIN_STREAMS} and {MAX_STREAMS}'}), 400
    
    if algorithm not in ['qlearning', 'ppo']:
        return jsonify({'error': 'Algorithm must be "qlearning" or "ppo"'}), 400
    
    # Get user ID from session or generate one
    user_id = session.get('user_id')
    if not user_id:
        user_id = str(uuid.uuid4())
        session['user_id'] = user_id
        session.permanent = True
    
    try:
        download_id = download_manager.start_download(
            url=url,
            mode=mode,
            num_streams=num_streams,
            use_rl=use_rl,
            algorithm=algorithm,
            user_id=user_id
        )
        
        return jsonify({
            'download_id': download_id,
            'message': 'Download started successfully',
            'use_rl': use_rl,
            'algorithm': algorithm,
            'num_streams': num_streams,
            'mode': mode
        })
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        print(f"❌ Error starting download: {str(e)}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500


@app.route('/api/downloads', methods=['GET'])
def list_downloads():
    """List all downloads."""
    try:
        downloads = download_manager.get_all_downloads()
        return jsonify({
            'downloads': downloads,
            'count': len(downloads)
        })
    except Exception as e:
        print(f"Error listing downloads: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/downloads/<download_id>')
def get_download_status(download_id):
    """Get status of a specific download."""
    try:
        status = download_manager.get_download_status(download_id)
        if status:
            return jsonify(status)
        else:
            return jsonify({'error': 'Download not found'}), 404
    except Exception as e:
        print(f"Error getting download status for {download_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/downloads/<download_id>/cancel', methods=['POST'])
def cancel_download(download_id):
    """Cancel a download."""
    if download_manager.cancel_download(download_id):
        return jsonify({'message': 'Download cancelled successfully'})
    else:
        return jsonify({'error': 'Download not found or not active'}), 404


@app.route('/api/downloads/<download_id>/metrics')
def get_download_metrics(download_id):
    """Get detailed metrics for a download."""
    status = download_manager.get_download_status(download_id)
    if status and 'metrics' in status:
        return jsonify(status['metrics'])
    else:
        return jsonify({'error': 'Metrics not available'}), 404


@app.route('/api/downloads/clear/completed', methods=['POST'])
def clear_completed_downloads():
    """Clear completed downloads history."""
    if download_manager.clear_completed():
        return jsonify({'message': 'Completed downloads cleared successfully'})
    else:
        return jsonify({'error': 'Failed to clear completed downloads'}), 500


@app.route('/api/downloads/clear/failed', methods=['POST'])
def clear_failed_downloads():
    """Clear failed downloads history."""
    if download_manager.clear_failed():
        return jsonify({'message': 'Failed downloads cleared successfully'})
    else:
        return jsonify({'error': 'Failed to clear failed downloads'}), 500


# ==================== RL Management Routes ====================

@app.route('/api/rl/stats')
def get_rl_stats():
    """Get RL learning statistics."""
    try:
        # Try to import TurboLane engine dynamically
        try:
            from turbolane.policies import TurboLaneEngine
            turbolane_engine = TurboLaneEngine(mode='client', algorithm=RL_ALGORITHM)
            stats = turbolane_engine.get_stats()
            available = True
        except ImportError:
            stats = {'error': 'RL engine not available'}
            available = False
        
        return jsonify({
            'algorithm': RL_ALGORITHM,
            'stats': stats,
            'available': available
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/rl/reset', methods=['POST'])
def reset_rl():
    """Reset RL learning (clear model)."""
    try:
        from turbolane.policies import TurboLaneEngine
        turbolane_engine = TurboLaneEngine(mode='client', algorithm=RL_ALGORITHM)
        turbolane_engine.reset()
        return jsonify({
            'message': f'{RL_ALGORITHM.upper()} learning reset successfully',
            'algorithm': RL_ALGORITHM
        })
    except ImportError:
        return jsonify({'error': 'RL engine not available'}), 503
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== File Management Routes ====================

@app.route('/api/files')
def list_files():
    """List all files in the download folder."""
    try:
        files = []
        
        # Check download folder
        for file_path in glob.glob(os.path.join(DOWNLOAD_FOLDER, '*')):
            if os.path.isfile(file_path):
                filename = os.path.basename(file_path)
                file_size = os.path.getsize(file_path)
                modified_time = os.path.getmtime(file_path)
                
                # Skip temporary files
                if not (filename.startswith('.') or 
                       filename.endswith('.part') or
                       filename == 'session.json'):
                    
                    files.append({
                        'name': filename,
                        'size': file_size,
                        'modified': modified_time,
                        'path': file_path,
                        'size_human': download_manager._human_readable_size(file_size),
                        'modified_formatted': datetime.fromtimestamp(modified_time).strftime('%Y-%m-%d %H:%M:%S')
                    })
        
        # Sort by modified time (newest first)
        files.sort(key=lambda x: x['modified'], reverse=True)
        
        return jsonify({
            'files': files,
            'count': len(files),
            'download_folder': DOWNLOAD_FOLDER
        })
    except Exception as e:
        print(f"Error listing files: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/files/<filename>', methods=['DELETE'])
def delete_file(filename):
    """Delete a file from the download folder."""
    try:
        # Security check
        if '..' in filename or '/' in filename or '\\' in filename:
            return jsonify({'error': 'Invalid filename'}), 400
        
        file_path = os.path.join(DOWNLOAD_FOLDER, filename)
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        
        os.remove(file_path)
        return jsonify({'message': 'File deleted successfully'})
        
    except Exception as e:
        print(f"Error deleting file {filename}: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/download/<filename>')
def download_file(filename):
    """Download a file."""
    try:
        # Security check
        if '..' in filename or '/' in filename or '\\' in filename:
            return jsonify({'error': 'Invalid filename'}), 400
        
        file_path = os.path.join(DOWNLOAD_FOLDER, filename)
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        
        return send_file(
            file_path, 
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        print(f"Error downloading file {filename}: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ==================== Statistics Routes ====================

@app.route('/api/stats')
def get_stats():
    """Get download statistics."""
    try:
        # Get download manager stats
        dm_stats = download_manager.get_statistics()
        
        # Get file system stats
        total_files = 0
        total_size = 0
        
        for file_path in glob.glob(os.path.join(DOWNLOAD_FOLDER, '*')):
            if os.path.isfile(file_path):
                filename = os.path.basename(file_path)
                if not (filename.startswith('.') or 
                       filename.endswith('.part') or
                       filename == 'session.json'):
                    total_files += 1
                    total_size += os.path.getsize(file_path)
        
        stats = {
            'downloads': dm_stats,
            'filesystem': {
                'total_files': total_files,
                'total_size': total_size,
                'total_size_human': download_manager._human_readable_size(total_size),
                'download_folder': DOWNLOAD_FOLDER
            },
            'configuration': {
                'algorithm': RL_ALGORITHM,
                'default_streams': DEFAULT_NUM_STREAMS,
                'min_streams': MIN_STREAMS,
                'max_streams': MAX_STREAMS,
                'download_folder': DOWNLOAD_FOLDER,
                'rl_available': True
            },
            'timestamp': time.time()
        }
        
        return jsonify(stats)
    except Exception as e:
        print(f"Error getting stats: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ==================== Health Check ====================

@app.route('/health')
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'timestamp': time.time(),
        'version': '1.0.0',
        'algorithm': RL_ALGORITHM
    })


# ==================== Error Handlers ====================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500


@app.errorhandler(413)
def too_large(error):
    return jsonify({'error': 'File too large'}), 413


# ==================== Main Entry Point ====================

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 TurboLane Download Manager Starting...")
    print("=" * 60)
    print(f"📁 Download folder: {DOWNLOAD_FOLDER}")
    print(f"🌐 Web interface: http://{FLASK_HOST}:{FLASK_PORT}")
    print(f"🔧 Debug mode: {FLASK_DEBUG}")
    print(f"🤖 RL Algorithm: {RL_ALGORITHM.upper()}")
    print(f"📊 Default streams: {DEFAULT_NUM_STREAMS}")
    print(f"📊 Stream range: {MIN_STREAMS}-{MAX_STREAMS}")
    print("=" * 60)
    
    # Start Flask app
    app.run(
        debug=FLASK_DEBUG,
        host=FLASK_HOST,
        port=FLASK_PORT,
        threaded=True
    )