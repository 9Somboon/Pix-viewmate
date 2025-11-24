import os
import threading
import time
import logging
import requests
from PyQt6.QtCore import QThread, pyqtSignal
from utilities import resize_and_encode_image, ask_api_about_image, detect_api_type
from concurrent.futures import ThreadPoolExecutor, as_completed

# ตั้งค่า logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class FilterWorker(QThread):
    progress_update = pyqtSignal(str)
    image_matched = pyqtSignal(str)
    processing_finished = pyqtSignal(list)
    show_processing_preview = pyqtSignal(str)
    progress_info = pyqtSignal(int, int, float)  # current, total, eta_seconds

    def __init__(self, folder_path, user_prompt, api_url, model_name, include_subfolders, temp, file_type="both", max_workers=4, app_ref=None, api_type="unknown"):
        super().__init__()
        self.folder_path = folder_path
        self.user_prompt = user_prompt
        self.api_url = api_url
        self.model_name = model_name
        self.include_subfolders = include_subfolders
        self.temp = temp
        self.file_type = file_type
        self.max_workers = max_workers
        self.api_type = api_type
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._stop_event = threading.Event()
        self.app_ref = app_ref
        self.session = requests.Session()
        logger.debug("FilterWorker initialized")

    def pause(self):
        self._pause_event.clear()
        logger.debug("Worker paused")

    def resume(self):
        self._pause_event.set()
        logger.debug("Worker resumed")

    def stop(self):
        self._stop_event.set()
        self._pause_event.set()  # In case it's paused
        logger.debug("Worker stop requested")

    def is_running(self):
        """Check if the worker is currently running."""
        return self.isRunning()

    def run(self):
        logger.debug("Worker started")
        matched = []
        if not os.path.isdir(self.folder_path):
            self.progress_update.emit("Error: Selected folder does not exist.")
            self.processing_finished.emit(matched)
            logger.debug("Worker finished with error: folder does not exist")
            return

        if self.file_type == "png":
            image_exts = (".png",)
        elif self.file_type == "jpg":
            image_exts = (".jpg", ".jpeg")
        else:
            image_exts = (".png", ".jpg", ".jpeg")

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
            self.processing_finished.emit(matched)
            logger.debug("Worker finished: no images found")
            return

        start_time = time.time()
        processed_count = 0

        def process_image(path):
            self._pause_event.wait()
            if self._stop_event.is_set():
                return None, None

            self.show_processing_preview.emit(path)
            img_b64 = resize_and_encode_image(path, max_size=640) # Explicitly set to 640 to match utilities default, though default is already 640
            if img_b64 is None:
                return path, False # Indicate failure but count as processed

            try:
                found = ask_api_about_image(
                    self.api_url, self.model_name, img_b64, self.user_prompt, self.temp, self.api_type, session=self.session
                )
                return path, found
            except Exception as e:
                self.progress_update.emit(f"Error processing {os.path.basename(path)}: {e}")
                return path, False

        # Create executor and submit all tasks
        executor = ThreadPoolExecutor(max_workers=self.max_workers)
        futures = {executor.submit(process_image, path): path for path in image_files}
        logger.debug(f"Submitted {len(futures)} tasks to executor")

        try:
            for future in as_completed(futures):
                if self._stop_event.is_set():
                    self.progress_update.emit("Stopping workers...")
                    # Cancel all pending futures
                    for f in futures:
                        f.cancel()
                    break
                
                path, found = future.result()
                processed_count += 1
                filename = os.path.basename(path)

                elapsed_time = time.time() - start_time
                eta_seconds = (elapsed_time / processed_count) * (total - processed_count) if processed_count > 0 else 0
                self.progress_info.emit(processed_count, total, eta_seconds)
                
                if found:
                    matched.append(path)
                    self.image_matched.emit(path)
                    self.progress_update.emit(f"Found: {filename}")
                else:
                    self.progress_update.emit(f"Not found: {filename}")
        finally:
            # Properly shutdown the executor
            logger.debug("Shutting down executor")
            executor.shutdown(wait=True)
            self.session.close() # Close the session
            logger.debug("Executor shutdown complete and session closed")

        if self._stop_event.is_set():
            self.progress_update.emit("Stopped by user.")
        self.processing_finished.emit(matched)
        logger.debug(f"Worker finished. Matched {len(matched)} images")