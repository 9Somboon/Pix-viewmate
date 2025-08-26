import os
import threading
import time
from PyQt6.QtCore import QThread, pyqtSignal
from utilities import resize_and_encode_image, ask_ollama_about_image
from concurrent.futures import ThreadPoolExecutor, as_completed

class FilterWorker(QThread):
    progress_update = pyqtSignal(str)
    image_matched = pyqtSignal(str)
    finished = pyqtSignal(list)
    show_processing_preview = pyqtSignal(str)
    progress_info = pyqtSignal(int, int, float)  # current, total, eta_seconds

    def __init__(self, folder_path, user_prompt, ollama_api_url, model_name, include_subfolders, temp, file_type="both", max_workers=4, app_ref=None):
        super().__init__()
        self.folder_path = folder_path
        self.user_prompt = user_prompt
        self.ollama_api_url = ollama_api_url
        self.model_name = model_name
        self.include_subfolders = include_subfolders
        self.temp = temp
        self.file_type = file_type
        self.max_workers = max_workers
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._stop_event = threading.Event()
        self.app_ref = app_ref

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    def stop(self):
        self._stop_event.set()
        self._pause_event.set()  # In case it's paused

    def run(self):
        matched = []
        if not os.path.isdir(self.folder_path):
            self.progress_update.emit("Error: Selected folder does not exist.")
            self.finished.emit(matched)
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
            self.finished.emit(matched)
            return

        start_time = time.time()
        processed_count = 0

        def process_image(path):
            self._pause_event.wait()
            if self._stop_event.is_set():
                return None, None

            self.show_processing_preview.emit(path)
            img_b64 = resize_and_encode_image(path, max_size=1024)
            if img_b64 is None:
                return path, False # Indicate failure but count as processed

            try:
                found = ask_ollama_about_image(
                    self.ollama_api_url, self.model_name, img_b64, self.user_prompt, self.temp
                )
                return path, found
            except Exception as e:
                self.progress_update.emit(f"Error processing {os.path.basename(path)}: {e}")
                return path, False

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(process_image, path): path for path in image_files}

            for future in as_completed(futures):
                if self._stop_event.is_set():
                    self.progress_update.emit("Stopping workers...")
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

        if self._stop_event.is_set():
            self.progress_update.emit("Stopped by user.")
        self.finished.emit(matched)