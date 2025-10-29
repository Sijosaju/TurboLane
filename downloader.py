# downloader.py - Core download functionality with detailed metrics and debugging

import os
import requests
import threading
from urllib.parse import urlparse, unquote
import time
from config import *

class MultiStreamDownloader:
    def __init__(self, url, num_streams=DEFAULT_NUM_STREAMS, progress_callback=None):
        """
        Initialize the downloader.
            url: The URL to download from
            num_streams: Number of parallel streams to use
            progress_callback: Function to call with progress updates (for GUI)
        """
        self.url = url
        self.num_streams = min(max(num_streams, MIN_STREAMS), MAX_STREAMS)
        self.progress_callback = progress_callback
        
        # Download state
        self.file_size = 0
        self.downloaded_bytes = 0
        self.chunks = []
        self.temp_files = []
        self.is_downloading = False
        self.threads = []
        self.lock = threading.Lock()
        self.start_time = None
        
        # Metrics tracking
        self.chunk_start_times = {}
        self.chunk_end_times = {}
        self.chunk_speeds = {}
        self.chunk_bytes = {}
        
    def get_filename_from_url(self):
        """Extract filename from URL or generate one."""
        path = urlparse(self.url).path
        filename = unquote(os.path.basename(path))
        
        if not filename or filename == '/':
            filename = 'downloaded_file'
        
        return filename
    
    def check_download_support(self):
        """
        Check if the server supports range requests (parallel downloads).
        Returns: (supports_ranges, file_size, filename)
        """
        try:
            # First try HEAD request
            try:
                response = requests.head(
                    self.url, 
                    timeout=CONNECTION_TIMEOUT, 
                    allow_redirects=True
                )
                
                if response.status_code == 200:
                    supports_ranges = response.headers.get('Accept-Ranges') == 'bytes'
                    file_size = int(response.headers.get('Content-Length', 0))
                    
                    # Get filename
                    content_disposition = response.headers.get('Content-Disposition', '')
                    if 'filename=' in content_disposition:
                        filename = content_disposition.split('filename=')[1].strip('"')
                    else:
                        filename = self.get_filename_from_url()
                    
                    return supports_ranges, file_size, filename
            except:
                # HEAD failed, try GET with small range
                print("HEAD request failed, trying GET with range...")
                pass
            
            # Fallback: Use GET request with a small range to test support
            headers = {'Range': 'bytes=0-0'}
            response = requests.get(
                self.url,
                headers=headers,
                timeout=CONNECTION_TIMEOUT,
                allow_redirects=True,
                stream=True
            )
            
            # Check if server supports ranges
            # Status 206 means partial content (ranges supported)
            # Status 200 means full content (ranges NOT supported)
            supports_ranges = response.status_code == 206
            
            # Get file size from Content-Range header or Content-Length
            if 'Content-Range' in response.headers:
                # Format: "bytes 0-0/12345" where 12345 is total size
                content_range = response.headers['Content-Range']
                file_size = int(content_range.split('/')[1])
            else:
                file_size = int(response.headers.get('Content-Length', 0))
            
            # Get filename
            content_disposition = response.headers.get('Content-Disposition', '')
            if 'filename=' in content_disposition:
                filename = content_disposition.split('filename=')[1].strip('"')
            else:
                filename = self.get_filename_from_url()
            
            response.close()  # Close the connection
            
            return supports_ranges, file_size, filename
            
        except Exception as e:
            raise Exception(f"Failed to check URL: {str(e)}")
    
    def calculate_chunks(self, file_size):
        """
        Divide the file into chunks for parallel download.
        Returns: List of (start_byte, end_byte) tuples
        """
        # If file is too small, use fewer streams
        if file_size < MIN_CHUNK_SIZE * self.num_streams:
            self.num_streams = max(1, file_size // MIN_CHUNK_SIZE)
            if self.num_streams == 0:
                self.num_streams = 1
        
        chunk_size = file_size // self.num_streams
        chunks = []
        
        for i in range(self.num_streams):
            start = i * chunk_size
            # Last chunk gets any remaining bytes
            end = file_size - 1 if i == self.num_streams - 1 else (i + 1) * chunk_size - 1
            chunks.append((start, end))
        
        return chunks
    
    def download_chunk(self, chunk_id, start, end, temp_file):
        """
        Download a specific chunk of the file with metrics tracking and retry logic.
        
        Args:
            chunk_id: ID of this chunk (for tracking)
            start: Starting byte position
            end: Ending byte position
            temp_file: Path to temporary file for this chunk
        """
        headers = {'Range': f'bytes={start}-{end}'}
        
        # Track start time for this chunk
        self.chunk_start_times[chunk_id] = time.time()
        chunk_bytes_downloaded = 0
        
        max_retries = MAX_RETRIES
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                response = requests.get(
                    self.url, 
                    headers=headers, 
                    stream=True,
                    timeout=(CONNECTION_TIMEOUT, READ_TIMEOUT),
                    allow_redirects=True
                )
                
                # Check if request was successful (206 for partial content, 200 for full)
                if response.status_code not in [200, 206]:
                    print(f"Chunk {chunk_id}: Bad status code {response.status_code}")
                    retry_count += 1
                    if retry_count < max_retries:
                        time.sleep(RETRY_DELAY)
                    continue
                
                # Reset counter for this attempt
                chunk_bytes_downloaded = 0
                
                with open(temp_file, 'wb') as f:
                    for data in response.iter_content(chunk_size=BUFFER_SIZE):
                        if not self.is_downloading:
                            print(f"Chunk {chunk_id}: Download cancelled")
                            break
                        
                        if data:  # Filter out keep-alive chunks
                            f.write(data)
                            chunk_bytes_downloaded += len(data)
                            
                            # Update progress
                            with self.lock:
                                self.downloaded_bytes += len(data)
                                if self.progress_callback:
                                    self.progress_callback(self.downloaded_bytes, self.file_size)
                
                # Track end time and calculate speed for this chunk
                self.chunk_end_times[chunk_id] = time.time()
                elapsed = self.chunk_end_times[chunk_id] - self.chunk_start_times[chunk_id]
                self.chunk_bytes[chunk_id] = chunk_bytes_downloaded
                self.chunk_speeds[chunk_id] = (chunk_bytes_downloaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                
                print(f"Chunk {chunk_id}: Downloaded {chunk_bytes_downloaded / (1024*1024):.2f} MB in {elapsed:.2f}s")
                break  # Success, exit retry loop
                
            except requests.exceptions.Timeout:
                retry_count += 1
                print(f"Chunk {chunk_id}: Timeout (attempt {retry_count}/{max_retries})")
                if retry_count < max_retries:
                    time.sleep(RETRY_DELAY)
                else:
                    print(f"Chunk {chunk_id}: Failed after {max_retries} attempts")
                    self.chunk_end_times[chunk_id] = time.time()
                    self.chunk_bytes[chunk_id] = chunk_bytes_downloaded
                    
            except Exception as e:
                retry_count += 1
                print(f"Chunk {chunk_id}: Error (attempt {retry_count}/{max_retries}): {str(e)}")
                if retry_count < max_retries:
                    time.sleep(RETRY_DELAY)
                else:
                    print(f"Chunk {chunk_id}: Failed after {max_retries} attempts")
                    self.chunk_end_times[chunk_id] = time.time()
                    self.chunk_bytes[chunk_id] = chunk_bytes_downloaded
    
    def assemble_file(self, output_file):
        """Combine all temporary chunk files into the final file."""
        print(f"Assembling {len(self.temp_files)} parts into final file...")
        
        with open(output_file, 'wb') as outfile:
            for i, temp_file in enumerate(self.temp_files):
                if os.path.exists(temp_file):
                    file_size = os.path.getsize(temp_file)
                    print(f"  Adding part {i}: {file_size / (1024*1024):.2f} MB")
                    
                    with open(temp_file, 'rb') as infile:
                        outfile.write(infile.read())
                    
                    # Delete temp file after combining
                    try:
                        os.remove(temp_file)
                    except:
                        pass
                else:
                    print(f"  WARNING: Part {i} not found at {temp_file}")
        
        final_size = os.path.getsize(output_file)
        print(f"Final file assembled: {final_size / (1024*1024):.2f} MB")
    
    def get_detailed_metrics(self):
        """
        Calculate detailed download metrics.
        Returns dictionary with all metrics.
        """
        if not self.start_time:
            return None
        
        end_time = max(self.chunk_end_times.values()) if self.chunk_end_times else time.time()
        total_time = end_time - self.start_time
        
        # Calculate overall throughput
        throughput_mbps = (self.file_size * 8) / (total_time * 1024 * 1024) if total_time > 0 else 0
        throughput_MBps = self.file_size / (total_time * 1024 * 1024) if total_time > 0 else 0
        
        # Calculate per-chunk metrics
        chunk_metrics = []
        for chunk_id in range(len(self.chunks)):
            if chunk_id in self.chunk_start_times and chunk_id in self.chunk_end_times:
                chunk_time = self.chunk_end_times[chunk_id] - self.chunk_start_times[chunk_id]
                chunk_size = self.chunk_bytes.get(chunk_id, 0)
                chunk_speed = self.chunk_speeds.get(chunk_id, 0)
                
                chunk_metrics.append({
                    'chunk_id': chunk_id,
                    'size_mb': chunk_size / (1024 * 1024),
                    'time_seconds': chunk_time,
                    'speed_mbps': chunk_speed
                })
        
        # Find fastest and slowest chunks
        if chunk_metrics:
            fastest_chunk = max(chunk_metrics, key=lambda x: x['speed_mbps'])
            slowest_chunk = min(chunk_metrics, key=lambda x: x['speed_mbps'])
        else:
            fastest_chunk = slowest_chunk = None
        
        return {
            'total_time_seconds': total_time,
            'total_size_mb': self.file_size / (1024 * 1024),
            'throughput_mbps': throughput_mbps,
            'throughput_MBps': throughput_MBps,
            'num_streams_used': self.num_streams,
            'average_speed_per_stream': throughput_MBps / self.num_streams if self.num_streams > 0 else 0,
            'chunk_metrics': chunk_metrics,
            'fastest_chunk': fastest_chunk,
            'slowest_chunk': slowest_chunk
        }
    
    def print_metrics_report(self):
        """Print a detailed metrics report to console."""
        metrics = self.get_detailed_metrics()
        if not metrics:
            return
        
        print("\n" + "="*60)
        print("DOWNLOAD METRICS REPORT")
        print("="*60)
        print(f"Total Download Time: {metrics['total_time_seconds']:.2f} seconds")
        print(f"File Size: {metrics['total_size_mb']:.2f} MB")
        print(f"Number of Streams: {metrics['num_streams_used']}")
        print(f"\nOverall Throughput:")
        print(f"  - {metrics['throughput_mbps']:.2f} Mbps")
        print(f"  - {metrics['throughput_MBps']:.2f} MB/s")
        print(f"  - Average per stream: {metrics['average_speed_per_stream']:.2f} MB/s")
        
        if metrics['chunk_metrics']:
            print(f"\nPer-Stream Performance:")
            print(f"  {'Stream':<8} {'Size (MB)':<12} {'Time (s)':<12} {'Speed (MB/s)':<15}")
            print(f"  {'-'*50}")
            for chunk in metrics['chunk_metrics']:
                print(f"  {chunk['chunk_id']:<8} {chunk['size_mb']:<12.2f} "
                      f"{chunk['time_seconds']:<12.2f} {chunk['speed_mbps']:<15.2f}")
            
            if metrics['fastest_chunk']:
                print(f"\nFastest Stream: #{metrics['fastest_chunk']['chunk_id']} "
                      f"at {metrics['fastest_chunk']['speed_mbps']:.2f} MB/s")
            if metrics['slowest_chunk']:
                print(f"Slowest Stream: #{metrics['slowest_chunk']['chunk_id']} "
                      f"at {metrics['slowest_chunk']['speed_mbps']:.2f} MB/s")
        
        print("="*60 + "\n")
    
    def export_metrics_to_file(self, filename="download_metrics.txt"):
        """Export metrics to a text file for analysis."""
        metrics = self.get_detailed_metrics()
        if not metrics:
            return
        
        filepath = os.path.join(DOWNLOAD_FOLDER, filename)
        
        with open(filepath, 'w') as f:
            f.write("MULTI-STREAM DOWNLOAD METRICS\n")
            f.write("="*60 + "\n\n")
            f.write(f"Download URL: {self.url}\n")
            f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            f.write(f"Total Time: {metrics['total_time_seconds']:.2f} seconds\n")
            f.write(f"File Size: {metrics['total_size_mb']:.2f} MB\n")
            f.write(f"Streams Used: {metrics['num_streams_used']}\n\n")
            
            f.write(f"Overall Throughput: {metrics['throughput_mbps']:.2f} Mbps\n")
            f.write(f"Overall Throughput: {metrics['throughput_MBps']:.2f} MB/s\n")
            f.write(f"Average per stream: {metrics['average_speed_per_stream']:.2f} MB/s\n\n")
            
            f.write("Per-Stream Details:\n")
            f.write(f"{'Stream':<8} {'Size (MB)':<12} {'Time (s)':<12} {'Speed (MB/s)':<15}\n")
            f.write("-"*50 + "\n")
            
            for chunk in metrics['chunk_metrics']:
                f.write(f"{chunk['chunk_id']:<8} {chunk['size_mb']:<12.2f} "
                       f"{chunk['time_seconds']:<12.2f} {chunk['speed_mbps']:<15.2f}\n")
        
        print(f"Metrics exported to: {filepath}")
    
    def download(self, output_path=None):
        """
        Main download function - coordinates the entire download process.
        
        Args:
            output_path: Where to save the file (defaults to DOWNLOAD_FOLDER)
        
        Returns:
            Path to downloaded file on success, None on failure
        """
        try:
            # Step 1: Check if download is possible
            print("Checking server support...")
            supports_ranges, file_size, filename = self.check_download_support()
            self.file_size = file_size
            
            print(f"File: {filename}")
            print(f"File size: {file_size / (1024*1024):.2f} MB")
            print(f"Supports range requests: {supports_ranges}")
            
            if file_size == 0:
                raise Exception("File size is 0 or Content-Length header unavailable")
            
            if not supports_ranges:
                print("WARNING: Server doesn't support range requests. Using single stream.")
                self.num_streams = 1
            
            # Step 2: Setup output path
            if output_path is None:
                output_path = os.path.join(DOWNLOAD_FOLDER, filename)
            
            print(f"Output path: {output_path}")
            
            # Step 3: Calculate chunks
            self.chunks = self.calculate_chunks(file_size)
            print(f"\nStarting download with {self.num_streams} streams")
            print(f"Chunk breakdown:")
            
            for i, (start, end) in enumerate(self.chunks):
                chunk_size = end - start + 1
                print(f"  Stream {i}: bytes {start:,}-{end:,} ({chunk_size/(1024*1024):.2f} MB)")
            
            # Step 4: Start download
            self.is_downloading = True
            self.downloaded_bytes = 0
            self.start_time = time.time()
            self.threads = []
            self.temp_files = []
            
            print("\nDownloading...")
            
            # Create temporary files for each chunk
            for i, (start, end) in enumerate(self.chunks):
                temp_file = f"{output_path}.part{i}"
                self.temp_files.append(temp_file)
                
                # Create thread for this chunk
                thread = threading.Thread(
                    target=self.download_chunk,
                    args=(i, start, end, temp_file),
                    daemon=True
                )
                thread.start()
                self.threads.append(thread)
            
            # Step 5: Wait for all threads to complete
            for i, thread in enumerate(self.threads):
                thread.join()
            
            print("\nAll streams completed")
            
            # Step 6: Verify and assemble
            if self.is_downloading:  # Only if not cancelled
                # Check temp file sizes before assembly
                print("\nVerifying downloaded parts:")
                total_downloaded = 0
                for i, temp_file in enumerate(self.temp_files):
                    if os.path.exists(temp_file):
                        size = os.path.getsize(temp_file)
                        total_downloaded += size
                        expected_size = self.chunks[i][1] - self.chunks[i][0] + 1
                        status = "OK" if size == expected_size else f"MISMATCH (expected {expected_size})"
                        print(f"  Part {i}: {size:,} bytes - {status}")
                    else:
                        print(f"  Part {i}: MISSING!")
                
                print(f"\nTotal downloaded: {total_downloaded / (1024*1024):.2f} MB")
                print(f"Expected: {file_size / (1024*1024):.2f} MB")
                
                # Assemble the file
                self.assemble_file(output_path)
                
                # Verify final file
                if os.path.exists(output_path):
                    final_size = os.path.getsize(output_path)
                    print(f"\nFinal file size: {final_size / (1024*1024):.2f} MB")
                    
                    if final_size == file_size:
                        print("SUCCESS: File size matches!")
                    else:
                        print(f"WARNING: Size mismatch! Expected {file_size}, got {final_size}")
                
                # Print detailed metrics report
                self.print_metrics_report()
                self.export_metrics_to_file()
                
                return output_path
            else:
                print("Download cancelled.")
                self.cleanup()
                return None
                
        except Exception as e:
            print(f"\nDownload failed: {str(e)}")
            import traceback
            traceback.print_exc()
            self.cleanup()
            return None
    
    def cleanup(self):
        """Clean up temporary files."""
        print("Cleaning up temporary files...")
        for temp_file in self.temp_files:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                    print(f"  Removed: {temp_file}")
                except Exception as e:
                    print(f"  Failed to remove {temp_file}: {e}")
    
    def cancel(self):
        """Cancel the download."""
        print("Cancelling download...")
        self.is_downloading = False
        self.cleanup()
    
    def get_speed(self):
        """Calculate current download speed in MB/s."""
        if self.start_time and self.downloaded_bytes > 0:
            elapsed = time.time() - self.start_time
            return (self.downloaded_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0
        return 0