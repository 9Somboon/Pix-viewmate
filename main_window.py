import sys
import os
import threading
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLineEdit, QLabel, QFileDialog,
                             QScrollArea, QGridLayout, QMessageBox, QCheckBox, QTabWidget, QComboBox, QSpinBox, QFormLayout, QProgressBar, QSlider)
from PyQt6.QtGui import QPixmap, QCloseEvent
from PyQt6.QtCore import Qt
from worker import FilterWorker
import requests
from clickable_image_label import ClickableImageLabel

class ImageFilterApp(QWidget):
    OLLAMA_API_URL = "http://192.168.50.55:11434"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Filter with Ollama")
        self.resize(900, 700)
        self.folder_path = ""
        self.worker = None
        self.setAcceptDrops(True)  # Enable drag and drop
        self.selected_images = []  # List to store selected image paths

        # Set default theme to dark
        self.dark_theme = True

        # Tabs
        self.tabs = QTabWidget()
        self.main_tab = QWidget()
        self.settings_tab = QWidget()
        self.tabs.addTab(self.main_tab, "Main")
        self.tabs.addTab(self.settings_tab, "Settings")

        # Main tab layout
        main_layout = QVBoxLayout(self.main_tab)
        main_layout.setContentsMargins(20, 20, 20, 20)  # เพิ่ม margin ให้กับ main layout
        main_layout.setSpacing(15)  # เพิ่ม spacing ระหว่าง layout ต่างๆ
        top_layout = QHBoxLayout()
        top_layout.setSpacing(10)  # เพิ่ม spacing ภายใน top layout
        prompt_layout = QHBoxLayout()
        prompt_layout.setSpacing(5)  # เพิ่ม spacing ภายใน prompt layout

        # Folder selection
        self.browse_btn = QPushButton("Browse Folder")
        self.browse_btn.clicked.connect(self.browse_folder)
        self.folder_label = QLabel("No folder selected")
        self.folder_label.setWordWrap(True)
        self.folder_label.setMinimumWidth(200)  # กำหนดความกว้างขั้นต่ำให้ folder label
        top_layout.addWidget(self.browse_btn)
        top_layout.addWidget(self.folder_label)

        # Include subfolders checkbox
        self.include_subfolder_checkbox = QCheckBox("Include Subfolders")
        self.include_subfolder_checkbox.setChecked(False)
        
        # File type selection
        self.file_type_label = QLabel("File Type:")
        self.png_checkbox = QCheckBox("PNG")
        self.jpg_checkbox = QCheckBox("JPG")
        # By default, both are checked
        self.png_checkbox.setChecked(True)
        self.jpg_checkbox.setChecked(True)
        
        # Theme toggle button
        self.theme_toggle_btn = QPushButton("🌞")  # Sun emoji for light theme
        self.theme_toggle_btn.setFixedSize(30, 30)
        self.theme_toggle_btn.clicked.connect(self.toggle_theme)
        
        # Set default theme to dark
        self.toggle_theme()
        
        top_layout.addWidget(self.include_subfolder_checkbox)
        top_layout.addSpacing(20)  # เพิ่มระยะห่างระหว่าง include subfolder และ file type
        top_layout.addWidget(self.file_type_label)
        top_layout.addWidget(self.png_checkbox)
        top_layout.addWidget(self.jpg_checkbox)
        top_layout.addStretch()  # เพิ่ม stretcher เพื่อผลัก theme toggle button ไปทางขวา
        top_layout.addWidget(self.theme_toggle_btn)

        # Prompt input
        self.prompt_edit = QLineEdit()
        self.prompt_edit.setPlaceholderText("Enter prompt (e.g., 'a photo of a cat')")
        self.prompt_edit.setMinimumWidth(200)  # กำหนดความกว้างขั้นต่ำให้ prompt edit
        self.filter_btn = QPushButton("Filter Images")
        self.filter_btn.clicked.connect(self.start_filtering)
        prompt_layout.addWidget(QLabel("Prompt:"))
        prompt_layout.addWidget(self.prompt_edit)
        prompt_layout.addSpacing(10)  # เพิ่มระยะห่างระหว่าง prompt input และ filter button
        prompt_layout.addWidget(self.filter_btn)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self.toggle_pause_resume)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_filtering)
        prompt_layout.addSpacing(10)  # เพิ่มระยะห่างระหว่าง filter button และ pause button
        prompt_layout.addWidget(self.pause_btn)
        prompt_layout.addSpacing(5)  # เพิ่มระยะห่างระหว่าง pause button และ stop button
        prompt_layout.addWidget(self.stop_btn)

        # Status label and preview
        status_preview_layout = QHBoxLayout()
        self.status_label = QLabel("Ready.")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("status")  # กำหนด object name ให้ status label
        self.model_label = QLabel("")  # สำหรับแสดงชื่อโมเดลปัจจุบัน
        self.model_label.setWordWrap(True)
        self.model_label.setObjectName("status")  # กำหนด object name ให้ model label
        self.processing_preview_label = QLabel()
        self.processing_preview_label.setFixedSize(64, 64)
        status_preview_layout.addWidget(self.status_label)
        status_preview_layout.addSpacing(20)  # เพิ่มระยะห่างระหว่าง status label และ model label
        status_preview_layout.addWidget(self.model_label)
        status_preview_layout.addStretch()  # เพิ่ม stretcher เพื่อผลัก processing preview ไปทางขวา
        status_preview_layout.addWidget(self.processing_preview_label)

        # Progress bar and info
        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_info_label = QLabel("")
        self.progress_info_label.setWordWrap(True)
        self.progress_info_label.setObjectName("status")  # กำหนด object name ให้ progress info label
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addSpacing(10)  # เพิ่มระยะห่างระหว่าง progress bar และ progress info label
        progress_layout.addWidget(self.progress_info_label)

        # Scroll area for thumbnails
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.thumbs_widget = QWidget()
        self.grid_layout = QGridLayout()
        self.thumbs_widget.setLayout(self.grid_layout)
        self.scroll_area.setWidget(self.thumbs_widget)

        # Slider for thumbnail size
        self.thumbnail_slider = QSlider(Qt.Orientation.Horizontal)
        self.thumbnail_slider.setMinimum(64)
        self.thumbnail_slider.setMaximum(512)
        self.thumbnail_slider.setValue(256)
        self.thumbnail_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.thumbnail_slider.setTickInterval(64)
        self.thumbnail_slider.valueChanged.connect(self.update_thumbnail_size)

        # Assemble main tab
        main_layout.addLayout(top_layout)
        main_layout.addLayout(prompt_layout)
        main_layout.addLayout(status_preview_layout)
        main_layout.addLayout(progress_layout)
        main_layout.addWidget(self.scroll_area)
        main_layout.addWidget(self.thumbnail_slider)

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

        # Max workers setting
        self.max_workers_spin = QSpinBox()
        self.max_workers_spin.setRange(1, 16)
        self.max_workers_spin.setValue(4)
        self.max_workers_spin.setSuffix(" workers")
        settings_layout.addRow("Max Concurrent Workers:", self.max_workers_spin)
        
        # Refresh model button
        self.refresh_model_btn = QPushButton("Refresh Models")
        settings_layout.addRow("", self.refresh_model_btn)

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)  # ลบ margin ของ main layout
        layout.addWidget(self.tabs)
        self.setLayout(layout)

        self.fetch_ollama_models()
        self.refresh_model_btn.clicked.connect(self.fetch_ollama_models)

    def fetch_ollama_models(self):
        print("Fetch ollama models called")
        def fetch():
            print("Fetch function started")
            base_url = self.ollama_url_edit.text().rstrip("/")
            # ตรวจสอบว่า base_url ลงท้ายด้วย /api/tags หรือไม่ ถ้าใช่ให้ตัดออก
            if base_url.endswith("/api/tags"):
                base_url = base_url[:-len("/api/tags")]
            # ตรวจสอบว่า base_url ลงท้ายด้วย /api/generate หรือไม่ ถ้าใช่ให้ตัดออก
            if base_url.endswith("/api/generate"):
                base_url = base_url[:-len("/api/generate")]
            url = base_url + "/api/tags"
            try:
                print(f"Fetching from URL: {url}")
                resp = requests.get(url, timeout=10)
                print(f"Response status code: {resp.status_code}")
                resp.raise_for_status()
                data = resp.json()
                print(f"Response data: {data}")
                models = [m['name'] for m in data.get('models', [])]
                print(f"Models: {models}")
                self.model_combo.clear()
                self.model_combo.addItems(models)
                if models:
                    # พยายามตั้งค่าโมเดลปัจจุบันถ้ามีอยู่ในลิสต์ หรือเลือกตัวแรก
                    current_model = self.model_combo.currentText()
                    if current_model and current_model in models:
                        self.model_label.setText(f"Model: {current_model}")
                    else:
                        self.model_combo.setCurrentIndex(0)
                        self.model_label.setText(f"Model: {self.model_combo.currentText()}")
            except Exception as e:
                print(f"Error fetching models: {e}")
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

        # ใช้ URL ที่ผู้ใช้ตั้งไว้ใน UI และเพิ่ม /api/generate
        ollama_base_url = self.ollama_url_edit.text().rstrip("/")
        # ตรวจสอบว่า ollama_base_url ลงท้ายด้วย /api/generate หรือไม่ ถ้าใช่ให้ตัดออก
        if ollama_base_url.endswith("/api/generate"):
            ollama_base_url = ollama_base_url[:-len("/api/generate")]
        # ตรวจสอบว่า ollama_base_url ลงท้ายด้วย /api/tags หรือไม่ ถ้าใช่ให้ตัดออก
        if ollama_base_url.endswith("/api/tags"):
            ollama_base_url = ollama_base_url[:-len("/api/tags")]
        ollama_api_url = ollama_base_url + "/api/generate"
        
        # ดึงค่าประเภทไฟล์ที่ผู้ใช้เลือก
        png_checked = self.png_checkbox.isChecked()
        jpg_checked = self.jpg_checkbox.isChecked()
        
        # กำหนดประเภทไฟล์ตามที่เลือก
        if png_checked and jpg_checked:
            file_type = "both"
        elif png_checked:
            file_type = "png"
        elif jpg_checked:
            file_type = "jpg"
        else:
            # หากไม่ได้เลือกประเภทไฟล์ใดเลย ให้แสดงข้อความแจ้งเตือน
            QMessageBox.warning(self, "No File Type", "Please select at least one file type (PNG or JPG).")
            self.filter_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            return
        
        # ดึงชื่อโมเดลที่เลือกจาก ComboBox
        selected_model = self.model_combo.currentText()
        if not selected_model or selected_model == "(fetch failed)":
            QMessageBox.warning(self, "No Model", "Please select a valid model from the Settings tab.")
            self.filter_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            return

        # อัปเดตชื่อโมเดลในแถบทดแทนสถานะ
        self.model_label.setText(f"Model: {selected_model}")
        
        max_workers = self.max_workers_spin.value()
        self.worker = FilterWorker(
            self.folder_path, prompt, ollama_api_url, selected_model, include_subfolders, temp, file_type, max_workers
        )
        self.worker.progress_update.connect(self.update_status_and_log)
        self.worker.image_matched.connect(self.add_matched_image_to_display)
        self.worker.finished.connect(self.filtering_finished)
        self.worker.show_processing_preview.connect(self.show_processing_preview)
        self.worker.progress_info.connect(self.update_progress_info)
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
            # Wait for the worker to finish (with a longer timeout)
            self.worker.wait(3000)  # Wait up to 3 seconds

    def update_status_and_log(self, message: str):
        # Prevent status label from flickering too fast during concurrent processing
        if message.startswith("Found") or message.startswith("Not found"):
             # We can just print these to the console log without updating the main status label
             print(message)
        else:
             self.status_label.setText(message)
             print(message)

    def add_matched_image_to_display(self, image_path: str):
        label = ClickableImageLabel(image_path)
        pixmap = QPixmap(image_path)
        thumbnail_size = self.thumbnail_slider.value()
        if not pixmap.isNull():
            pixmap = pixmap.scaled(thumbnail_size, thumbnail_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            label.setPixmap(pixmap)
            label.setFixedSize(thumbnail_size, thumbnail_size)
            # Connect the clicked signal
            label.clicked.connect(self.on_image_clicked)
        else:
            label.setText("Failed to load image")
        idx = self.grid_layout.count()
        # Calculate number of columns based on current thumbnail size and scroll area width
        scroll_width = self.scroll_area.viewport().width()
        padding = 10
        columns = max(1, scroll_width // (thumbnail_size + padding))
        r, c = divmod(idx, columns)
        self.grid_layout.addWidget(label, r, c)

    def show_processing_preview(self, image_path: str):
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            pixmap = pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.processing_preview_label.setPixmap(pixmap)
        else:
            self.processing_preview_label.clear()

    def update_progress_info(self, current, total, eta_seconds):
        # อัปเดต QProgressBar
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        
        # อัปเดตข้อมูลความคืบหน้า
        if eta_seconds > 0:
            # แปลงวินาทีเป็นรูปแบบอ่านง่าย
            if eta_seconds < 60:
                eta_str = f"{eta_seconds:.0f}s"
            elif eta_seconds < 3600:
                eta_str = f"{eta_seconds/60:.1f}m"
            else:
                eta_str = f"{eta_seconds/3600:.1f}h"
            self.progress_info_label.setText(f"Processed {current}/{total} files - ETA: {eta_str}")
        else:
            self.progress_info_label.setText(f"Processed {current}/{total} files")

    def filtering_finished(self, matched_paths: list):
        n = len(matched_paths)
        self.status_label.setText(f"Finished. Found {n} image(s).")
        self.filter_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        if n == 0:
            QMessageBox.information(self, "No Matches", "No images matched the prompt.")
        self.worker = None
    
    def update_thumbnail_size(self, size):
        # Update the size of all thumbnails in the grid layout
        for i in range(self.grid_layout.count()):
            widget = self.grid_layout.itemAt(i).widget()
            if isinstance(widget, ClickableImageLabel):
                # Update the pixmap with the new size using the widget's method
                widget.updatePixmapWithSize(size)
        
        # Update the grid layout
        self.update_grid_layout()

    def update_grid_layout(self):
        # Update the grid layout based on the current thumbnail size and scroll area width
        scroll_width = self.scroll_area.viewport().width()
        thumbnail_size = self.thumbnail_slider.value()
        # Calculate number of columns based on scroll area width and thumbnail size
        # Add some padding for spacing between thumbnails
        padding = 10
        columns = max(1, scroll_width // (thumbnail_size + padding))
        
        # Re-arrange all widgets in the grid layout
        widgets = []
        # Collect all widgets first
        for i in range(self.grid_layout.count()):
            widget = self.grid_layout.itemAt(i).widget()
            if widget:
                widgets.append(widget)
        
        # Clear the grid layout
        for i in reversed(range(self.grid_layout.count())):
            widget = self.grid_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        # Re-add widgets with new positions
        for i, widget in enumerate(widgets):
            row, col = divmod(i, columns)
            self.grid_layout.addWidget(widget, row, col)

    def toggle_theme(self):
        # ฟังก์ชันสำหรับสลับธีม dark/light
        if not hasattr(self, 'dark_theme'):
            self.dark_theme = False
            
        # สลับค่า theme
        self.dark_theme = not self.dark_theme
        
        if self.dark_theme:
            # ธีม dark
            self.theme_toggle_btn.setText("🌙")  # Moon emoji
            stylesheet = """
                QWidget {
                    background-color: #2b2b2b;
                    color: #ffffff;
                    font-family: "Segoe UI", sans-serif;
                    font-size: 14px;
                }
                QPushButton {
                    background-color: #3c3c3c;
                    color: #ffffff;
                    border: 1px solid #5c5c5c;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-weight: 500;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #4c4c4c;
                    border: 1px solid #7c7c7c;
                }
                QPushButton:pressed {
                    background-color: #5c5c5c;
                    border: 1px solid #9c9c9c;
                }
                QPushButton#primary {
                    background-color: #0078D7;
                    color: #ffffff;
                    border: 1px solid #0078D7;
                }
                QPushButton#primary:hover {
                    background-color: #0066B4;
                    border: 1px solid #006B4;
                }
                QPushButton#primary:pressed {
                    background-color: #005599;
                    border: 1px solid #005599;
                }
                QLabel {
                    font-size: 14px;
                }
                QLabel#title {
                    font-size: 16px;
                    font-weight: bold;
                }
                QLabel#status {
                    font-size: 13px;
                }
                QTabWidget::pane {
                    border: 1px solid #5c5c5c;
                    border-radius: 4px;
                }
                QTabBar::tab {
                    background-color: #3c3c3c;
                    color: #ffffff;
                    padding: 8px 16px;
                    border-top-left-radius: 4px;
                    border-top-right-radius: 4px;
                    border: 1px solid #5c5c5c;
                    font-size: 14px;
                    margin-right: 2px;
                }
                QTabBar::tab:selected {
                    background-color: #2b2b2b;
                    font-weight: bold;
                    border-bottom: none;
                }
                QScrollArea {
                    background-color: #2b2b2b;
                }
                QProgressBar {
                    border: 1px solid #5c5c5c;
                    background-color: #3c3c3c;
                    border-radius: 4px;
                    text-align: center;
                    font-size: 12px;
                }
                QProgressBar::chunk {
                    background-color: #0078D7;
                    border-radius: 3px;
                }
                QCheckBox {
                    spacing: 5px;
                    font-size: 14px;
                }
                QLabel#status {
                    background-color: #3c3c3c;
                    border: 1px solid #5c5c5c;
                    border-radius: 4px;
                    padding: 5px;
                    font-size: 13px;
                }
                QCheckBox::indicator {
                    width: 18px;
                    height: 18px;
                }
                QCheckBox::indicator:unchecked {
                    border: 1px solid #5c5c5c;
                    background-color: #3c3c3c;
                }
                QCheckBox::indicator:checked {
                    border: 1px solid #0078D7;
                    background-color: #0078D7;
                }
                QCheckBox::indicator:checked::after {
                    content: "";
                    position: absolute;
                    width: 4px;
                    height: 8px;
                    border: 2px solid white;
                    border-top: none;
                    border-left: none;
                    transform: rotate(45deg);
                    margin-left: 4px;
                    margin-top: 1px;
                }
                QComboBox {
                    font-size: 14px;
                    padding: 4px;
                }
                QSpinBox {
                    font-size: 14px;
                    padding: 4px;
                }
            """
        else:
            # ธีม light (default)
            self.theme_toggle_btn.setText("🌞")  # Sun emoji
            stylesheet = """
                QWidget {
                    background-color: #ffffff;
                    color: #000000;
                    font-family: "Segoe UI", sans-serif;
                    font-size: 14px;
                }
                QPushButton {
                    background-color: #f0f0f0;
                    color: #000000;
                    border: 1px solid #c0c0c0;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-weight: 500;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #e0e0e0;
                    border: 1px solid #a0a0a0;
                }
                QPushButton:pressed {
                    background-color: #d0d0d0;
                    border: 1px solid #808080;
                }
                QPushButton#primary {
                    background-color: #0078D7;
                    color: #ffffff;
                    border: 1px solid #0078D7;
                }
                QPushButton#primary:hover {
                    background-color: #0066B4;
                    border: 1px solid #006B4;
                }
                QPushButton#primary:pressed {
                    background-color: #005599;
                    border: 1px solid #005599;
                }
                QLabel {
                    font-size: 14px;
                }
                QLabel#title {
                    font-size: 16px;
                    font-weight: bold;
                }
                QLabel#status {
                    font-size: 13px;
                    background-color: #f0f0f0;
                    border: 1px solid #c0c0c0;
                    border-radius: 4px;
                    padding: 5px;
                }
                QTabWidget::pane {
                    border: 1px solid #c0c0c0;
                    border-radius: 4px;
                }
                QTabBar::tab {
                    background-color: #f0f0f0;
                    color: #000000;
                    padding: 8px 16px;
                    border-top-left-radius: 4px;
                    border-top-right-radius: 4px;
                    border: 1px solid #c0c0c0;
                    font-size: 14px;
                    margin-right: 2px;
                }
                QTabBar::tab:selected {
                    background-color: #ffffff;
                    font-weight: bold;
                    border-bottom: none;
                }
                QScrollArea {
                    background-color: #ffffff;
                }
                QProgressBar {
                    border: 1px solid #c0c0c0;
                    background-color: #f0f0f0;
                    border-radius: 4px;
                    text-align: center;
                    font-size: 12px;
                }
                QProgressBar::chunk {
                    background-color: #0078D7;
                    border-radius: 3px;
                }
                QCheckBox {
                    spacing: 5px;
                    font-size: 14px;
                }
                QCheckBox::indicator {
                    width: 18px;
                    height: 18px;
                }
                QCheckBox::indicator:unchecked {
                    border: 1px solid #c0c0c0;
                    background-color: #ffffff;
                }
                QCheckBox::indicator:checked {
                    border: 1px solid #0078D7;
                    background-color: #0078D7;
                }
                QCheckBox::indicator:checked::after {
                    content: "";
                    position: absolute;
                    width: 4px;
                    height: 8px;
                    border: 2px solid white;
                    border-top: none;
                    border-left: none;
                    transform: rotate(45deg);
                    margin-left: 4px;
                    margin-top: 1px;
                }
                QComboBox {
                    font-size: 14px;
                    padding: 4px;
                }
                QSpinBox {
                    font-size: 14px;
                    padding: 4px;
                }
            """
        
        # ใช้ stylesheet
        self.setStyleSheet(stylesheet)
    
    def on_image_clicked(self, image_path: str):
        # Handle image click - add or remove from selected images list
        if image_path in self.selected_images:
            self.selected_images.remove(image_path)
            # Update status to show number of selected images
            self.status_label.setText(f"Unselected image. {len(self.selected_images)} images selected.")
        else:
            self.selected_images.append(image_path)
            # Update status to show number of selected images
            self.status_label.setText(f"Selected image: {os.path.basename(image_path)}. {len(self.selected_images)} images selected.")
    def closeEvent(self, event: QCloseEvent):
        """Handle the close event to ensure proper shutdown."""
        if self.worker is not None:
            # Stop the worker if it's running
            self.worker.stop()
            # Wait for the worker to finish (with a longer timeout)
            self.worker.wait(3000)  # Wait up to 3 seconds
            # Set worker to None after stopping
            self.worker = None
        
        # Accept the close event to allow the application to close
        event.accept()
    
    def resizeEvent(self, event):
        # Update the grid layout when the window is resized
        self.update_grid_layout()
        super().resizeEvent(event)