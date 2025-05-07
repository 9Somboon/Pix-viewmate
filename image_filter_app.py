import sys
import os
import base64
import json
import requests
import threading

from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLineEdit, QLabel, QFileDialog,
                             QScrollArea, QGridLayout, QMessageBox, QCheckBox, QTabWidget, QComboBox, QSpinBox, QFormLayout)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, QThread, pyqtSignal

# --- Helper functions ---

def image_to_base64(image_path: str) -> str | None:
    try:
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        return encoded
    except Exception as e:
        print(f"Error encoding {image_path}: {e}")
        return None

def ask_ollama_about_image(ollama_api_url: str, model_name: str, image_base64: str, user_prompt_object: str, temp: float) -> bool:
    payload = {
        "model": model_name,
        "prompt": f"Analyze the provided image carefully. Does this image contain a {user_prompt_object}? Please answer with only 'YES' or 'NO'.",
        "images": [image_base64],
        "stream": False,
        "options": {"temperature": temp}
    }
    try:
        response = requests.post(
            ollama_api_url,
            json=payload,
            timeout=90
        )
        response.raise_for_status()
        data = response.json()
        answer = data.get("response", "").strip().upper()
        return "YES" in answer and "NO" not in answer
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        print(f"Ollama API error: {e}")
        return False

# --- FilterWorker QThread class ---

class FilterWorker(QThread):
    progress_update = pyqtSignal(str)
    image_matched = pyqtSignal(str)
    finished = pyqtSignal(list)
    show_processing_preview = pyqtSignal(str)

    def __init__(self, folder_path, user_prompt, ollama_api_url, model_name, include_subfolders, temp, app_ref=None):
        super().__init__()
        self.folder_path = folder_path
        self.user_prompt = user_prompt
        self.ollama_api_url = ollama_api_url
        self.model_name = model_name
        self.include_subfolders = include_subfolders
        self.temp = temp
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused initially
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

        for idx, path in enumerate(image_files, 1):
            if self._stop_event.is_set():
                self.progress_update.emit("Stopped by user.")
                break
            self._pause_event.wait()  # Block here if paused
            filename = os.path.basename(path)
            self.progress_update.emit(f"Processing {filename} ({idx}/{total})...")
            self.show_processing_preview.emit(path)
            img_b64 = image_to_base64(path)
            if img_b64 is None:
                self.progress_update.emit(f"Failed to read {filename}. Skipping.")
                continue
            try:
                found = ask_ollama_about_image(
                    self.ollama_api_url, self.model_name, img_b64, self.user_prompt, self.temp
                )
            except Exception as e:
                self.progress_update.emit(f"Error processing {filename}: {e}")
                continue
            if found:
                matched.append(path)
                self.image_matched.emit(path)
                self.progress_update.emit(f"Found '{self.user_prompt}' in {filename}.")
            else:
                self.progress_update.emit(f"Not found in {filename}.")
        self.finished.emit(matched)

# --- ImageFilterApp QWidget class ---

class ImageFilterApp(QWidget):
    OLLAMA_API_URL = "http://192.168.50.55:11434/api/generate"
    MODEL_NAME = "gemma3:4b-it-qat"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Filter with Ollama")
        self.resize(900, 700)
        self.folder_path = ""
        self.worker = None
        self.setAcceptDrops(True)  # Enable drag and drop

        # Tabs
        self.tabs = QTabWidget()
        self.main_tab = QWidget()
        self.settings_tab = QWidget()
        self.tabs.addTab(self.main_tab, "Main")
        self.tabs.addTab(self.settings_tab, "Settings")

        # Main tab layout
        main_layout = QVBoxLayout(self.main_tab)
        top_layout = QHBoxLayout()
        prompt_layout = QHBoxLayout()

        # Folder selection
        self.browse_btn = QPushButton("Browse Folder")
        self.browse_btn.clicked.connect(self.browse_folder)
        self.folder_label = QLabel("No folder selected")
        self.folder_label.setWordWrap(True)
        top_layout.addWidget(self.browse_btn)
        top_layout.addWidget(self.folder_label)

        # Include subfolders checkbox
        self.include_subfolder_checkbox = QCheckBox("Include Subfolders")
        self.include_subfolder_checkbox.setChecked(False)
        top_layout.addWidget(self.include_subfolder_checkbox)

        # Prompt input
        self.prompt_edit = QLineEdit()
        self.prompt_edit.setPlaceholderText("Enter prompt (e.g., 'a photo of a cat')")
        self.filter_btn = QPushButton("Filter Images")
        self.filter_btn.clicked.connect(self.start_filtering)
        prompt_layout.addWidget(QLabel("Prompt:"))
        prompt_layout.addWidget(self.prompt_edit)
        prompt_layout.addWidget(self.filter_btn)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self.toggle_pause_resume)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_filtering)
        prompt_layout.addWidget(self.pause_btn)
        prompt_layout.addWidget(self.stop_btn)

        # Status label and preview
        status_preview_layout = QHBoxLayout()
        self.status_label = QLabel("Ready.")
        self.status_label.setWordWrap(True)
        self.processing_preview_label = QLabel()
        self.processing_preview_label.setFixedSize(64, 64)
        status_preview_layout.addWidget(self.status_label)
        status_preview_layout.addWidget(self.processing_preview_label)

        # Scroll area for thumbnails
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.thumbs_widget = QWidget()
        self.grid_layout = QGridLayout()
        self.thumbs_widget.setLayout(self.grid_layout)
        self.scroll_area.setWidget(self.thumbs_widget)

        # Assemble main tab
        main_layout.addLayout(top_layout)
        main_layout.addLayout(prompt_layout)
        main_layout.addLayout(status_preview_layout)
        main_layout.addWidget(self.scroll_area)

        # Settings tab layout
        settings_layout = QFormLayout(self.settings_tab)
        self.ollama_url_edit = QLineEdit(self.OLLAMA_API_URL)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(False)
        self.temp_spin = QSpinBox()
        self.temp_spin.setRange(0, 100)
        self.temp_spin.setValue(0)
        self.temp_spin.setSuffix(" / 100")
        settings_layout.addRow("Ollama URL:", self.ollama_url_edit)
        settings_layout.addRow("Model:", self.model_combo)
        settings_layout.addRow("Temperature:", self.temp_spin)

        # Main layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        self.setLayout(layout)

        self.fetch_ollama_models()

    def fetch_ollama_models(self):
        def fetch():
            url = self.ollama_url_edit.text().rstrip("/") + "/api/tags"
            try:
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                models = [m['name'] for m in data.get('models', [])]
                self.model_combo.clear()
                self.model_combo.addItems(models)
                if self.MODEL_NAME in models:
                    self.model_combo.setCurrentText(self.MODEL_NAME)
            except Exception as e:
                self.model_combo.clear()
                self.model_combo.addItem("(fetch failed)")
        threading.Thread(target=fetch, daemon=True).start()

    def dragEnterEvent(self, event):
        if (event.mimeData().hasUrls()):
            # Accept only if at least one is a directory
            for url in event.mimeData().urls():
                local_path = url.toLocalFile()
                if os.path.isdir(local_path):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            local_path = url.toLocalFile()
            if os.path.isdir(local_path):
                self.folder_path = local_path
                self.folder_label.setText(local_path)
                break

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Image Folder")
        if folder:
            self.folder_path = folder
            self.folder_label.setText(folder)
        else:
            self.folder_label.setText("No folder selected")

    def start_filtering(self):
        prompt = self.prompt_edit.text().strip()
        if not self.folder_path or not os.path.isdir(self.folder_path):
            QMessageBox.warning(self, "No Folder", "Please select a valid folder containing images.")
            return
        if not prompt:
            QMessageBox.warning(self, "No Prompt", "Please enter a prompt.")
            return
        include_subfolders = self.include_subfolder_checkbox.isChecked()
        temp = 0.0  # ใช้ค่า temperature คงที่

        # Clear previous thumbnails
        for i in reversed(range(self.grid_layout.count())):
            widget = self.grid_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        self.filter_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self.pause_btn.setText("Pause")
        self.status_label.setText("Starting filtering...")

        self.worker = FilterWorker(
            self.folder_path, prompt, self.OLLAMA_API_URL, self.MODEL_NAME, include_subfolders, temp
        )
        self.worker.progress_update.connect(self.update_status_and_log)
        self.worker.image_matched.connect(self.add_matched_image_to_display)
        self.worker.finished.connect(self.filtering_finished)
        self.worker.show_processing_preview.connect(self.show_processing_preview)
        self.worker.start()

    def toggle_pause_resume(self):
        if not self.worker:
            return
        if self.pause_btn.text() == "Pause":
            self.worker.pause()
            self.pause_btn.setText("Resume")
            self.status_label.setText("Paused.")
        else:
            self.worker.resume()
            self.pause_btn.setText("Pause")
            self.status_label.setText("Resumed.")

    def stop_filtering(self):
        if self.worker:
            self.worker.stop()
            self.status_label.setText("Stopping...")
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)

    def update_status_and_log(self, message: str):
        self.status_label.setText(message)
        print(message)

    def add_matched_image_to_display(self, image_path: str):
        label = QLabel()
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            pixmap = pixmap.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            label.setPixmap(pixmap)
            label.setFixedSize(256, 256)
        else:
            label.setText("Failed to load image")
        idx = self.grid_layout.count()
        r, c = divmod(idx, 4)
        self.grid_layout.addWidget(label, r, c)

    def show_processing_preview(self, image_path: str):
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            pixmap = pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.processing_preview_label.setPixmap(pixmap)
        else:
            self.processing_preview_label.clear()

    def filtering_finished(self, matched_paths: list):
        n = len(matched_paths)
        self.status_label.setText(f"Finished. Found {n} image(s).")
        self.filter_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        if n == 0:
            QMessageBox.information(self, "No Matches", "No images matched the prompt.")
        self.worker = None

# --- Main execution block ---

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = ImageFilterApp()
    window.show()
    sys.exit(app.exec())
