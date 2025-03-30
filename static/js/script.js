document.addEventListener('DOMContentLoaded', function() {
    const downloadForm = document.getElementById('downloadForm');
    const videoUrl = document.getElementById('videoUrl');
    const videoInfo = document.getElementById('videoInfo');
    const infoContent = document.getElementById('infoContent');
    const loader = document.getElementById('loader');
    const videoThumbnail = document.getElementById('videoThumbnail');
    const videoTitle = document.getElementById('videoTitle');
    const videoAuthor = document.getElementById('videoAuthor');
    const videoPlatform = document.getElementById('videoPlatform');
    const qualitySelect = document.getElementById('qualitySelect');
    const qualityOptions = document.getElementById('qualityOptions');
    const downloadBtn = document.getElementById('downloadBtn');
    const downloadProgress = document.getElementById('downloadProgress');
    const progressBar = document.getElementById('progressBar');
    const progressText = document.getElementById('progressText');
    const progressDetails = document.getElementById('progressDetails');
    const errorMessage = document.getElementById('errorMessage');
    const errorText = document.getElementById('errorText');
    const formatBtns = document.querySelectorAll('.format-btn');
    
    let selectedFormat = 'video';
    let eventSource = null;
    
    // Format button click
    formatBtns.forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            formatBtns.forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            selectedFormat = this.dataset.format;
            
            // Show/hide quality options based on format
            if (selectedFormat === 'audio') {
                qualityOptions.style.display = 'none';
            } else {
                qualityOptions.style.display = 'flex';
            }
        });
    });
    
    // Form submission
    downloadForm.addEventListener('submit', function(e) {
        e.preventDefault();
        
        const url = videoUrl.value.trim();
        
        if (!url) {
            showError('Please enter a valid URL');
            return;
        }
        
        // Hide any previous error
        hideError();
        
        // Show video info section with loader
        videoInfo.classList.remove('hidden');
        infoContent.style.display = 'none';
        loader.style.display = 'flex';
        
        // Fetch video info
        fetchVideoInfo(url);
    });
    
    // Download button click
    downloadBtn.addEventListener('click', function() {
        const url = videoUrl.value.trim();
        
        if (!url) {
            showError('Please enter a valid URL');
            return;
        }
        
        // Hide video info and show progress
        videoInfo.classList.add('hidden');
        downloadProgress.classList.remove('hidden');
        
        // Reset progress
        updateProgress(0, 'Starting...', 'Calculating...');
        
        // Start download with progress tracking
        startDownload(url);
    });
    
    // Fetch video info
    function fetchVideoInfo(url) {
        // Auto-detect platform
        let platform;
        if (url.includes('youtube.com') || url.includes('youtu.be')) {
            platform = 'youtube';
        } else if (url.includes('instagram.com') || url.includes('instagr.am')) {
            platform = 'instagram';
        } else if (url.includes('facebook.com') || url.includes('fb.com') || url.includes('fb.watch')) {
            platform = 'facebook';
        } else {
            showError('Unsupported URL. Please use YouTube, Instagram, or Facebook URL.');
            videoInfo.classList.add('hidden');
            return;
        }
        
        // Highlight the detected platform
        highlightPlatform(platform);
        
        fetch('/api/info', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ url: url, platform: platform })
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                showError(data.error);
                videoInfo.classList.add('hidden');
                return;
            }
            
            // Update video info
            videoTitle.textContent = data.title || 'No video title';
            videoAuthor.textContent = data.author || 'Unknown creator';
            videoPlatform.textContent = data.platform || '';
            
            // Remove description if it exists
            const descriptionElem = document.getElementById('videoDescription');
            if (descriptionElem) {
                descriptionElem.parentNode.removeChild(descriptionElem);
            }
            
            // Add duration if available
            if (data.duration) {
                let formattedDuration = '';
                if (typeof data.duration === 'number') {
                    const minutes = Math.floor(data.duration / 60);
                    const seconds = data.duration % 60;
                    formattedDuration = `${minutes.toString().padStart(2, '0')} minutes, ${seconds.toString().padStart(2, '0')} seconds`;
                } else {
                    formattedDuration = data.duration;
                }
                
                if (document.getElementById('videoDuration')) {
                    document.getElementById('videoDuration').textContent = `Duration: ${formattedDuration}`;
                } else {
                    // Create duration element if it doesn't exist
                    const durationElem = document.createElement('p');
                    durationElem.id = 'videoDuration';
                    durationElem.textContent = `Duration: ${formattedDuration}`;
                    
                    // Add after author
                    videoAuthor.parentNode.insertBefore(durationElem, videoAuthor.nextSibling);
                }
            }
            
            if (data.thumbnail) {
                videoThumbnail.src = data.thumbnail;
                videoThumbnail.style.display = 'block';
                document.getElementById('instagramPlaceholder').style.display = 'none';
            } else if (platform === 'instagram') {
                // For Instagram, show a placeholder
                videoThumbnail.style.display = 'none';
                document.getElementById('instagramPlaceholder').style.display = 'flex';
            } else {
                videoThumbnail.style.display = 'none';
                document.getElementById('instagramPlaceholder').style.display = 'none';
            }
            
            // Show/hide quality options based on platform
            if (platform === 'youtube') {
                document.getElementById('qualityOptions').style.display = 'flex';
            } else {
                document.getElementById('qualityOptions').style.display = 'none';
            }
            
            // Show info content, hide loader
            loader.style.display = 'none';
            infoContent.style.display = 'flex';
            
            // If platform is Facebook, show alternatives
            if (platform === 'facebook' && data.alternatives) {
                const alternativesDiv = document.createElement('div');
                alternativesDiv.className = 'alternatives';
                alternativesDiv.innerHTML = '<h4>Alternative Methods:</h4><ul>' + 
                    data.alternatives.map(alt => `<li>${alt}</li>`).join('') + 
                    '</ul>';
                
                // Add after the download button
                downloadBtn.parentNode.insertBefore(alternativesDiv, downloadBtn.nextSibling);
            }
        })
        .catch(error => {
            showError('Failed to fetch video information. Please try again.');
            videoInfo.classList.add('hidden');
            console.error('Error:', error);
        });
    }
    
    // Start download with progress tracking
    function startDownload(url) {
        // Determine platform
        let platform;
        if (url.includes('youtube.com') || url.includes('youtu.be')) {
            platform = 'youtube';
        } else if (url.includes('instagram.com') || url.includes('instagr.am')) {
            platform = 'instagram';
        } else if (url.includes('facebook.com') || url.includes('fb.com') || url.includes('fb.watch')) {
            platform = 'facebook';
        } else {
            showError('Unsupported URL');
            downloadProgress.classList.add('hidden');
            return;
        }
        
        // Create form data
        const formData = new FormData();
        formData.append('url', url);
        formData.append('platform', platform);
        formData.append('format', selectedFormat);
        
        // Add quality for YouTube videos
        if (platform === 'youtube') {
            formData.append('quality', qualitySelect.value);
        }
        
        // For YouTube and Instagram, use SSE for progress updates
        if (platform === 'youtube' || platform === 'instagram') {
            fetch('/download', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    showError(data.error);
                    downloadProgress.classList.add('hidden');
                    return;
                }
                
                const downloadId = data.download_id;
                
                // Connect to SSE endpoint for progress updates
                if (eventSource) {
                    eventSource.close();
                }
                
                eventSource = new EventSource(`/progress/${downloadId}`);
                
                // Set a timeout to check download status if SSE fails
                const progressCheckInterval = setInterval(() => {
                    fetch(`/check_download/${downloadId}`)
                        .then(response => response.json())
                        .then(data => {
                            if (data.error) {
                                clearInterval(progressCheckInterval);
                                return;
                            }
                            
                            if (data.download_info.percent === 100 || data.download_info.status === 'complete') {
                                clearInterval(progressCheckInterval);
                                handleDownloadComplete(downloadId);
                            }
                        })
                        .catch(error => {
                            console.error('Error checking download status:', error);
                        });
                }, 5000); // Check every 5 seconds
                
                eventSource.onmessage = function(event) {
                    const progress = JSON.parse(event.data);
                    
                    // Check for errors
                    if (progress.error) {
                        eventSource.close();
                        clearInterval(progressCheckInterval);
                        showError(progress.error);
                        downloadProgress.classList.add('hidden');
                        return;
                    }
                    
                    updateProgress(progress.percent, progress.speed, progress.eta);
                    
                    // When download is complete
                    if (progress.percent === 100) {
                        eventSource.close();
                        clearInterval(progressCheckInterval);
                        handleDownloadComplete(downloadId);
                    }
                };
                
                eventSource.onerror = function() {
                    // Don't close the event source on error, let it try to reconnect
                    console.log('SSE connection error, will try to reconnect...');
                };
            })
            .catch(error => {
                showError('Failed to start download. Please try again.');
                downloadProgress.classList.add('hidden');
                console.error('Error:', error);
            });
        } else {
            // For other platforms, use the regular form submission
            fetch('/download', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    showError(data.error);
                    downloadProgress.classList.add('hidden');
                    return;
                }
                
                // For direct downloads, create a link and click it
                if (data.download_url) {
                    const link = document.createElement('a');
                    link.href = data.download_url;
                    link.download = data.filename || 'download';
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                    
                    // Hide progress after download starts
                    setTimeout(() => {
                        downloadProgress.classList.add('hidden');
                        // Show success message
                        showSuccess('Download started successfully!');
                    }, 1000);
                }
            })
            .catch(error => {
                showError('Failed to start download. Please try again.');
                downloadProgress.classList.add('hidden');
                console.error('Error:', error);
            });
        }
    }
    
    // Update progress bar and text
    function updateProgress(percent, speed, eta) {
        // Ensure percent is a number
        if (typeof percent === 'string') {
            percent = parseInt(percent, 10) || 0;
        }
        
        // Ensure percent is between 0 and 100
        percent = Math.max(0, Math.min(100, percent));
        
        // Update the UI
        progressBar.style.width = `${percent}%`;
        progressText.textContent = `${percent}%`;
        
        // Add a pulsing effect when downloading
        if (percent < 100) {
            progressBar.classList.add('downloading');
        } else {
            progressBar.classList.remove('downloading');
        }
        
        if (progressDetails) {
            progressDetails.textContent = `Speed: ${speed} | ETA: ${eta}`;
            
            // Add a small animation to show active downloading
            progressDetails.classList.add('updating');
            setTimeout(() => {
                progressDetails.classList.remove('updating');
            }, 300);
        }
        
        // Force a repaint to ensure the progress bar updates visually
        // This can help with some browser rendering issues
        progressBar.offsetHeight;
    }
    
    // Show error message
    function showError(message) {
        errorText.textContent = message;
        errorMessage.classList.remove('hidden');
    }
    
    // Hide error message
    function hideError() {
        errorMessage.classList.add('hidden');
    }
    
    // Auto-detect platform from URL when pasting
    videoUrl.addEventListener('input', function() {
        const url = this.value.trim();
        if (url.includes('youtube.com') || url.includes('youtu.be')) {
            highlightPlatform('youtube');
        } else if (url.includes('instagram.com') || url.includes('instagr.am')) {
            highlightPlatform('instagram');
        } else if (url.includes('facebook.com') || url.includes('fb.com') || url.includes('fb.watch')) {
            highlightPlatform('facebook');
        } else {
            resetPlatformHighlights();
        }
    });
    
    // Highlight the detected platform in the supported platforms section
    function highlightPlatform(platform) {
        const platforms = document.querySelectorAll('.supported-platforms span');
        platforms.forEach(p => {
            if (p.innerHTML.toLowerCase().includes(platform)) {
                p.classList.add('active');
            } else {
                p.classList.remove('active');
            }
        });
    }
    
    // Reset platform highlights
    function resetPlatformHighlights() {
        const platforms = document.querySelectorAll('.supported-platforms span');
        platforms.forEach(p => p.classList.remove('active'));
    }
    
    // Clean up event source on page unload
    window.addEventListener('beforeunload', function() {
        if (eventSource) {
            eventSource.close();
        }
    });
    
    // Function to handle download completion
    function handleDownloadComplete(downloadId) {
        // Update UI to show download is complete
        updateProgress(100, 'Complete', 'Ready for download');
        
        // Get the direct download URL
        fetch(`/direct_download/${downloadId}`)
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    // Show error in the progress container
                    const progressContainer = document.querySelector('.download-progress');
                    progressContainer.innerHTML = `
                        <h3>Download Error</h3>
                        <p class="error-text">${data.error}</p>
                        <button class="download-complete-btn secondary" id="newDownloadBtn">
                            <i class="fas fa-sync"></i> Try Again
                        </button>
                    `;
                    
                    // Add event listener to the new download button
                    document.getElementById('newDownloadBtn').addEventListener('click', resetUI);
                    return;
                }
                
                // Create a download link and click it automatically
                const downloadLink = document.createElement('a');
                downloadLink.href = data.download_url;
                downloadLink.download = `${data.title}.${data.format}`;
                document.body.appendChild(downloadLink);
                downloadLink.click();
                document.body.removeChild(downloadLink);
                
                // Show a success message
                const progressContainer = document.querySelector('.download-progress');
                progressContainer.innerHTML = `
                    <h3>Download Complete!</h3>
                    <p>Your ${data.format === 'mp3' ? 'audio' : 'video'} has been downloaded.</p>
                    <button class="download-complete-btn secondary" id="newDownloadBtn">
                        <i class="fas fa-sync"></i> New Download
                    </button>
                `;
                
                // Add event listener to the new download button
                document.getElementById('newDownloadBtn').addEventListener('click', resetUI);
            })
            .catch(error => {
                showError('Failed to get download link. Please try again.');
                console.error('Error:', error);
                
                // Show error in the progress container
                const progressContainer = document.querySelector('.download-progress');
                progressContainer.innerHTML = `
                    <h3>Download Error</h3>
                    <p class="error-text">Failed to get download link. Please try again.</p>
                    <button class="download-complete-btn secondary" id="newDownloadBtn">
                        <i class="fas fa-sync"></i> Try Again
                    </button>
                `;
                
                // Add event listener to the new download button
                document.getElementById('newDownloadBtn').addEventListener('click', resetUI);
            });
    }
    
    // Function to reset the UI to initial state
    function resetUI() {
        // Clear the URL input
        document.getElementById('videoUrl').value = '';
        
        // Hide video info and download progress sections
        document.getElementById('videoInfo').classList.add('hidden');
        document.getElementById('downloadProgress').classList.add('hidden');
        
        // Hide error message
        document.getElementById('errorMessage').classList.add('hidden');
        
        // Reset progress bar
        document.getElementById('progressBar').style.width = '0%';
        document.getElementById('progressText').textContent = '0%';
        document.getElementById('progressDetails').textContent = 'Speed: Calculating... | ETA: Calculating...';
        
        // Reset platform highlights
        resetPlatformHighlights();
        
        // Scroll to top
        window.scrollTo(0, 0);
    }
    
    // Show success message
    function showSuccess(message) {
        // Create success message element if it doesn't exist
        let successMessage = document.getElementById('successMessage');
        if (!successMessage) {
            successMessage = document.createElement('div');
            successMessage.id = 'successMessage';
            successMessage.className = 'success-message';
            document.querySelector('main').appendChild(successMessage);
        }
        
        successMessage.innerHTML = `<i class="fas fa-check-circle"></i><span>${message}</span>`;
        successMessage.classList.remove('hidden');
        
        // Hide after 5 seconds
        setTimeout(() => {
            successMessage.classList.add('hidden');
        }, 5000);
    }
}); 