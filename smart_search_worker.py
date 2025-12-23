# Smart Search Workers
# Background workers for image indexing and search operations

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
from config import OLLAMA_HOST, VISION_MODEL, EMBEDDING_MODEL, MAX_IMAGE_SIZE
import lancedb_manager

# Setup logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def resize_and_encode_image(image_path: str, max_size: int = MAX_IMAGE_SIZE) -> str | None:
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


def get_image_description(image_base64: str, ollama_host: str = OLLAMA_HOST, model: str = VISION_MODEL) -> str | None:
    """
    Send image to Ollama Vision model and get a text description.
    """
    url = f"{ollama_host.rstrip('/')}/api/generate"
    
    prompt = "Describe this image in detail in English. Focus on objects, colors, setting, and mood."
    
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
        description = data.get("response", "").strip()
        return description if description else None
    except Exception as e:
        logger.error(f"Error getting image description: {e}")
        return None


def get_text_embedding(text: str, ollama_host: str = OLLAMA_HOST, model: str = EMBEDDING_MODEL) -> list | None:
    """
    Send text to Ollama Embedding model and get a vector.
    """
    url = f"{ollama_host.rstrip('/')}/api/embed"
    
    payload = {
        "model": model,
        "input": text
    }
    
    try:
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        
        # Ollama returns embeddings in 'embeddings' array (for batch) or 'embedding' (for single)
        embeddings = data.get("embeddings")
        if embeddings and len(embeddings) > 0:
            return embeddings[0]
        
        embedding = data.get("embedding")
        if embedding:
            return embedding
            
        logger.error(f"No embedding in response: {data}")
        return None
    except Exception as e:
        logger.error(f"Error getting text embedding: {e}")
        return None


class IndexWorker(QThread):
    """
    Worker thread for indexing images in the background.
    """
    # Signals
    progress_update = pyqtSignal(str)  # Status message
    progress_info = pyqtSignal(int, int, int, float)  # current, total, skipped, eta_seconds
    indexing_finished = pyqtSignal(int, int)  # indexed_count, skipped_count
    error_occurred = pyqtSignal(str)  # error message

    def __init__(self, folder_path: str, include_subfolders: bool = True, 
                 ollama_host: str = OLLAMA_HOST):
        super().__init__()
        self.folder_path = folder_path
        self.include_subfolders = include_subfolders
        self.ollama_host = ollama_host
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused by default
        logger.debug("IndexWorker initialized")

    def stop(self):
        """Stop the worker."""
        self._stop_event.set()
        self._pause_event.set()  # Unpause to allow clean exit
        logger.debug("IndexWorker stop requested")

    def pause(self):
        """Pause the worker."""
        self._pause_event.clear()
        logger.debug("IndexWorker paused")

    def resume(self):
        """Resume the worker."""
        self._pause_event.set()
        logger.debug("IndexWorker resumed")

    def is_running(self):
        """Check if worker is running."""
        return self.isRunning()

    def run(self):
        logger.debug("IndexWorker started")
        indexed_count = 0
        skipped_count = 0
        failed_count = 0
        
        # Validate folder
        if not os.path.isdir(self.folder_path):
            self.error_occurred.emit("Selected folder does not exist.")
            self.indexing_finished.emit(0, 0)
            return
        
        # Collect image files
        image_exts = ('.png', '.jpg', '.jpeg')
        image_files = []
        
        for root, _, files in os.walk(self.folder_path):
            for f in files:
                if f.lower().endswith(image_exts):
                    image_files.append(os.path.join(root, f))
            if not self.include_subfolders:
                break
        
        total = len(image_files)
        if total == 0:
            self.progress_update.emit("No images found in the selected folder.")
            self.indexing_finished.emit(0, 0)
            return
        
        self.progress_update.emit(f"Found {total} images. Checking for already indexed files...")
        
        # First pass: Filter out already indexed files (done sequentially for accurate skip count)
        files_to_process = []
        for filepath in image_files:
            if self._stop_event.is_set():
                break
            if lancedb_manager.is_indexed(filepath):
                skipped_count += 1
            else:
                files_to_process.append(filepath)
        
        if self._stop_event.is_set():
            self.progress_update.emit("Indexing stopped by user.")
            self.indexing_finished.emit(indexed_count, skipped_count)
            return
        
        total_to_process = len(files_to_process)
        self.progress_update.emit(f"Skipped {skipped_count} already indexed. Processing {total_to_process} new images...")
        
        if total_to_process == 0:
            self.progress_update.emit(f"All images are already indexed. Skipped: {skipped_count}")
            self.indexing_finished.emit(0, skipped_count)
            return
        
        start_time = time.time()
        processed_count = 0
        
        # Thread-safe counters using locks
        lock = threading.Lock()
        
        def process_single_image(filepath: str) -> tuple:
            """
            Process a single image: resize, get description, get embedding, store.
            Returns tuple: (filepath, success, error_message)
            """
            filename = os.path.basename(filepath)
            
            try:
                # Check for stop request
                if self._stop_event.is_set():
                    return (filepath, False, "Stopped by user")
                
                # Wait if paused
                self._pause_event.wait()
                
                # Step 1: Resize and encode image
                img_base64 = resize_and_encode_image(filepath)
                if img_base64 is None:
                    return (filepath, False, "Failed to process image")
                
                # Check for stop request again
                if self._stop_event.is_set():
                    return (filepath, False, "Stopped by user")
                
                # Step 2: Get description from Vision model
                description = get_image_description(img_base64, self.ollama_host)
                if description is None:
                    return (filepath, False, "Failed to get description from Vision model")
                
                # Check for stop request again
                if self._stop_event.is_set():
                    return (filepath, False, "Stopped by user")
                
                # Step 3: Get embedding from Embedding model
                vector = get_text_embedding(description, self.ollama_host)
                if vector is None:
                    return (filepath, False, "Failed to get embedding")
                
                # Step 4: Store in LanceDB
                if lancedb_manager.add_image(filepath, description, vector):
                    return (filepath, True, None)
                else:
                    return (filepath, False, "Failed to store in database")
                    
            except Exception as e:
                logger.error(f"Error processing {filename}: {e}")
                return (filepath, False, str(e))
        
        # Use ThreadPoolExecutor for parallel processing
        max_workers = 3
        self.progress_update.emit(f"Starting parallel indexing with {max_workers} workers...")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_filepath = {
                executor.submit(process_single_image, fp): fp 
                for fp in files_to_process
            }
            
            # Process completed futures as they finish
            for future in as_completed(future_to_filepath):
                if self._stop_event.is_set():
                    # Cancel remaining futures
                    for f in future_to_filepath:
                        f.cancel()
                    break
                
                filepath, success, error_msg = future.result()
                filename = os.path.basename(filepath)
                
                with lock:
                    processed_count += 1
                    if success:
                        indexed_count += 1
                        self.progress_update.emit(f"✓ Indexed: {filename}")
                    else:
                        failed_count += 1
                        if error_msg != "Stopped by user":
                            self.progress_update.emit(f"✗ Failed: {filename} - {error_msg}")
                    
                    # Update progress
                    elapsed = time.time() - start_time
                    if processed_count > 0:
                        eta = (elapsed / processed_count) * (total_to_process - processed_count)
                    else:
                        eta = 0
                    
                    # Emit progress: current processed, total to process, skipped, eta
                    self.progress_info.emit(
                        processed_count + skipped_count,  # Show total progress
                        total,  # Total files
                        skipped_count,
                        eta
                    )
        
        # Final status
        if self._stop_event.is_set():
            self.progress_update.emit(f"Indexing stopped. Indexed: {indexed_count}, Skipped: {skipped_count}, Failed: {failed_count}")
        else:
            self.progress_update.emit(f"Indexing complete. Indexed: {indexed_count}, Skipped: {skipped_count}, Failed: {failed_count}")
        
        self.indexing_finished.emit(indexed_count, skipped_count)
        logger.debug(f"IndexWorker finished. Indexed: {indexed_count}, Skipped: {skipped_count}, Failed: {failed_count}")


class SearchWorker(QThread):
    """
    Worker thread for searching images in the background.
    """
    # Signals
    search_complete = pyqtSignal(list)  # List of result dictionaries
    search_error = pyqtSignal(str)  # Error message
    status_update = pyqtSignal(str)  # Status message

    def __init__(self, query: str, limit: int = 20, ollama_host: str = OLLAMA_HOST):
        super().__init__()
        self.query = query
        self.limit = limit
        self.ollama_host = ollama_host
        logger.debug(f"SearchWorker initialized with query: {query}")

    def run(self):
        logger.debug("SearchWorker started")
        
        if not self.query.strip():
            self.search_error.emit("Please enter a search query.")
            return
        
        self.status_update.emit("Converting query to embedding...")
        
        # Get embedding for the query
        query_vector = get_text_embedding(self.query, self.ollama_host)
        if query_vector is None:
            self.search_error.emit("Failed to process search query. Check Ollama connection.")
            return
        
        self.status_update.emit("Searching database...")
        
        # Search in LanceDB
        results = lancedb_manager.search(query_vector, self.limit)
        
        # Filter out results where the file no longer exists
        valid_results = []
        for result in results:
            if os.path.exists(result.get('filepath', '')):
                valid_results.append(result)
        
        self.status_update.emit(f"Found {len(valid_results)} matching images.")
        self.search_complete.emit(valid_results)
        logger.debug(f"SearchWorker finished with {len(valid_results)} results")
