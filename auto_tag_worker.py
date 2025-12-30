# Auto-Tag Worker
# Background worker for auto-tagging images with AI-generated keywords

import os
import threading
import time
import logging
import base64
import requests
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt6.QtCore import QThread, pyqtSignal
from PIL import Image
from config import OLLAMA_HOST, VISION_MODEL, MAX_IMAGE_SIZE
from utilities import read_existing_keywords, embed_keywords_in_exif

# Setup logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def resize_and_encode_for_tagging(image_path: str, max_size: int = MAX_IMAGE_SIZE) -> str | None:
    """
    Resize and encode image to base64 for sending to Ollama.
    """
    try:
        with Image.open(image_path) as img:
            # Convert to RGB if necessary
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            # Resize maintaining aspect ratio
            img.thumbnail((max_size, max_size))
            
            # Save to buffer as JPEG
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=85)
            
            # Encode to base64
            return base64.b64encode(buffer.getvalue()).decode('utf-8')
    except Exception as e:
        logger.error(f"Error processing image {image_path}: {e}")
        return None


def generate_tags_from_image(image_base64: str, num_keywords: int = 20, 
                             ollama_host: str = OLLAMA_HOST, 
                             model: str = VISION_MODEL) -> list[str]:
    """
    Send image to Ollama Vision model and get keyword tags.
    """
    url = f"{ollama_host.rstrip('/')}/api/generate"
    
    prompt = f"""Analyze this image and generate exactly {num_keywords} relevant English keywords for stock photography.
Focus on: objects, subjects, colors, mood, style, concepts.
Return ONLY a comma-separated list of single-word or two-word keywords.
Example format: nature, forest, green, peaceful, outdoor, landscape"""
    
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [image_base64],
        "stream": False,
        "options": {"temperature": 0.3}
    }
    
    try:
        response = requests.post(url, json=payload, timeout=120)
        response.raise_for_status()
        data = response.json()
        response_text = data.get("response", "").strip()
        
        if not response_text:
            return []
        
        # Parse comma-separated keywords
        keywords = []
        for kw in response_text.split(','):
            kw = kw.strip().lower()
            # Filter out empty or too long keywords
            if kw and len(kw) <= 50:
                keywords.append(kw)
        
        return keywords[:num_keywords]  # Limit to requested number
        
    except Exception as e:
        logger.error(f"Error generating tags: {e}")
        return []


class AutoTagWorker(QThread):
    """
    Worker thread for auto-tagging images in the background.
    """
    # Signals
    progress_update = pyqtSignal(str)  # Status message
    progress_info = pyqtSignal(int, int, float)  # current, total, eta_seconds
    image_tagged = pyqtSignal(str, list)  # filepath, keywords
    tagging_finished = pyqtSignal(int, int)  # success_count, failed_count
    error_occurred = pyqtSignal(str)  # error message

    def __init__(self, image_paths: list[str], num_keywords: int = 20,
                 append_mode: bool = True, ollama_host: str = OLLAMA_HOST,
                 vision_model: str = VISION_MODEL):
        super().__init__()
        self.image_paths = image_paths
        self.num_keywords = num_keywords
        self.append_mode = append_mode
        self.ollama_host = ollama_host
        self.vision_model = vision_model
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused by default
        logger.debug(f"AutoTagWorker initialized with {len(image_paths)} images")

    def stop(self):
        """Stop the worker."""
        self._stop_event.set()
        self._pause_event.set()  # Unpause to allow clean exit
        logger.debug("AutoTagWorker stop requested")

    def pause(self):
        """Pause the worker."""
        self._pause_event.clear()
        logger.debug("AutoTagWorker paused")

    def resume(self):
        """Resume the worker."""
        self._pause_event.set()
        logger.debug("AutoTagWorker resumed")

    def is_running(self):
        """Check if worker is running."""
        return self.isRunning()

    def run(self):
        logger.debug("AutoTagWorker started")
        success_count = 0
        failed_count = 0
        
        total = len(self.image_paths)
        if total == 0:
            self.progress_update.emit("No images to tag.")
            self.tagging_finished.emit(0, 0)
            return
        
        self.progress_update.emit(f"Starting auto-tagging of {total} images...")
        start_time = time.time()
        
        for idx, filepath in enumerate(self.image_paths):
            # Check for stop request
            if self._stop_event.is_set():
                self.progress_update.emit("Tagging stopped by user.")
                break
            
            # Wait if paused
            self._pause_event.wait()
            
            filename = os.path.basename(filepath)
            self.progress_update.emit(f"Processing: {filename}")
            
            try:
                # Step 1: Resize and encode image
                img_base64 = resize_and_encode_for_tagging(filepath)
                if img_base64 is None:
                    self.progress_update.emit(f"✗ Failed to process: {filename}")
                    failed_count += 1
                    continue
                
                # Check for stop request
                if self._stop_event.is_set():
                    break
                
                # Step 2: Generate tags from Vision model
                new_keywords = generate_tags_from_image(
                    img_base64, self.num_keywords, 
                    self.ollama_host, self.vision_model
                )
                
                if not new_keywords:
                    self.progress_update.emit(f"✗ Failed to generate tags: {filename}")
                    failed_count += 1
                    continue
                
                # Step 3: Handle append mode
                if self.append_mode:
                    existing_keywords = read_existing_keywords(filepath)
                    # Merge keywords, removing duplicates
                    all_keywords = list(set(existing_keywords + new_keywords))
                else:
                    all_keywords = new_keywords
                
                # Step 4: Embed keywords in EXIF/IPTC
                if embed_keywords_in_exif(filepath, all_keywords):
                    self.progress_update.emit(f"✓ Tagged: {filename} ({len(all_keywords)} keywords)")
                    self.image_tagged.emit(filepath, all_keywords)
                    success_count += 1
                else:
                    self.progress_update.emit(f"✗ Failed to save tags: {filename}")
                    failed_count += 1
                    
            except Exception as e:
                logger.error(f"Error tagging {filename}: {e}")
                self.progress_update.emit(f"✗ Error: {filename} - {str(e)}")
                failed_count += 1
            
            # Update progress
            processed = idx + 1
            elapsed = time.time() - start_time
            if processed > 0:
                eta = (elapsed / processed) * (total - processed)
            else:
                eta = 0
            
            self.progress_info.emit(processed, total, eta)
        
        # Final status
        if self._stop_event.is_set():
            self.progress_update.emit(f"Tagging stopped. Success: {success_count}, Failed: {failed_count}")
        else:
            self.progress_update.emit(f"Tagging complete. Success: {success_count}, Failed: {failed_count}")
        
        self.tagging_finished.emit(success_count, failed_count)
        logger.debug(f"AutoTagWorker finished. Success: {success_count}, Failed: {failed_count}")
