from flask import Flask, render_template, request, send_file, jsonify, Response, stream_with_context, send_from_directory
import os
import re
import tempfile
from pytube import YouTube
import instaloader
import requests
import json
import time
import yt_dlp
import threading
import queue
import logging
import datetime

app = Flask(__name__)
TEMP_DIR = tempfile.gettempdir()

# Global progress tracking
download_progress = {}
progress_queue = queue.Queue()

# Add this at the top of your file
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# Disable yt-dlp debug output more aggressively
yt_dlp.utils.bug_reports_message = lambda: ''

# Create a custom logger for yt-dlp
class QuietLogger:
    def debug(self, msg):
        pass
    
    def warning(self, msg):
        pass
    
    def error(self, msg):
        pass

# Create a static downloads directory if it doesn't exist
DOWNLOADS_DIR = os.path.join('/tmp', 'downloads')
if not os.path.exists(DOWNLOADS_DIR):
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Change logs directory to a writable location
LOGS_DIR = os.path.join('/tmp', 'logs')
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR, exist_ok=True)


# Custom progress hook for yt-dlp
def progress_hook(d):
    try:
        if d['status'] == 'downloading':
            download_id = d.get('info_dict', {}).get('id', 'video')
            
            # If we don't have a proper download_id, try to find it
            if download_id == 'video' and len(download_progress) > 0:
                # Use the most recent download_id
                download_id = list(download_progress.keys())[-1]
            
            # Calculate progress percentage
            percent = 0
            if 'total_bytes' in d and d['total_bytes'] > 0:
                percent = int(100 * d['downloaded_bytes'] / d['total_bytes'])
            elif 'total_bytes_estimate' in d and d['total_bytes_estimate'] > 0:
                percent = int(100 * d['downloaded_bytes'] / d['total_bytes_estimate'])
            
            # Always update progress to ensure UI is responsive
            if download_id in download_progress:
                download_progress[download_id].update({
                    'percent': percent,
                    'speed': d.get('speed', 0),
                    'eta': d.get('eta', 0),
                    'filename': d.get('filename', '')
                })
        
        elif d['status'] == 'finished':
            download_id = d.get('info_dict', {}).get('id', 'video')
            
            # If we don't have a proper download_id, try to find it
            if download_id == 'video' and len(download_progress) > 0:
                # Use the most recent download_id
                download_id = list(download_progress.keys())[-1]
            
            if download_id in download_progress:
                download_progress[download_id].update({
                    'percent': 100,
                    'speed': 0,
                    'eta': 0,
                    'filename': d.get('filename', ''),
                    'status': 'finished'
                })
    except Exception as e:
        # Don't log the error to avoid terminal output
        pass

# Format speed in human-readable form
def format_speed(speed):
    if speed is None:
        return 'Unknown'
    
    if speed < 1024:
        return f"{speed:.1f} B/s"
    elif speed < 1024 * 1024:
        return f"{speed/1024:.1f} KB/s"
    else:
        return f"{speed/(1024*1024):.1f} MB/s"

# Format ETA in human-readable form
def format_eta(eta):
    if eta is None or eta == 0:
        return 'Unknown'
    
    if eta < 60:
        return f"{eta} sec"
    elif eta < 3600:
        return f"{eta//60} min {eta%60} sec"
    else:
        return f"{eta//3600} hr {(eta%3600)//60} min"

# Server-Sent Events endpoint for progress updates
@app.route('/progress/<download_id>')
def progress_stream(download_id):
    def generate():
        last_percent = -1
        yield f"data: {json.dumps({'id': download_id, 'percent': 0, 'speed': 'Starting...', 'eta': 'Calculating...'})}\n\n"
        
        while True:
            # Check if download is complete
            if download_id in download_progress:
                if 'error' in download_progress[download_id]:
                    # If there's an error, send it to the client
                    yield f"data: {json.dumps({'id': download_id, 'error': download_progress[download_id]['error']})}\n\n"
                    break
                elif 'percent' in download_progress[download_id] and download_progress[download_id]['percent'] == 100:
                    # If download is complete
                    yield f"data: {json.dumps({'id': download_id, 'percent': 100, 'speed': 'Complete', 'eta': '0'})}\n\n"
                    break
                elif 'percent' in download_progress[download_id]:
                    # If we have progress info, always send updates
                    current = download_progress[download_id]
                    yield f"data: {json.dumps({'id': download_id, 'percent': current['percent'], 'speed': format_speed(current['speed']), 'eta': format_eta(current['eta'])})}\n\n"
            
            # Sleep to avoid high CPU usage, but keep updates frequent
            time.sleep(0.3)
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download():
    url = request.form.get('url')
    platform = request.form.get('platform', 'auto')
    format_type = request.form.get('format', 'video')
    quality = request.form.get('quality', 'highest')
    
    if not url:
        return jsonify({"error": "Please provide a URL"}), 400
    
    try:
        # Auto-detect platform if not specified
        if platform == 'auto':
            if 'youtube.com' in url or 'youtu.be' in url:
                platform = 'youtube'
            elif 'instagram.com' in url or 'instagr.am' in url:
                platform = 'instagram'
            elif 'facebook.com' in url or 'fb.com' in url or 'fb.watch' in url:
                platform = 'facebook'
            else:
                return jsonify({"error": "Could not detect platform from URL"}), 400
        
        # YouTube
        if platform == 'youtube':
            # Generate a download ID
            download_id = f"yt_{int(time.time())}"
            
            # Initialize progress tracking
            download_progress[download_id] = {
                'percent': 0,
                'speed': 0,
                'eta': 0,
                'status': 'starting'
            }
            
            # Return the download ID first
            response = {
                "download_id": download_id,
                "status": "started",
                "message": "Download started. Please wait..."
            }
            
            # Start download in background
            threading.Thread(target=download_youtube_with_progress, 
                            args=(url, format_type, quality, download_id)).start()
            
            return jsonify(response)
        
        # Instagram
        elif platform == 'instagram':
            # Generate a download ID
            download_id = f"ig_{int(time.time())}"
            
            # Initialize progress tracking
            download_progress[download_id] = {
                'percent': 0,
                'speed': 0,
                'eta': 0,
                'status': 'starting'
            }
            
            # Return the download ID first
            response = {
                "download_id": download_id,
                "status": "started",
                "message": "Download started. Please wait..."
            }
            
            # Start download in background
            threading.Thread(target=download_instagram_with_progress, 
                            args=(url, download_id)).start()
            
            return jsonify(response)
        
        # Facebook
        elif platform == 'facebook':
            return download_facebook_alternative(url)
        
        else:
            return jsonify({"error": "Unsupported platform"}), 400
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def download_youtube_with_progress(url, format_type, quality, download_id):
    """Download YouTube video with progress tracking"""
    try:
        # Create a unique filename
        timestamp = int(time.time())
        
        if format_type == 'audio':
            # Download as MP3
            filename = f"youtube_audio_{timestamp}.mp3"
            temp_file_path = os.path.join(TEMP_DIR, filename)
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': temp_file_path,
                'progress_hooks': [progress_hook],
                'quiet': True,
                'no_warnings': True,
                'no_color': True,
                'logger': QuietLogger(),
                'verbose': False,
                # Add cookies options
                'cookiesfrombrowser': ('chrome',),
                'ignoreerrors': True,
                'skip_download_archive': True,
                'extractor_retries': 3,
                'socket_timeout': 30,
            }
            
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    title = sanitize_filename(info.get('title', 'audio'))
                
                # The actual file path with mp3 extension
                final_temp_path = temp_file_path + '.mp3'
                
                # Copy to static downloads directory
                static_filename = f"{title}_{timestamp}.mp3"
                static_file_path = os.path.join(DOWNLOADS_DIR, static_filename)
                
                # Copy the file
                import shutil
                shutil.copy2(final_temp_path, static_file_path)
                
                logger.debug(f"Audio download complete. Final path: {final_temp_path}")
                logger.debug(f"Copied to static path: {static_file_path}")
                
                # Store both paths and additional info for logging
                download_progress[download_id]['file_path'] = final_temp_path
                download_progress[download_id]['static_path'] = f"/static/downloads/{static_filename}"
                download_progress[download_id]['title'] = title
                download_progress[download_id]['format'] = 'mp3'
                download_progress[download_id]['platform'] = 'YouTube'
                download_progress[download_id]['url'] = url
                download_progress[download_id]['duration'] = info.get('duration_string', str(info.get('duration', 'Unknown')))
                download_progress[download_id]['description'] = info.get('description', 'No description available')
                
                # Log the download
                log_download(download_progress[download_id])
                
            except Exception as e:
                logger.error(f"Error downloading audio: {str(e)}")
                if "ffmpeg is not installed" in str(e):
                    download_progress[download_id] = {
                        'error': "FFmpeg is required for audio downloads. Please install FFmpeg or contact the administrator."
                    }
                else:
                    download_progress[download_id] = {
                        'error': str(e)
                    }
        else:
            # Download as video with specified quality
            filename = f"youtube_video_{timestamp}.mp4"
            temp_file_path = os.path.join(TEMP_DIR, filename)
            
            logger.debug(f"Video download path: {temp_file_path}")
            
            # If FFmpeg might not be available, use a simpler format string that doesn't require merging
            try:
                # First, try to check if FFmpeg is available
                import subprocess
                try:
                    subprocess.run(['ffmpeg', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
                    ffmpeg_available = True
                except (FileNotFoundError, subprocess.SubprocessError):
                    ffmpeg_available = False
                    logger.warning("FFmpeg not found, using simpler format string")
                
                # Set format based on quality and FFmpeg availability
                if quality == 'highest':
                    format_string = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best' if ffmpeg_available else 'best[ext=mp4]/best'
                elif quality == '720p':
                    format_string = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]' if ffmpeg_available else 'best[height<=720][ext=mp4]/best[height<=720]'
                elif quality == '480p':
                    format_string = 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]' if ffmpeg_available else 'best[height<=480][ext=mp4]/best[height<=480]'
                elif quality == '360p':
                    format_string = 'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]/best[height<=360]' if ffmpeg_available else 'best[height<=360][ext=mp4]/best[height<=360]'
                else:
                    format_string = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best' if ffmpeg_available else 'best[ext=mp4]/best'
                
                ydl_opts = {
                    'format': format_string,
                    'outtmpl': temp_file_path,
                    'quiet': True,
                    'no_warnings': True,
                    'no_color': True,
                    'logger': QuietLogger(),
                    'verbose': False,
                    'progress_hooks': [progress_hook],
                    # Add cookies options
                    'cookiesfrombrowser': ('chrome',),  # Use Chrome cookies
                    'ignoreerrors': True,  # Continue on errors
                    'skip_download_archive': True,  # Don't use download archive
                    'extractor_retries': 3,  # Retry 3 times
                    'socket_timeout': 30,  # Increase timeout
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    title = sanitize_filename(info.get('title', 'video'))
                
                logger.debug(f"Video download complete. Path: {temp_file_path}")
                
                # Check if file exists
                if os.path.exists(temp_file_path):
                    logger.debug(f"File exists at {temp_file_path}")
                else:
                    logger.warning(f"File does not exist at {temp_file_path}")
                    # Try to find the actual file
                    dir_name = os.path.dirname(temp_file_path)
                    base_name = os.path.basename(temp_file_path)
                    for f in os.listdir(dir_name):
                        if f.startswith(base_name.split('.')[0]):
                            logger.debug(f"Found potential match: {f}")
                            temp_file_path = os.path.join(dir_name, f)
                            break
                
                # Copy to static downloads directory with the video title
                static_filename = f"{title}.mp4"
                static_file_path = os.path.join(DOWNLOADS_DIR, static_filename)
                
                # Copy the file
                import shutil
                shutil.copy2(temp_file_path, static_file_path)
                logger.debug(f"Copied to static path: {static_file_path}")
                
                # Store both paths and additional info for logging
                download_progress[download_id]['file_path'] = temp_file_path
                download_progress[download_id]['static_path'] = f"/static/downloads/{static_filename}"
                download_progress[download_id]['title'] = title
                download_progress[download_id]['format'] = 'mp4'
                download_progress[download_id]['platform'] = 'YouTube'
                download_progress[download_id]['url'] = url
                download_progress[download_id]['duration'] = info.get('duration_string', str(info.get('duration', 'Unknown')))
                download_progress[download_id]['description'] = info.get('description', 'No description available')
                
                # Log the download
                log_download(download_progress[download_id])
                
            except Exception as e:
                logger.error(f"Error downloading video: {str(e)}")
                
                # Try with a different approach if the error is related to bot detection
                if "Sign in to confirm you're not a bot" in str(e):
                    try:
                        logger.info("Trying alternative download method to bypass bot detection...")
                        
                        # Try with a different user agent and referer
                        ydl_opts = {
                            'format': 'best[ext=mp4]/best',  # Simpler format
                            'outtmpl': temp_file_path,
                            'quiet': True,
                            'no_warnings': True,
                            'no_color': True,
                            'logger': QuietLogger(),
                            'verbose': False,
                            'http_headers': {
                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                                'Referer': 'https://www.youtube.com/'
                            },
                            'cookiesfrombrowser': ('chrome',),
                            'ignoreerrors': True,
                            'skip_download_archive': True,
                            'extractor_retries': 5
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            info = ydl.extract_info(url, download=True)
                            title = sanitize_filename(info.get('title', 'video'))
                        
                        logger.debug(f"Alternative video download complete. Path: {temp_file_path}")
                        
                        # Copy to static downloads directory with the video title
                        static_filename = f"{title}.mp4"
                        static_file_path = os.path.join(DOWNLOADS_DIR, static_filename)
                        
                        # Copy the file
                        import shutil
                        shutil.copy2(temp_file_path, static_file_path)
                        logger.debug(f"Copied to static path: {static_file_path}")
                        
                        # Store both paths and additional info for logging
                        download_progress[download_id]['file_path'] = temp_file_path
                        download_progress[download_id]['static_path'] = f"/static/downloads/{static_filename}"
                        download_progress[download_id]['title'] = title
                        download_progress[download_id]['format'] = 'mp4'
                        download_progress[download_id]['platform'] = 'YouTube'
                        download_progress[download_id]['url'] = url
                        download_progress[download_id]['duration'] = info.get('duration_string', str(info.get('duration', 'Unknown')))
                        download_progress[download_id]['description'] = info.get('description', 'No description available')
                        logger.debug(f"Updated download_progress for alternative video: {download_progress[download_id]}")
                        
                    except Exception as alt_error:
                        logger.error(f"Alternative download method failed: {str(alt_error)}")
                        download_progress[download_id] = {
                            'error': "YouTube has detected automated access. Please try a different video or try again later."
                        }
                elif "ffmpeg is not installed" in str(e) or "ffmpeg not found" in str(e):
                    # If FFmpeg error occurs, try again with a simpler format that doesn't require merging
                    logger.debug("Trying simpler format due to FFmpeg error")
                    ydl_opts = {
                        'format': 'best[ext=mp4]/best',  # Simpler format that doesn't require merging
                        'outtmpl': temp_file_path,
                        'quiet': True,
                        'no_warnings': True,
                        'no_color': True,
                        'logger': QuietLogger(),
                        'verbose': False,
                        'cookiesfrombrowser': ('chrome',)
                    }
                    
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        title = sanitize_filename(info.get('title', 'video'))
                    
                    logger.debug(f"Fallback video download complete. Path: {temp_file_path}")
                    
                    # Copy to static downloads directory with the video title
                    static_filename = f"{title}.mp4"
                    static_file_path = os.path.join(DOWNLOADS_DIR, static_filename)
                    
                    # Copy the file
                    import shutil
                    shutil.copy2(temp_file_path, static_file_path)
                    logger.debug(f"Copied to static path: {static_file_path}")
                    
                    # Store both paths and additional info for logging
                    download_progress[download_id]['file_path'] = temp_file_path
                    download_progress[download_id]['static_path'] = f"/static/downloads/{static_filename}"
                    download_progress[download_id]['title'] = title
                    download_progress[download_id]['format'] = 'mp4'
                    download_progress[download_id]['platform'] = 'YouTube'
                    download_progress[download_id]['url'] = url
                    download_progress[download_id]['duration'] = info.get('duration_string', str(info.get('duration', 'Unknown')))
                    download_progress[download_id]['description'] = info.get('description', 'No description available')
                    logger.debug(f"Updated download_progress for fallback video: {download_progress[download_id]}")
                else:
                    download_progress[download_id] = {
                        'error': str(e)
                    }
                    logger.error(f"Set error in download_progress: {str(e)}")
        
        # At the very end of the function, after all processing is done:
        # Ensure the progress is marked as 100% complete
        if download_id in download_progress:
            download_progress[download_id]['percent'] = 100
            download_progress[download_id]['status'] = 'complete'
            logger.debug(f"Final update - marked download as complete: {download_id}")
    
    except Exception as e:
        logger.error(f"General error in download_youtube_with_progress: {str(e)}")
        download_progress[download_id] = {
            'error': f"YouTube download error: {str(e)}"
        }

# Endpoint to get the download file after progress is complete
@app.route('/get_file/<download_id>')
def get_file(download_id):
    print(f"Getting file for download_id: {download_id}")
    
    if download_id not in download_progress:
        print(f"Download ID {download_id} not found in download_progress")
        return jsonify({"error": "Download not found"}), 404
    
    download_info = download_progress[download_id]
    print(f"Download info: {download_info}")
    
    if 'error' in download_info:
        return jsonify({"error": download_info['error']}), 500
    
    if 'file_path' not in download_info:
        return jsonify({"error": "Download not complete"}), 400
    
    file_path = download_info['file_path']
    title = download_info.get('title', 'download')
    format_ext = download_info.get('format', 'mp4')
    
    print(f"Sending file: {file_path}, title: {title}, format: {format_ext}")
    
    # Check if file exists
    if not os.path.exists(file_path):
        print(f"File not found at {file_path}")
        return jsonify({"error": f"File not found at {file_path}"}), 404
    
    try:
        return send_file(
            file_path, 
            as_attachment=True, 
            download_name=f"{title}.{format_ext}",
            mimetype='video/mp4' if format_ext == 'mp4' else 'audio/mp3'
        )
    except Exception as e:
        print(f"Error sending file: {str(e)}")
        return jsonify({"error": f"Error sending file: {str(e)}"}), 500

def download_instagram(url):
    try:
        # Generate a download ID
        download_id = f"ig_{int(time.time())}"
        
        # Initialize progress tracking
        download_progress[download_id] = {
            'percent': 0,
            'speed': 0,
            'eta': 0,
            'status': 'starting'
        }
        
        # Return the download ID first
        response = {
            "download_id": download_id,
            "status": "started",
            "message": "Download started. Please wait..."
        }
        
        # Start download in background
        threading.Thread(target=download_instagram_with_progress, 
                        args=(url, download_id)).start()
        
        return jsonify(response)
    
    except Exception as e:
        return jsonify({"error": f"Instagram download error: {str(e)}"}), 500

def download_instagram_with_progress(url, download_id):
    """Download Instagram video with progress tracking"""
    try:
        # Create a unique filename
        timestamp = int(time.time())
        filename = f"instagram_video_{timestamp}.mp4"
        temp_file_path = os.path.join(TEMP_DIR, filename)
        
        logger.debug(f"Instagram download path: {temp_file_path}")
        
        # Use yt-dlp to download Instagram video
        ydl_opts = {
            'format': 'best',
            'outtmpl': temp_file_path,
            'quiet': True,
            'no_warnings': True,
            'no_color': True,
            'logger': QuietLogger(),
            'verbose': False,
            'progress_hooks': [progress_hook],
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = sanitize_filename(info.get('title', 'Instagram Video'))
                
            logger.debug(f"Instagram download complete. Path: {temp_file_path}")
            
            # Copy to static downloads directory with the video title
            static_filename = f"{title}.mp4"
            static_file_path = os.path.join(DOWNLOADS_DIR, static_filename)
            
            # Copy the file
            import shutil
            shutil.copy2(temp_file_path, static_file_path)
            logger.debug(f"Copied to static path: {static_file_path}")
            
            # Store both paths and additional info for logging
            download_progress[download_id]['file_path'] = temp_file_path
            download_progress[download_id]['static_path'] = f"/static/downloads/{static_filename}"
            download_progress[download_id]['title'] = title
            download_progress[download_id]['format'] = 'mp4'
            download_progress[download_id]['platform'] = 'Instagram'
            download_progress[download_id]['url'] = url
            download_progress[download_id]['duration'] = info.get('duration_string', str(info.get('duration', 'Unknown')))
            download_progress[download_id]['description'] = info.get('description', 'No description available')
            download_progress[download_id]['percent'] = 100
            
            # Log the download
            log_download(download_progress[download_id])
            
        except Exception as e:
            logger.error(f"Error downloading Instagram video: {str(e)}")
            download_progress[download_id] = {
                "error": f"Could not download Instagram video: {str(e)}",
                "alternatives": [
                    "1. Use a browser extension like 'Video DownloadHelper'",
                    "2. Try an online service like savefrom.net",
                    "3. Use the Instagram app to save videos directly"
                ]
            }
    
    except Exception as e:
        logger.error(f"General error in download_instagram_with_progress: {str(e)}")
        download_progress[download_id] = {
            'error': f"Instagram download error: {str(e)}"
        }

def download_facebook_alternative(url):
    try:
        # Create a response with instructions
        return jsonify({
            "message": "Facebook videos cannot be downloaded directly due to Facebook's restrictions.",
            "alternatives": [
                "1. Use a browser extension like 'Video DownloadHelper'",
                "2. Try a dedicated online service like savefrom.net",
                "3. Use the Facebook app to save videos directly"
            ]
        }), 200
        
    except Exception as e:
        return jsonify({"error": f"Facebook download error: {str(e)}"}), 500

@app.route('/api/info', methods=['POST'])
def get_video_info():
    data = request.json
    url = data.get('url')
    platform = data.get('platform', 'auto')
    
    if not url:
        return jsonify({"error": "Please provide a URL"}), 400
    
    try:
        # YouTube
        if platform == 'youtube':
            try:
                with yt_dlp.YoutubeDL() as ydl:
                    info = ydl.extract_info(url, download=False)
                    
                    # Format duration
                    duration_seconds = info.get('duration')
                    if duration_seconds:
                        minutes = duration_seconds // 60
                        seconds = duration_seconds % 60
                        duration_formatted = f"{minutes:02d} minutes, {seconds:02d} seconds"
                    else:
                        duration_formatted = "Unknown duration"
                    
                    return jsonify({
                        "title": info.get('title', 'YouTube Video'),
                        "thumbnail": info.get('thumbnail'),
                        "duration": duration_formatted,
                        "description": info.get('description', 'No description available'),
                        "author": info.get('uploader', 'Unknown creator'),
                        "platform": "YouTube"
                    })
            except Exception as e:
                return jsonify({"error": f"Could not fetch YouTube video info: {str(e)}"}), 500
        
        # Instagram
        elif platform == 'instagram':
            try:
                # Extract shortcode from URL with a more flexible regex
                match = re.search(r'instagram\.com/(?:p|reel|tv)/([^/?]+)', url)
                if not match:
                    return jsonify({"error": "Invalid Instagram URL. Please use a direct post or reel link."}), 400
                    
                shortcode = match.group(1)
                
                # Try to get info using yt-dlp first (more reliable for public content)
                try:
                    with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                        info = ydl.extract_info(url, download=False)
                        
                        # Format duration if available
                        duration_seconds = info.get('duration')
                        if duration_seconds:
                            minutes = duration_seconds // 60
                            seconds = duration_seconds % 60
                            duration_formatted = f"{minutes:02d} minutes, {seconds:02d} seconds"
                        else:
                            duration_formatted = "Unknown duration"
                        
                        return jsonify({
                            "title": info.get('title', 'Instagram Video'),
                            "thumbnail": info.get('thumbnail'),
                            "duration": duration_formatted,
                            "description": info.get('description', 'No description available'),
                            "author": info.get('uploader', 'Unknown creator'),
                            "platform": "Instagram",
                            "is_video": True
                        })
                except Exception as e:
                    # Fallback to Instaloader
                    L = instaloader.Instaloader()
                    
                    # Get post info
                    try:
                        post = instaloader.Post.from_shortcode(L.context, shortcode)
                        
                        return jsonify({
                            "title": f"Instagram post by {post.owner_username}",
                            "thumbnail": post.url,
                            "author": post.owner_username,
                            "platform": "Instagram",
                            "is_video": post.is_video,
                            "description": post.caption if post.caption else "No description available"
                        })
                    except Exception as insta_error:
                        return jsonify({
                            "title": "Instagram Content",
                            "platform": "Instagram",
                            "note": "Limited information available without authentication",
                            "thumbnail": f"https://www.instagram.com/p/{shortcode}/media/?size=l"
                        })
            except Exception as e:
                return jsonify({"error": f"Instagram info error: {str(e)}"}), 500
        
        # Facebook
        elif platform == 'facebook':
            return jsonify({
                "title": "Facebook Video",
                "platform": "Facebook",
                "note": "Facebook videos require alternative download methods",
                "alternatives": [
                    "Use a browser extension",
                    "Try an online service",
                    "Use the Facebook app"
                ]
            })
        
        else:
            return jsonify({"error": "Unsupported platform. Please use YouTube, Instagram, or Facebook URL"}), 400
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Check for FFmpeg at startup
import subprocess
try:
    subprocess.run(['ffmpeg', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    print("FFmpeg found - full functionality available")
except (FileNotFoundError, subprocess.SubprocessError):
    print("WARNING: FFmpeg not found. Some download features may be limited.")
    print("Install FFmpeg for full functionality:")
    print("  - Ubuntu/Debian: sudo apt install ffmpeg")
    print("  - macOS: brew install ffmpeg")
    print("  - Windows: Download from https://ffmpeg.org/download.html")

@app.route('/direct_download/<download_id>')
def direct_download(download_id):
    if download_id not in download_progress:
        return jsonify({"error": "Download not found"}), 404
    
    download_info = download_progress[download_id]
    
    if 'error' in download_info:
        return jsonify({"error": download_info['error']}), 500
    
    if 'static_path' not in download_info:
        return jsonify({"error": "Download not complete"}), 400
    
    # Ensure title is sanitized
    title = sanitize_filename(download_info.get('title', 'download'))
    
    # Return the static path for direct download
    return jsonify({
        "title": title,
        "format": download_info.get('format', 'mp4'),
        "download_url": download_info['static_path']
    })

@app.route('/fallback_download/<download_id>')
def fallback_download(download_id):
    """Fallback download method that doesn't use send_file"""
    if download_id not in download_progress:
        return jsonify({"error": "Download not found"}), 404
    
    download_info = download_progress[download_id]
    
    if 'error' in download_info:
        return jsonify({"error": download_info['error']}), 500
    
    if 'file_path' not in download_info:
        return jsonify({"error": "Download not complete"}), 400
    
    file_path = download_info['file_path']
    title = download_info.get('title', 'download')
    format_ext = download_info.get('format', 'mp4')
    
    # Check if file exists
    if not os.path.exists(file_path):
        return jsonify({"error": f"File not found at {file_path}"}), 404
    
    # Read the file and return it as a response
    try:
        with open(file_path, 'rb') as f:
            file_data = f.read()
        
        response = Response(file_data, 
                           mimetype='video/mp4' if format_ext == 'mp4' else 'audio/mp3')
        response.headers['Content-Disposition'] = f'attachment; filename="{title}.{format_ext}"'
        return response
    except Exception as e:
        logger.error(f"Error in fallback_download: {str(e)}")
        return jsonify({"error": f"Error sending file: {str(e)}"}), 500

# Serve static files
@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

@app.route('/check_download/<download_id>')
def check_download(download_id):
    """Debug endpoint to check download status"""
    if download_id not in download_progress:
        return jsonify({"error": "Download not found"}), 404
    
    return jsonify({
        "status": "found",
        "download_info": download_progress[download_id]
    })

def sanitize_filename(filename):
    """Sanitize a filename to remove invalid characters"""
    if not filename:
        return "download"
        
    # Replace invalid characters with underscore
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    # Replace multiple spaces with single space
    filename = ' '.join(filename.split())
    
    # Replace special characters that might cause issues
    filename = filename.replace('&', 'and')
    filename = filename.replace('#', '')
    filename = filename.replace('%', '')
    filename = filename.replace('$', '')
    filename = filename.replace('@', '')
    filename = filename.replace('!', '')
    filename = filename.replace('+', '_plus_')
    
    # Limit length
    if len(filename) > 100:
        filename = filename[:97] + '...'
    
    return filename.strip()

def log_download(download_info):
    """Log successful download to a file in a simple format"""
    try:
        # Get current date and time
        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        
        # Create log file path (one file per day)
        log_file = os.path.join(LOGS_DIR, f"downloads_{date_str}.log")
        
        # Get file size if available
        file_path = download_info.get('file_path', '')
        file_size = "Unknown"
        if file_path and os.path.exists(file_path):
            size_bytes = os.path.getsize(file_path)
            if size_bytes < 1024:
                file_size = f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                file_size = f"{size_bytes/1024:.2f} KB"
            elif size_bytes < 1024 * 1024 * 1024:
                file_size = f"{size_bytes/(1024*1024):.2f} MB"
            else:
                file_size = f"{size_bytes/(1024*1024*1024):.2f} GB"
        
        # Format log entry in a simple format
        title = download_info.get('title', 'Unknown')
        duration = download_info.get('duration', 'Unknown')
        platform = download_info.get('platform', 'Unknown')
        datetime_str = f"{date_str} {time_str}"
        
        # Format the log entry as a simple text
        log_entry = f"""Download at {datetime_str}
Title: {title}
Duration: {duration}
Platform: {platform}
Size: {file_size}
-----------------------------------------
"""
        
        # Write to log file
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
            
        return True
    except Exception as e:
        logger.error(f"Error logging download: {str(e)}")
        return False

if __name__ == '__main__':
    from gunicorn.app.wsgiapp import run
        run()
