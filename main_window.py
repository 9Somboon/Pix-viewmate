import sys
import os
import threading
import json
import logging
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLineEdit, QLabel, QFileDialog,
                             QScrollArea, QGridLayout, QMessageBox, QCheckBox, QTabWidget, QComboBox, QSpinBox, QDoubleSpinBox, QFormLayout, QProgressBar, QSlider, QInputDialog, QGroupBox)
from PyQt6.QtGui import QPixmap, QCloseEvent
from PyQt6.QtCore import Qt
from worker import FilterWorker
import requests
from clickable_image_label import ClickableImageLabel
from utilities import embed_keywords_in_exif
from smart_search_worker import IndexWorker, SearchWorker
from auto_tag_worker import AutoTagWorker
from thumbnail_cache import load_cached_thumbnail, get_thumbnail_cache
from config import OLLAMA_HOST

# ตั้งค่า logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ImageFilterApp(QWidget):
    OLLAMA_API_URL = "http://192.168.50.55:11434"

    def save_settings(self):
        settings = {
            "api_provider": self.api_provider_combo.currentText(),
            "api_url": self.api_url_edit.text(),
            "selected_model": self.model_combo.currentText(),
            "temperature": self.temp_spin.value(),
            "max_workers": self.max_workers_spin.value(),
            "vision_model": self.vision_model_edit.text(),
            "embedding_model": self.embedding_model_edit.text()
        }
        
        with open("app_settings.json", "w") as f:
            json.dump(settings, f, indent=2)

    def load_settings(self):
        try:
            with open("app_settings.json", "r") as f:
                settings = json.load(f)
            
            # โหลด API provider
            api_provider = settings.get("api_provider", "Auto Detect")
            self.api_provider_combo.setCurrentText(api_provider)
            
            self.api_url_edit.setText(settings.get("api_url", self.OLLAMA_API_URL))
            self.temp_spin.setValue(settings.get("temperature", 0.0))
            self.max_workers_spin.setValue(settings.get("max_workers", 4))
            
            # โหลด Smart Search settings
            from config import VISION_MODEL, EMBEDDING_MODEL
            self.vision_model_edit.setText(settings.get("vision_model", VISION_MODEL))
            self.embedding_model_edit.setText(settings.get("embedding_model", EMBEDDING_MODEL))
            
            # โหลดโมเดลที่เลือกไว้หลังจากดึงรายการโมเดลจาก API
            selected_model = settings.get("selected_model", "")
            if selected_model:
                # เก็บค่าไว้ชั่วคราวจนกว่าจะโหลดโมเดลจาก API เสร็จ
                self.pending_selected_model = selected_model
        except FileNotFoundError:
            # ถ้าไม่มีไฟล์การตั้งค่า ให้ใช้ค่าเริ่มต้น
            self.pending_selected_model = ""
        except Exception as e:
            print(f"Error loading settings: {e}")
            self.pending_selected_model = ""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pix-viewmate - Image Filter")
        self.resize(900, 700)
        self.folder_path = ""
        self.worker = None
        self.setAcceptDrops(True)  # Enable drag and drop
        self.selected_images = []  # List to store selected image paths

        # Load settings
        # self.load_settings()  # โหลด settings ก่อนที่จะใช้ self.api_url_edit

        # Set default theme to dark
        self.dark_theme = True

        # Smart Search workers
        self.index_worker = None
        self.search_worker = None
        self.smart_search_folder = ""
        self.cached_search_results = []  # Store all search results for real-time filtering
        
        # Auto-Tag worker
        self.auto_tag_worker = None

        # Tabs
        self.tabs = QTabWidget()
        self.main_tab = QWidget()
        self.smart_search_tab = QWidget()
        self.settings_tab = QWidget()
        self.tabs.addTab(self.main_tab, "Main")
        self.tabs.addTab(self.smart_search_tab, "Smart Search")
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

        # Slider for thumbnail size
        self.thumbnail_slider = QSlider(Qt.Orientation.Horizontal)
        self.thumbnail_slider.setMinimum(64)
        self.thumbnail_slider.setMaximum(512)
        self.thumbnail_slider.setValue(256)
        self.thumbnail_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.thumbnail_slider.setTickInterval(64)
        self.thumbnail_slider.valueChanged.connect(self.update_thumbnail_size)
        
        # Set slider to a smaller size
        self.thumbnail_slider.setFixedWidth(150)
        self.thumbnail_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 6px;
                background: #ddd;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #0078D7;
                border: 1px solid #0078D7;
                width: 12px;
                margin: -6px 0;
                border-radius: 6px;
            }
            QSlider::sub-page:horizontal {
                background: #0078D7;
                border-radius: 3px;
            }
        """)
        
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
        main_layout.addLayout(progress_layout)
        main_layout.addWidget(self.scroll_area)
        
        # Layout for bottom controls (buttons and slider)
        bottom_controls_layout = QHBoxLayout()
        
        # Control Buttons
        self.delete_btn = QPushButton("Delete")
        self.move_to_folder_btn = QPushButton("Move to folder")
        self.embed_keywords_btn = QPushButton("Embed Keywords")
        self.select_all_btn = QPushButton("Select all")
        self.deselect_all_btn = QPushButton("Deselect all")
        self.invert_selection_btn = QPushButton("Invert selection")
        
        # Auto Tag Controls
        self.auto_tag_btn = QPushButton("🏷️ Auto Tag")
        self.auto_tag_btn.setToolTip("Generate AI keywords for selected images")
        self.auto_tag_keywords_spin = QSpinBox()
        self.auto_tag_keywords_spin.setRange(5, 50)
        self.auto_tag_keywords_spin.setValue(20)
        self.auto_tag_keywords_spin.setSuffix(" keywords")
        self.auto_tag_keywords_spin.setToolTip("Number of keywords to generate")
        self.auto_tag_append_checkbox = QCheckBox("Append")
        self.auto_tag_append_checkbox.setChecked(True)
        self.auto_tag_append_checkbox.setToolTip("Append to existing keywords")
        self.auto_tag_stop_btn = QPushButton("Stop")
        self.auto_tag_stop_btn.setEnabled(False)
        
        bottom_controls_layout.addWidget(self.delete_btn)
        bottom_controls_layout.addWidget(self.move_to_folder_btn)
        bottom_controls_layout.addWidget(self.embed_keywords_btn)
        bottom_controls_layout.addWidget(self.select_all_btn)
        bottom_controls_layout.addWidget(self.deselect_all_btn)
        bottom_controls_layout.addWidget(self.invert_selection_btn)
        bottom_controls_layout.addSpacing(10)
        bottom_controls_layout.addWidget(self.auto_tag_btn)
        bottom_controls_layout.addWidget(self.auto_tag_keywords_spin)
        bottom_controls_layout.addWidget(self.auto_tag_append_checkbox)
        bottom_controls_layout.addWidget(self.auto_tag_stop_btn)
        
        bottom_controls_layout.addStretch() # Pushes slider to the right
        
        # Thumbnail Slider
        bottom_controls_layout.addWidget(self.thumbnail_slider)
        
        main_layout.addLayout(bottom_controls_layout)
        
        # Connect delete button to delete_selected_images function
        self.delete_btn.clicked.connect(self.delete_selected_images)
        
        # Connect move to folder button to move_selected_images function
        self.move_to_folder_btn.clicked.connect(self.move_selected_images)
        self.embed_keywords_btn.clicked.connect(self.embed_keywords_for_selected_images)
        
        # Connect select all button to select_all_images function
        self.select_all_btn.clicked.connect(self.select_all_images)
        
        # Connect deselect all button to deselect_all_images function
        self.deselect_all_btn.clicked.connect(self.deselect_all_images)
        
        # Connect invert selection button to invert_selection function
        self.invert_selection_btn.clicked.connect(self.invert_selection)
        
        # Connect Auto Tag buttons
        self.auto_tag_btn.clicked.connect(self.start_auto_tagging)
        self.auto_tag_stop_btn.clicked.connect(self.stop_auto_tagging)
        
        # Initially hide control buttons
        self.update_control_buttons_visibility()
        
        
        # Smart Search tab layout
        smart_search_layout = QVBoxLayout(self.smart_search_tab)
        smart_search_layout.setContentsMargins(20, 20, 20, 20)
        smart_search_layout.setSpacing(15)
        
        # Folder selection for indexing
        ss_folder_layout = QHBoxLayout()
        ss_folder_layout.setSpacing(10)
        self.ss_browse_btn = QPushButton("Browse Folder")
        self.ss_browse_btn.clicked.connect(self.ss_browse_folder)
        self.ss_folder_label = QLabel("No folder selected")
        self.ss_folder_label.setWordWrap(True)
        self.ss_folder_label.setMinimumWidth(200)
        self.ss_include_subfolder_checkbox = QCheckBox("Include Subfolders")
        self.ss_include_subfolder_checkbox.setChecked(True)
        ss_folder_layout.addWidget(self.ss_browse_btn)
        ss_folder_layout.addWidget(self.ss_folder_label)
        ss_folder_layout.addWidget(self.ss_include_subfolder_checkbox)
        ss_folder_layout.addStretch()
        
        # Index button and controls
        ss_index_layout = QHBoxLayout()
        ss_index_layout.setSpacing(10)
        self.ss_index_btn = QPushButton("🔄 Sync/Index Images")
        self.ss_index_btn.clicked.connect(self.ss_start_indexing)
        self.ss_stop_index_btn = QPushButton("Stop")
        self.ss_stop_index_btn.setEnabled(False)
        self.ss_stop_index_btn.clicked.connect(self.ss_stop_indexing)
        ss_index_layout.addWidget(self.ss_index_btn)
        ss_index_layout.addWidget(self.ss_stop_index_btn)
        ss_index_layout.addStretch()
        
        # Index progress
        ss_progress_layout = QHBoxLayout()
        self.ss_progress_bar = QProgressBar()
        self.ss_progress_bar.setVisible(False)
        self.ss_progress_info = QLabel("")
        self.ss_progress_info.setWordWrap(True)
        ss_progress_layout.addWidget(self.ss_progress_bar)
        ss_progress_layout.addSpacing(10)
        ss_progress_layout.addWidget(self.ss_progress_info)
        
        # Status label
        self.ss_status_label = QLabel("Ready. Select a folder and click 'Sync/Index Images' to start.")
        self.ss_status_label.setWordWrap(True)
        self.ss_status_label.setObjectName("status")
        
        # Search input
        ss_search_layout = QHBoxLayout()
        ss_search_layout.setSpacing(10)
        self.ss_search_edit = QLineEdit()
        self.ss_search_edit.setPlaceholderText("Describe what you're looking for (e.g., 'sunset on beach', 'cat playing')")
        self.ss_search_edit.returnPressed.connect(self.ss_start_search)
        self.ss_search_btn = QPushButton("🔍 Search")
        self.ss_search_btn.clicked.connect(self.ss_start_search)
        ss_search_layout.addWidget(QLabel("Search:"))
        ss_search_layout.addWidget(self.ss_search_edit)
        ss_search_layout.addWidget(self.ss_search_btn)
        
        # Strictness slider for filtering results
        ss_strictness_layout = QHBoxLayout()
        ss_strictness_layout.setSpacing(10)
        ss_strictness_layout.addWidget(QLabel("Strictness:"))
        self.ss_strictness_slider = QSlider(Qt.Orientation.Horizontal)
        self.ss_strictness_slider.setMinimum(1)  # Maps to threshold 1.5 (loose)
        self.ss_strictness_slider.setMaximum(10)  # Maps to threshold 0.3 (strict)
        self.ss_strictness_slider.setValue(5)  # Default: 0.9 (moderate)
        self.ss_strictness_slider.setFixedWidth(150)
        self.ss_strictness_label = QLabel("Moderate")
        self.ss_strictness_slider.valueChanged.connect(self.ss_update_strictness_label)
        self.ss_strictness_slider.valueChanged.connect(self.ss_filter_cached_results)  # Real-time filtering
        ss_strictness_layout.addWidget(self.ss_strictness_slider)
        ss_strictness_layout.addWidget(self.ss_strictness_label)
        ss_strictness_layout.addStretch()
        
        # Results scroll area
        self.ss_scroll_area = QScrollArea()
        self.ss_scroll_area.setWidgetResizable(True)
        self.ss_thumbs_widget = QWidget()
        self.ss_grid_layout = QGridLayout()
        self.ss_thumbs_widget.setLayout(self.ss_grid_layout)
        self.ss_scroll_area.setWidget(self.ss_thumbs_widget)
        
        # Thumbnail slider for results
        ss_bottom_layout = QHBoxLayout()
        ss_bottom_layout.addStretch()
        ss_bottom_layout.addWidget(QLabel("Thumbnail Size:"))
        self.ss_thumbnail_slider = QSlider(Qt.Orientation.Horizontal)
        self.ss_thumbnail_slider.setMinimum(64)
        self.ss_thumbnail_slider.setMaximum(512)
        self.ss_thumbnail_slider.setValue(200)
        self.ss_thumbnail_slider.setFixedWidth(150)
        self.ss_thumbnail_slider.valueChanged.connect(self.ss_update_thumbnail_size)
        ss_bottom_layout.addWidget(self.ss_thumbnail_slider)
        
        # Assemble Smart Search tab
        smart_search_layout.addLayout(ss_folder_layout)
        smart_search_layout.addLayout(ss_index_layout)
        smart_search_layout.addLayout(ss_progress_layout)
        smart_search_layout.addWidget(self.ss_status_label)
        smart_search_layout.addLayout(ss_search_layout)
        smart_search_layout.addLayout(ss_strictness_layout)
        smart_search_layout.addWidget(self.ss_scroll_area)
        smart_search_layout.addLayout(ss_bottom_layout)

        # Settings tab layout
        # Main layout for settings tab
        settings_main_layout = QVBoxLayout(self.settings_tab)
        settings_main_layout.setContentsMargins(20, 20, 20, 20)
        settings_main_layout.setSpacing(15)

        # API Settings GroupBox (supports both Ollama and LM Studio)
        api_group_box = QGroupBox("API Settings")
        api_layout = QFormLayout(api_group_box)
        api_layout.setContentsMargins(10, 15, 10, 10)
        api_layout.setSpacing(10)

        # API Provider dropdown
        self.api_provider_combo = QComboBox()
        self.api_provider_combo.addItems(["Auto Detect", "Ollama", "LM Studio"])
        self.api_provider_combo.currentTextChanged.connect(self.on_api_provider_changed)
        
        self.api_url_edit = QLineEdit(self.OLLAMA_API_URL)
        self.api_url_edit.setMinimumWidth(300)
        self.api_url_edit.setPlaceholderText("e.g., http://localhost:11434 (Ollama) or http://localhost:1234 (LM Studio)")
        self.model_combo = QComboBox()
        self.model_combo.setEditable(False)
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 1.0)
        self.temp_spin.setValue(0.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setDecimals(1)

        api_layout.addRow("API Provider:", self.api_provider_combo)
        api_layout.addRow("API URL:", self.api_url_edit)
        api_layout.addRow("Model:", self.model_combo)
        api_layout.addRow("Temperature:", self.temp_spin)

        # Worker Settings GroupBox
        worker_group_box = QGroupBox("Worker Settings")
        worker_layout = QFormLayout(worker_group_box)
        worker_layout.setContentsMargins(10, 15, 10, 10)
        worker_layout.setSpacing(10)

        self.max_workers_spin = QSpinBox()
        self.max_workers_spin.setRange(1, 16)
        self.max_workers_spin.setValue(4)
        self.max_workers_spin.setSuffix(" workers")
        worker_layout.addRow("Max Concurrent Workers:", self.max_workers_spin)

        # Smart Search Settings GroupBox
        smart_search_group_box = QGroupBox("Smart Search Settings")
        smart_search_layout = QFormLayout(smart_search_group_box)
        smart_search_layout.setContentsMargins(10, 15, 10, 10)
        smart_search_layout.setSpacing(10)

        from config import VISION_MODEL, EMBEDDING_MODEL
        self.vision_model_edit = QLineEdit(VISION_MODEL)
        self.vision_model_edit.setMinimumWidth(300)
        self.embedding_model_edit = QLineEdit(EMBEDDING_MODEL)
        self.embedding_model_edit.setMinimumWidth(300)

        smart_search_layout.addRow("Vision Model:", self.vision_model_edit)
        smart_search_layout.addRow("Embedding Model:", self.embedding_model_edit)

        # Buttons layout
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        
        self.refresh_model_btn = QPushButton("Refresh Models")
        self.save_settings_btn = QPushButton("Save Settings")
        self.save_settings_btn.clicked.connect(self.save_settings) # Connect here as well

        buttons_layout.addStretch() # Push buttons to the right
        buttons_layout.addWidget(self.refresh_model_btn)
        buttons_layout.addWidget(self.save_settings_btn)

        settings_main_layout.addWidget(api_group_box)
        settings_main_layout.addWidget(worker_group_box)
        settings_main_layout.addWidget(smart_search_group_box)
        settings_main_layout.addStretch() # Push content to the top
        settings_main_layout.addLayout(buttons_layout)

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)  # ลบ margin ของ main layout
        layout.addWidget(self.tabs)
        self.setLayout(layout)

        # Load settings first, then fetch models with the correct URL
        self.load_settings()  # โหลด settings ก่อนเพื่อให้ใช้ URL ที่ถูกต้อง
        self.fetch_ollama_models()  # รีเฟรชรายชื่อโมเดลทุกครั้งที่เปิดแอป
        
        self.refresh_model_btn.clicked.connect(self.fetch_ollama_models)
        self.save_settings_btn.clicked.connect(self.save_settings)
        self.model_combo.currentTextChanged.connect(self.on_model_changed)

    def fetch_models(self):
        """Fetch models from the selected API provider (Ollama or LM Studio)"""
        print("Fetch models called")
        def fetch():
            print("Fetch function started")
            base_url = self.api_url_edit.text().rstrip("/")
            # ตรวจสอบว่า base_url ลงท้ายด้วย endpoint ต่างๆ หรือไม่ ถ้าใช่ให้ตัดออก
            if base_url.endswith("/api/tags"):
                base_url = base_url[:-len("/api/tags")]
            if base_url.endswith("/api/generate"):
                base_url = base_url[:-len("/api/generate")]
            if base_url.endswith("/v1/models"):
                base_url = base_url[:-len("/v1/models")]
            if base_url.endswith("/v1/chat/completions"):
                base_url = base_url[:-len("/v1/chat/completions")]
            
            # ใช้ API provider ที่เลือกหรือ auto detect
            api_provider = self.api_provider_combo.currentText()
            if api_provider == "Ollama":
                api_type = "ollama"
            elif api_provider == "LM Studio":
                api_type = "openai"
            else:  # Auto Detect
                api_type = self.detect_api_type(base_url)
            print(f"Using API type: {api_type} (provider: {api_provider})")
            
            if api_type == "ollama":
                url = base_url + "/api/tags"
            elif api_type == "openai":
                url = base_url + "/v1/models"
            else:
                print("Unknown API type")
                self.model_combo.clear()
                self.model_combo.addItem("(fetch failed)")
                return
            
            try:
                print(f"Fetching from URL: {url}")
                resp = requests.get(url, timeout=10)
                print(f"Response status code: {resp.status_code}")
                resp.raise_for_status()
                data = resp.json()
                print(f"Response data: {data}")
                
                if api_type == "ollama":
                    models = [m['name'] for m in data.get('models', [])]
                elif api_type == "openai":
                    models = [m['id'] for m in data.get('data', [])]
                
                print(f"Models: {models}")
                self.model_combo.clear()
                self.model_combo.addItems(models)
                if models:
                    # ถ้ามีโมเดลที่เลือกไว้ชั่วคราว ให้ตั้งค่า
                    if hasattr(self, 'pending_selected_model') and self.pending_selected_model:
                        if self.pending_selected_model in models:
                            self.model_combo.setCurrentText(self.pending_selected_model)
                            self.model_label.setText(f"Model: {self.pending_selected_model}")
                        self.pending_selected_model = ""
                    # ถ้าไม่มีการตั้งค่าชั่วคราว ให้เลือกตัวแรก
                    elif not self.model_combo.currentText():
                        self.model_combo.setCurrentIndex(0)
                        self.model_label.setText(f"Model: {self.model_combo.currentText()}")
            except Exception as e:
                print(f"Error fetching models: {e}")
                self.model_combo.clear()
                self.model_combo.addItem("(fetch failed)")
        threading.Thread(target=fetch, daemon=True).start()
    
    # Alias for backward compatibility
    def fetch_ollama_models(self):
        self.fetch_models()

    def detect_api_type(self, base_url):
        """
        ตรวจจับประเภทของ API โดยอัตโนมัติ
        คืนค่า "ollama", "openai" หรือ "unknown"
        """
        # ลองเรียก endpoint ของ Ollama API
        try:
            url = base_url + "/api/tags"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                # ตรวจสอบโครงสร้างข้อมูลของ Ollama API
                if 'models' in data:
                    return "ollama"
        except:
            pass
        
        # ลองเรียก endpoint ของ API ที่เข้ากันได้กับ OpenAI
        try:
            url = base_url + "/v1/models"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                # ตรวจสอบโครงสร้างข้อมูลของ API ที่เข้ากันได้กับ OpenAI
                if 'data' in data:
                    return "openai"
        except:
            pass
        
        return "unknown"
    
    def on_model_changed(self):
        # อัปเดตชื่อโมเดลในแถบทดแทนสถานะเมื่อมีการเลือกโมเดลใหม่
        self.model_label.setText(f"Model: {self.model_combo.currentText()}")

    def on_api_provider_changed(self, provider):
        """
        เมื่อเปลี่ยน API provider ให้อัปเดต URL placeholder และ refresh รายการโมเดล
        """
        if provider == "Ollama":
            self.api_url_edit.setPlaceholderText("e.g., http://localhost:11434")
            # ถ้า URL ว่างหรือเป็น default ของ LM Studio ให้เปลี่ยนเป็น default ของ Ollama
            current_url = self.api_url_edit.text().strip()
            if not current_url or current_url == "http://localhost:1234":
                self.api_url_edit.setText("http://localhost:11434")
        elif provider == "LM Studio":
            self.api_url_edit.setPlaceholderText("e.g., http://localhost:1234")
            # ถ้า URL ว่างหรือเป็น default ของ Ollama ให้เปลี่ยนเป็น default ของ LM Studio
            current_url = self.api_url_edit.text().strip()
            if not current_url or current_url == "http://localhost:11434":
                self.api_url_edit.setText("http://localhost:1234")
        else:  # Auto Detect
            self.api_url_edit.setPlaceholderText("e.g., http://localhost:11434 (Ollama) or http://localhost:1234 (LM Studio)")
        
        # Refresh รายการโมเดล
        self.fetch_models()

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
        logger.debug("Start filtering requested")
        # ตรวจสอบว่ามี worker ที่กำลังทำงานอยู่หรือไม่
        if self.worker is not None and self.worker.isRunning():
            logger.debug("Worker is already running")
            QMessageBox.warning(self, "Worker Busy", "A filtering operation is already in progress. Please wait for it to finish or stop it before starting a new one.")
            return
            
        prompt = self.prompt_edit.text().strip()
        if not self.folder_path or not os.path.isdir(self.folder_path):
            logger.debug("No valid folder selected")
            QMessageBox.warning(self, "No Folder", "Please select a valid folder containing images.")
            return
        if not prompt:
            logger.debug("No prompt entered")
            QMessageBox.warning(self, "No Prompt", "Please enter a prompt.")
            return
        
        # ตรวจสอบการเชื่อมต่อกับ API ก่อนเริ่มการกรอง
        api_base_url = self.api_url_edit.text().rstrip("/")
        # ตรวจสอบว่า api_base_url ลงท้ายด้วย /api/generate หรือไม่ ถ้าใช่ให้ตัดออก
        if api_base_url.endswith("/api/generate"):
            api_base_url = api_base_url[:-len("/api/generate")]
        # ตรวจสอบว่า api_base_url ลงท้ายด้วย /api/tags หรือไม่ ถ้าใช่ให้ตัดออก
        if api_base_url.endswith("/api/tags"):
            api_base_url = api_base_url[:-len("/api/tags")]
        # ตรวจสอบว่า api_base_url ลงท้ายด้วย /v1/models หรือไม่ ถ้าใช่ให้ตัดออก
        if api_base_url.endswith("/v1/models"):
            api_base_url = api_base_url[:-len("/v1/models")]
        
        try:
            resp = requests.get(api_base_url, timeout=5)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.debug(f"Connection error: {e}")
            QMessageBox.critical(self, "Connection Error", f"Failed to connect to API at {api_base_url}. Please check your network connection and server status.\n\nError: {str(e)}")
            return
        
        include_subfolders = self.include_subfolder_checkbox.isChecked()
        temp = self.temp_spin.value()  # ใช้ค่า temperature จาก settings


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
            logger.debug("No file type selected")
            QMessageBox.warning(self, "No File Type", "Please select at least one file type (PNG or JPG).")
            self.filter_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            return
        
        # ดึงชื่อโมเดลที่เลือกจาก ComboBox
        selected_model = self.model_combo.currentText()
        if not selected_model or selected_model == "(fetch failed)":
            logger.debug("No valid model selected")
            QMessageBox.warning(self, "No Model", "Please select a valid model from the Settings tab.")
            self.filter_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            return

        # อัปเดตชื่อโมเดลในแถบทดแทนสถานะ
        self.model_label.setText(f"Model: {selected_model}")
        
        # บันทึกการตั้งค่า
        self.save_settings()
        
        # ตรวจจับประเภทของ API ตาม provider ที่เลือก
        api_provider = self.api_provider_combo.currentText()
        if api_provider == "Ollama":
            api_type = "ollama"
        elif api_provider == "LM Studio":
            api_type = "openai"  # LM Studio uses OpenAI compatible API
        else:  # Auto Detect
            api_type = self.detect_api_type(api_base_url)
        print(f"Using API type: {api_type} (provider: {api_provider})")
        
        # กำหนด API URL ตามประเภท
        if api_type == "ollama":
            api_url = api_base_url + "/api/generate"
        else:  # openai compatible (LM Studio)
            api_url = api_base_url + "/v1/chat/completions"
        
        max_workers = self.max_workers_spin.value()
        logger.debug(f"Creating new FilterWorker with max_workers: {max_workers}")
        self.worker = FilterWorker(
            self.folder_path, prompt, api_url, selected_model, include_subfolders, temp, file_type, max_workers, api_type=api_type
        )
        self.worker.progress_update.connect(self.update_status_and_log)
        self.worker.image_matched.connect(self.add_matched_image_to_display)
        self.worker.processing_finished.connect(self.filtering_finished)
        self.worker.show_processing_preview.connect(self.show_processing_preview)
        self.worker.progress_info.connect(self.update_progress_info)
        self.worker.start()
        logger.debug("FilterWorker started")

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
        thumbnail_size = self.thumbnail_slider.value()
        
        # Use cached thumbnail loading for better performance
        pixmap = load_cached_thumbnail(image_path, thumbnail_size)
        if not pixmap.isNull():
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
        # self.worker = None  <-- Removed to prevent crash. Worker will be cleaned up when a new one is created or app closes.
    
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
                /* ใช้ฟอนต์ San Francisco ถ้ามี หรือฟอนต์ sans-serif ทั่วไป */
                QWidget {
                    /* font-family: -apple-system, BlinkMacSystemFont, "San Francisco", "Helvetica Neue", sans-serif; */
                    /* font-size: 13px; */
                    /* color: #FFFFFF; */
                    /* background-color: #2B2B2B; */
                }
                
                /* ปุ่มรอง (Secondary Button) */
                QPushButton {
                    /* background-color: #4A4A4A; */ /* สีเทาเข้มของ macOS */
                    /* color: #FFFFFF; */
                    /* border: none; */
                    /* border-radius: 6px; */
                    /* padding: 8px 16px; */
                    /* font-size: 13px; */
                    /* font-weight: 400; */
                }
                
                QPushButton:hover {
                    /* background-color: #5A5A5A; */ /* สีเข้มขึ้นเมื่อ hover */
                }
                
                QPushButton:pressed {
                    /* background-color: #3A3A3A; */ /* สีเข้มขึ้นเมื่อกด */
                }
                
                /* ปุ่มหลัก (Primary Button) */
                QPushButton#primary, QPushButton#filter_btn, QPushButton#browse_btn, QPushButton#refresh_model_btn {
                    /* background-color: #0A84FF; */ /* สีฟ้าของ macOS */
                    /* color: white; */
                    /* border: none; */
                    /* border-radius: 6px; */
                    /* padding: 8px 16px; */
                    /* font-size: 13px; */
                    /* font-weight: 500; */
                }
                
                QPushButton#primary:hover, QPushButton#filter_btn:hover, QPushButton#browse_btn:hover, QPushButton#refresh_model_btn:hover {
                    /* background-color: #007AFF; */ /* สีเข้มขึ้นเมื่อ hover */
                }
                
                QPushButton#primary:pressed, QPushButton#filter_btn:pressed, QPushButton#browse_btn:pressed, QPushButton#refresh_model_btn:pressed {
                    /* background-color: #0062CC; */ /* สีเข้มขึ้นเมื่อกด */
                }
                
                /* ปุ่มควบคุม (Control Buttons) */
                QPushButton#pause_btn, QPushButton#stop_btn {
                    /* background-color: #4A4A4A; */
                    /* color: #FFFFFF; */
                    /* border: none; */
                    /* border-radius: 6px; */
                    /* padding: 6px 12px; */
                    /* font-size: 12px; */
                    /* font-weight: 400; */
                }
                
                QPushButton#pause_btn:hover, QPushButton#stop_btn:hover {
                    /* background-color: #5A5A5A; */
                }
                
                QPushButton#pause_btn:pressed, QPushButton#stop_btn:pressed {
                    /* background-color: #3A3A3A; */
                }
                
                /* ปุ่ม Theme Toggle */
                QPushButton#theme_toggle_btn {
                    /* background-color: transparent; */
                    /* color: #FFFFFF; */
                    /* border: none; */
                    /* border-radius: 6px; */
                    /* padding: 6px 12px; */
                    /* font-size: 16px; */
                    /* font-weight: 400; */
                }
                
                QPushButton#theme_toggle_btn:hover {
                    /* background-color: rgba(255, 255, 255, 0.1); */
                }
                
                QPushButton#theme_toggle_btn:pressed {
                    /* background-color: rgba(255, 255, 255, 0.2); */
                }
                
                /* Label */
                QLabel {
                    /* color: #FFFFFF; */
                    /* font-size: 13px; */
                }
                
                QLabel#status {
                    /* color: #CCCCCC; */
                    /* font-size: 12px; */
                    /* background-color: #3A3A3A; */
                    /* padding: 6px 8px; */
                    /* border-radius: 4px; */
                }
                
                /* Tab Widget */
                QTabWidget::pane {
                    border: 1px solid #4A4A4A;
                    border-radius: 6px;
                    background-color: #2B2B2B;
                }
                
                QTabBar::tab {
                    /* background-color: #3A3A3A; */
                    /* color: #CCCCCC; */
                    /* padding: 8px 16px; */
                    /* border-top-left-radius: 6px; */
                    /* border-top-right-radius: 6px; */
                    /* border: 1px solid #4A4A4A; */
                    /* font-size: 13px; */
                    /* font-weight: 400; */
                    /* margin-right: 2px; */
                }
                
                QTabBar::tab:selected {
                    /* background-color: #2B2B2B; */
                    /* color: #FFFFFF; */
                    /* font-weight: 500; */
                    /* border-bottom: none; */
                }
                
                QTabBar::tab:hover:!selected {
                    /* background-color: #4A4A4A; */
                }
                
                /* Scroll Area */
                QScrollArea {
                    /* border: none; */
                    /* background-color: #2B2B2B; */
                }
                
                QScrollBar:vertical {
                    /* border: none; */
                    /* background: transparent; */
                    /* width: 8px; */
                    /* margin: 0px 0px 0px; */
                }
                
                QScrollBar::handle:vertical {
                    /* background: rgba(255, 255, 255, 0.3); */
                    /* border-radius: 4px; */
                    /* min-height: 20px; */
                }
                
                QScrollBar::handle:vertical:hover {
                    /* background: rgba(255, 255, 255, 0.5); */
                }
                
                QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical {
                    /* height: 0px; */
                }
                
                /* ProgressBar */
                QProgressBar {
                    /* border: none; */
                    /* background-color: #4A4A4A; */
                    /* border-radius: 3px; */
                    /* text-align: center; */
                    /* height: 6px; */
                }
                
                QProgressBar::chunk {
                    /* background-color: #0A84FF; */
                    /* border-radius: 3px; */
                }
                
                /* Input Fields */
                QLineEdit, QComboBox, QSpinBox {
                    /* padding: 6px 8px; */
                    /* border: 1px solid #4A4A4A; */
                    /* border-radius: 4px; */
                    /* background-color: #3A3A3A; */
                    /* color: #FFFFFF; */
                    /* font-size: 13px; */
                    /* selection-background-color: #0A84FF; */
                    /* selection-color: #FFFFFF; */
                }
                
                QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                    /* border: 1px solid #0A84FF; */
                    /* outline: none; */
                }
                
                QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {
                    /* background-color: #2A2A2A; */
                    /* color: #666666; */
                }
                
                /* Checkbox */
                QCheckBox {
                    /* spacing: 10px; */
                    /* font-size: 13px; */
                    /* color: #FFFFFF; */
                }
                
                QCheckBox::indicator {
                    /* width: 18px; */
                    /* height: 18px; */
                }
                
                QCheckBox::indicator:unchecked {
                    /* border: 1px solid #CCCCCC; */
                    /* background-color: #3A3A3A; */
                    /* border-radius: 4px; */
                }
                
                QCheckBox::indicator:unchecked:hover {
                    /* border: 1px solid #0A84FF; */
                }
                
                QCheckBox::indicator:checked {
                    /* border: 1px solid #0A84FF; */
                    /* background-color: #0A84FF; */
                    /* border-radius: 4px; */
                }
                
                QCheckBox::indicator:checked:hover {
                    /* border: 1px solid #007AFF; */
                    /* background-color: #007AFF; */
                }
            """
        else:
            # ธีม light (default)
            self.theme_toggle_btn.setText("🌞")  # Sun emoji
            stylesheet = """
                /* ใช้ฟอนต์ San Francisco ถ้ามี หรือฟอนต์ sans-serif ทั่วไป */
                QWidget {
                    /* font-family: -apple-system, BlinkMacSystemFont, "San Francisco", "Helvetica Neue", sans-serif; */
                    /* font-size: 13px; */
                    /* color: #000000; */
                    /* background-color: #FFFFFF; */
                }
                
                /* ปุ่มรอง (Secondary Button) */
                QPushButton {
                    /* background-color: #E6E6E6; */ /* สีเทาอ่อนของ macOS */
                    /* color: #000000; */
                    /* border: none; */
                    /* border-radius: 6px; */
                    /* padding: 8px 16px; */
                    /* font-size: 13px; */
                    /* font-weight: 400; */
                }
                
                QPushButton:hover {
                    /* background-color: #D6D6D6; */ /* สีเข้มขึ้นเมื่อ hover */
                }
                
                QPushButton:pressed {
                    /* background-color: #C6C6C6; */ /* สีเข้มขึ้นเมื่อกด */
                }
                
                /* ปุ่มหลัก (Primary Button) */
                QPushButton#primary, QPushButton#filter_btn, QPushButton#browse_btn, QPushButton#refresh_model_btn {
                    /* background-color: #007AFF; */ /* สีฟ้าของ macOS */
                    /* color: white; */
                    /* border: none; */
                    /* border-radius: 6px; */
                    /* padding: 8px 16px; */
                    /* font-size: 13px; */
                    /* font-weight: 500; */
                }
                
                QPushButton#primary:hover, QPushButton#filter_btn:hover, QPushButton#browse_btn:hover, QPushButton#refresh_model_btn:hover {
                    /* background-color: #0062CC; */ /* สีเข้มขึ้นเมื่อ hover */
                }
                
                QPushButton#primary:pressed, QPushButton#filter_btn:pressed, QPushButton#browse_btn:pressed, QPushButton#refresh_model_btn:pressed {
                    /* background-color: #004F99; */ /* สีเข้มขึ้นเมื่อกด */
                }
                
                /* ปุ่มควบคุม (Control Buttons) */
                QPushButton#pause_btn, QPushButton#stop_btn {
                    /* background-color: #E6E6E6; */
                    /* color: #000000; */
                    /* border: none; */
                    /* border-radius: 6px; */
                    /* padding: 6px 12px; */
                    /* font-size: 12px; */
                    /* font-weight: 400; */
                }
                
                QPushButton#pause_btn:hover, QPushButton#stop_btn:hover {
                    /* background-color: #D6D6D6; */
                }
                
                QPushButton#pause_btn:pressed, QPushButton#stop_btn:pressed {
                    /* background-color: #C6C6C6; */
                }
                
                /* ปุ่ม Theme Toggle */
                QPushButton#theme_toggle_btn {
                    /* background-color: transparent; */
                    /* color: #000000; */
                    /* border: none; */
                    /* border-radius: 6px; */
                    /* padding: 6px 12px; */
                    /* font-size: 16px; */
                    /* font-weight: 400; */
                }
                
                QPushButton#theme_toggle_btn:hover {
                    /* background-color: rgba(0, 0, 0.1); */
                }
                
                QPushButton#theme_toggle_btn:pressed {
                    /* background-color: rgba(0, 0, 0.2); */
                }
                
                /* Label */
                QLabel {
                    /* color: #000000; */
                    /* font-size: 13px; */
                }
                
                QLabel#status {
                    /* color: #666666; */
                    /* font-size: 12px; */
                    /* background-color: #F2F2F2; */
                    /* padding: 6px 8px; */
                    /* border-radius: 4px; */
                }
                
                /* Tab Widget */
                QTabWidget::pane {
                    /* border: 1px solid #E6E6E6; */
                    /* border-radius: 6px; */
                    /* background-color: #FFFFFF; */
                }
                
                QTabBar::tab {
                    /* background-color: #F2F2F2; */
                    /* color: #666666; */
                    /* padding: 8px 16px; */
                    /* border-top-left-radius: 6px; */
                    /* border-top-right-radius: 6px; */
                    /* border: 1px solid #E6E6E6; */
                    /* font-size: 13px; */
                    /* font-weight: 400; */
                    /* margin-right: 2px; */
                }
                
                QTabBar::tab:selected {
                    /* background-color: #FFFFFF; */
                    /* color: #000000; */
                    /* font-weight: 500; */
                    /* border-bottom: none; */
                }
                
                QTabBar::tab:hover:!selected {
                    /* background-color: #E6E6E6; */
                }
                
                /* Scroll Area */
                QScrollArea {
                    /* border: none; */
                    /* background-color: #FFFFFF; */
                }
                
                QScrollBar:vertical {
                    /* border: none; */
                    /* background: transparent; */
                    /* width: 8px; */
                    /* margin: 0px 0px 0px 0px; */
                }
                
                QScrollBar::handle:vertical {
                    /* background: rgba(0, 0, 0, 0.3); */
                    /* border-radius: 4px; */
                    /* min-height: 20px; */
                }
                
                QScrollBar::handle:vertical:hover {
                    /* background: rgba(0, 0, 0, 0.5); */
                }
                
                QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical {
                    /* height: 0px; */
                }
                
                /* ProgressBar */
                QProgressBar {
                    /* border: none; */
                    /* background-color: #E6E6E6; */
                    /* border-radius: 3px; */
                    /* text-align: center; */
                    /* height: 6px; */
                }
                
                QProgressBar::chunk {
                    /* background-color: #007AFF; */
                    /* border-radius: 3px; */
                }
                
                /* Input Fields */
                QLineEdit, QComboBox, QSpinBox {
                    /* padding: 6px 8px; */
                    /* border: 1px solid #CCCCCC; */
                    /* border-radius: 4px; */
                    /* background-color: #FFFFFF; */
                    /* color: #000000; */
                    /* font-size: 13px; */
                    /* selection-background-color: #007AFF; */
                    /* selection-color: #FFFFFF; */
                }
                
                QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                    /* border: 1px solid #007AFF; */
                    /* outline: none; */
                }
                
                QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {
                    /* background-color: #F2F2F2; */
                    /* color: #999999; */
                }
                
                /* Checkbox */
                QCheckBox {
                    /* spacing: 10px; */
                    /* font-size: 13px; */
                    /* color: #000000; */
                }
                
                QCheckBox::indicator {
                    /* width: 18px; */
                    /* height: 18px; */
                }
                
                QCheckBox::indicator:unchecked {
                    /* border: 1px solid #CCCCCC; */
                    /* background-color: #FFFFFF; */
                    /* border-radius: 4px; */
                }
                
                QCheckBox::indicator:unchecked:hover {
                    /* border: 1px solid #007AFF; */
                }
                
                QCheckBox::indicator:checked {
                    /* border: 1px solid #007AFF; */
                    /* background-color: #007AFF; */
                    /* border-radius: 4px; */
                }
                
                QCheckBox::indicator:checked:hover {
                    /* border: 1px solid #0062CC; */
                    /* background-color: #0062CC; */
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
        
        # Update control buttons visibility based on selected images count
        self.update_control_buttons_visibility()
    
    def update_control_buttons_visibility(self):
        # Show/hide control buttons based on selected images count
        if len(self.selected_images) > 0:
            self.delete_btn.setVisible(True)
            self.move_to_folder_btn.setVisible(True)
            self.embed_keywords_btn.setVisible(True)
            self.select_all_btn.setVisible(True)
            self.deselect_all_btn.setVisible(True)
            self.invert_selection_btn.setVisible(True)
            self.auto_tag_btn.setVisible(True)
            self.auto_tag_keywords_spin.setVisible(True)
            self.auto_tag_append_checkbox.setVisible(True)
        else:
            self.delete_btn.setVisible(False)
            self.move_to_folder_btn.setVisible(False)
            self.embed_keywords_btn.setVisible(False)
            self.select_all_btn.setVisible(False)
            self.deselect_all_btn.setVisible(False)
            self.invert_selection_btn.setVisible(False)
            self.auto_tag_btn.setVisible(False)
            self.auto_tag_keywords_spin.setVisible(False)
            self.auto_tag_append_checkbox.setVisible(False)
            self.auto_tag_stop_btn.setVisible(False)
    
    def delete_selected_images(self):
        # Delete selected images by moving them to trash
        if not self.selected_images:
            return
        
        # Import send2trash module
        try:
            from send2trash import send2trash
        except ImportError:
            QMessageBox.critical(self, "Error", "send2trash module not found. Please install it using 'pip install send2trash'")
            return
        
        # Confirm deletion
        reply = QMessageBox.question(self, "Confirm Delete",
                                   f"Are you sure you want to delete {len(self.selected_images)} selected image(s)?\n\n"
                                   "This action will move the file(s) to the trash/recycle bin and cannot be undone.",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            # Move each selected image to trash
            failed_files = []
            deleted_files = []
            for image_path in self.selected_images:
                try:
                    send2trash(image_path)
                    # Add to deleted files list
                    deleted_files.append(image_path)
                except Exception as e:
                    failed_files.append((image_path, str(e)))
            
            # Remove deleted images from grid layout
            for i in reversed(range(self.grid_layout.count())):
                widget = self.grid_layout.itemAt(i).widget()
                if widget and isinstance(widget, ClickableImageLabel):
                    if widget.image_path in deleted_files:
                        widget.setParent(None)
            
            # Remove deleted images from selected images list
            for image_path in deleted_files:
                self.selected_images.remove(image_path)
            
            # Update control buttons visibility
            self.update_control_buttons_visibility()
            
            # Show result message
            if failed_files:
                error_msg = "\n".join([f"{path}: {error}" for path, error in failed_files])
                QMessageBox.warning(self, "Delete Error", f"Failed to delete the following files:\n\n{error_msg}")
            else:
                QMessageBox.information(self, "Delete Success", f"Successfully deleted {len(deleted_files)} image(s).")
    
    def move_selected_images(self):
        # Move selected images to a selected folder
        if not self.selected_images:
            return
        
        # Import required modules
        import shutil
        import os
        
        # Select destination folder
        dest_folder = QFileDialog.getExistingDirectory(self, "Select Destination Folder")
        if not dest_folder:
            return
        
        # Confirm move operation
        reply = QMessageBox.question(self, "Confirm Move",
                                   f"Are you sure you want to move {len(self.selected_images)} selected image(s) to '{dest_folder}'?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            # Move each selected image to destination folder
            failed_files = []
            moved_files = []
            for image_path in self.selected_images:
                try:
                    # Get filename from path
                    filename = os.path.basename(image_path)
                    # Create destination path
                    dest_path = os.path.join(dest_folder, filename)
                    # Move file
                    shutil.move(image_path, dest_path)
                    # Add to moved files list
                    moved_files.append(image_path)
                except Exception as e:
                    failed_files.append((image_path, str(e)))
            
            # Remove moved images from grid layout
            for i in reversed(range(self.grid_layout.count())):
                widget = self.grid_layout.itemAt(i).widget()
                if widget and isinstance(widget, ClickableImageLabel):
                    if widget.image_path in moved_files:
                        widget.setParent(None)
            
            # Remove moved images from selected images list
            for image_path in moved_files:
                self.selected_images.remove(image_path)
            
            # Update control buttons visibility
            self.update_control_buttons_visibility()
            
            # Show result message
            if failed_files:
                error_msg = "\n".join([f"{path}: {error}" for path, error in failed_files])
                QMessageBox.warning(self, "Move Error", f"Failed to move the following files:\n\n{error_msg}")
            else:
                QMessageBox.information(self, "Move Success", f"Successfully moved {len(moved_files)} image(s) to '{dest_folder}'.")

    def embed_keywords_for_selected_images(self):
        if not self.selected_images:
            return

        text, ok = QInputDialog.getText(self, 'Embed Keywords',
                                          'Enter keywords (comma-separated):')

        if ok and text:
            keywords = [k.strip() for k in text.split(',')]
            if not keywords:
                return

            failed_files = []
            success_count = 0
            for image_path in self.selected_images:
                if embed_keywords_in_exif(image_path, keywords):
                    success_count += 1
                else:
                    failed_files.append(image_path)

            if failed_files:
                error_msg = "\n".join(failed_files)
                QMessageBox.warning(self, "Embedding Error", f"Failed to embed keywords in the following files:\n\n{error_msg}")
            
            if success_count > 0:
                QMessageBox.information(self, "Embedding Success", f"Successfully embedded keywords in {success_count} image(s).")

    def select_all_images(self):
        # Select all images in the preview window
        selected_count = 0
        for i in range(self.grid_layout.count()):
            widget = self.grid_layout.itemAt(i).widget()
            if isinstance(widget, ClickableImageLabel) and widget.image_path:
                # Check if image is not already selected
                if widget.image_path not in self.selected_images:
                    # Add to selected images list
                    self.selected_images.append(widget.image_path)
                    selected_count += 1
                
                # Set widget as selected
                widget.setSelected(True)
        
        # Update status label
        self.status_label.setText(f"Selected {selected_count} image(s). {len(self.selected_images)} images selected in total.")
        
        # Update control buttons visibility
        self.update_control_buttons_visibility()

    def deselect_all_images(self):
        # Deselect all images in the preview window
        deselected_count = 0
        for i in range(self.grid_layout.count()):
            widget = self.grid_layout.itemAt(i).widget()
            if isinstance(widget, ClickableImageLabel) and widget.image_path:
                # Check if image is currently selected
                if widget.image_path in self.selected_images:
                    # Remove from selected images list
                    self.selected_images.remove(widget.image_path)
                    deselected_count += 1
                
                # Set widget as deselected
                widget.setSelected(False)
        
        # Update status label
        self.status_label.setText(f"Deselected {deselected_count} image(s). {len(self.selected_images)} images selected in total.")
        
        # Update control buttons visibility
        self.update_control_buttons_visibility()

    def invert_selection(self):
        # Invert selection of all images in the preview window
        inverted_count = 0
        for i in range(self.grid_layout.count()):
            widget = self.grid_layout.itemAt(i).widget()
            if isinstance(widget, ClickableImageLabel) and widget.image_path:
                # Check if image is currently selected
                if widget.image_path in self.selected_images:
                    # Remove from selected images list
                    self.selected_images.remove(widget.image_path)
                    # Set widget as deselected
                    widget.setSelected(False)
                else:
                    # Add to selected images list
                    self.selected_images.append(widget.image_path)
                    # Set widget as selected
                    widget.setSelected(True)
                    inverted_count += 1
        
        # Update status label
        self.status_label.setText(f"Inverted selection of {inverted_count} image(s). {len(self.selected_images)} images selected in total.")
        
        # Update control buttons visibility
        self.update_control_buttons_visibility()

    def start_auto_tagging(self):
        """Start auto-tagging selected images."""
        if not self.selected_images:
            QMessageBox.warning(self, "No Selection", "Please select images to auto-tag.")
            return
        
        # Check if auto-tag worker is already running
        if self.auto_tag_worker is not None and self.auto_tag_worker.is_running():
            QMessageBox.warning(self, "Worker Busy", "Auto-tagging is already in progress.")
            return
        
        # Get settings from UI
        num_keywords = self.auto_tag_keywords_spin.value()
        append_mode = self.auto_tag_append_checkbox.isChecked()
        ollama_host = self.api_url_edit.text().rstrip("/")
        vision_model = self.vision_model_edit.text()
        
        # Create and start worker
        self.auto_tag_worker = AutoTagWorker(
            image_paths=self.selected_images.copy(),
            num_keywords=num_keywords,
            append_mode=append_mode,
            ollama_host=ollama_host,
            vision_model=vision_model
        )
        
        # Connect signals
        self.auto_tag_worker.progress_update.connect(self.update_status_and_log)
        self.auto_tag_worker.progress_info.connect(self.update_progress_info)
        self.auto_tag_worker.image_tagged.connect(self.on_image_tagged)
        self.auto_tag_worker.tagging_finished.connect(self.on_tagging_finished)
        
        # Update UI state
        self.auto_tag_btn.setEnabled(False)
        self.auto_tag_stop_btn.setEnabled(True)
        self.auto_tag_stop_btn.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(len(self.selected_images))
        
        self.status_label.setText(f"Starting auto-tagging of {len(self.selected_images)} images...")
        self.auto_tag_worker.start()

    def stop_auto_tagging(self):
        """Stop the auto-tagging process."""
        if self.auto_tag_worker is not None and self.auto_tag_worker.is_running():
            self.auto_tag_worker.stop()
            self.status_label.setText("Stopping auto-tagging...")
            self.auto_tag_stop_btn.setEnabled(False)

    def on_image_tagged(self, filepath: str, keywords: list):
        """Called when an image is successfully tagged."""
        logger.debug(f"Image tagged: {filepath} with {len(keywords)} keywords")

    def on_tagging_finished(self, success_count: int, failed_count: int):
        """Called when auto-tagging is complete."""
        self.auto_tag_btn.setEnabled(True)
        self.auto_tag_stop_btn.setEnabled(False)
        self.auto_tag_stop_btn.setVisible(False)
        self.progress_bar.setVisible(False)
        
        msg = f"Auto-tagging complete. Success: {success_count}, Failed: {failed_count}"
        self.status_label.setText(msg)
        
        if success_count > 0:
            QMessageBox.information(self, "Auto-Tag Complete", msg)

    def closeEvent(self, event: QCloseEvent):
        """Handle the close event to ensure proper shutdown."""
        logger.debug("Close event received")
        if self.worker is not None and self.worker.is_running():
            logger.debug("Worker is running, stopping it...")
            # Stop the worker if it's running
            self.status_label.setText("Stopping worker thread...")
            self.worker.stop()
            # Wait for the worker to finish (with a longer timeout)
            logger.debug("Waiting for worker to finish...")
            self.worker.wait(10000)  # Wait up to 10 seconds
            logger.debug("Worker finished or timeout reached")
            # Set worker to None after stopping
            self.worker = None
        
        # Stop Smart Search workers if running
        if self.index_worker is not None and self.index_worker.is_running():
            self.index_worker.stop()
            self.index_worker.wait(5000)
        if self.search_worker is not None and self.search_worker.isRunning():
            self.search_worker.wait(5000)
        
        # Stop Auto-Tag worker if running
        if self.auto_tag_worker is not None and self.auto_tag_worker.is_running():
            self.auto_tag_worker.stop()
            self.auto_tag_worker.wait(5000)
        
        # Cleanup thumbnail cache
        try:
            cache = get_thumbnail_cache()
            cache.cleanup_disk_cache()
            logger.debug(f"Cache stats: {cache.get_stats()}")
        except Exception as e:
            logger.warning(f"Error cleaning up thumbnail cache: {e}")
        
        # Accept the close event to allow the application to close
        logger.debug("Accepting close event")
        event.accept()
    
    def resizeEvent(self, event):
        # Update the grid layout when the window is resized
        self.update_grid_layout()
        super().resizeEvent(event)
    
    # ========== Smart Search Methods ==========
    
    def ss_browse_folder(self):
        """Browse for folder to index."""
        folder = QFileDialog.getExistingDirectory(self, "Select Image Folder for Indexing")
        if folder:
            self.smart_search_folder = folder
            self.ss_folder_label.setText(folder)
        else:
            self.ss_folder_label.setText("No folder selected")
    
    def ss_start_indexing(self):
        """Start the image indexing process."""
        if not self.smart_search_folder or not os.path.isdir(self.smart_search_folder):
            QMessageBox.warning(self, "No Folder", "Please select a valid folder containing images.")
            return
        
        # Check if worker is already running
        if self.index_worker is not None and self.index_worker.is_running():
            QMessageBox.warning(self, "Indexing in Progress", "Please wait for the current indexing to finish.")
            return
        
        # Get Ollama host from settings
        ollama_host = self.api_url_edit.text().rstrip("/")
        if ollama_host.endswith("/api/generate"):
            ollama_host = ollama_host[:-len("/api/generate")]
        if ollama_host.endswith("/api/tags"):
            ollama_host = ollama_host[:-len("/api/tags")]
        
        include_subfolders = self.ss_include_subfolder_checkbox.isChecked()
        
        # Clear previous results
        for i in reversed(range(self.ss_grid_layout.count())):
            widget = self.ss_grid_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        # Update UI state
        self.ss_index_btn.setEnabled(False)
        self.ss_stop_index_btn.setEnabled(True)
        self.ss_progress_bar.setVisible(True)
        self.ss_progress_bar.setValue(0)
        
        # Get model names from settings
        vision_model = self.vision_model_edit.text()
        embedding_model = self.embedding_model_edit.text()
        
        # Create and start worker
        self.index_worker = IndexWorker(self.smart_search_folder, include_subfolders, ollama_host, 
                                        vision_model, embedding_model)
        self.index_worker.progress_update.connect(self.ss_on_progress_update)
        self.index_worker.progress_info.connect(self.ss_on_progress_info)
        self.index_worker.indexing_finished.connect(self.ss_on_indexing_finished)
        self.index_worker.error_occurred.connect(self.ss_on_error)
        self.index_worker.start()
        
        logger.debug("IndexWorker started")
    
    def ss_stop_indexing(self):
        """Stop the indexing process."""
        if self.index_worker is not None and self.index_worker.is_running():
            self.index_worker.stop()
            self.ss_status_label.setText("Stopping indexing...")
            self.ss_stop_index_btn.setEnabled(False)
    
    def ss_on_progress_update(self, message: str):
        """Handle progress update from worker."""
        self.ss_status_label.setText(message)
    
    def ss_on_progress_info(self, current: int, total: int, skipped: int, eta_seconds: float):
        """Handle progress info from worker."""
        self.ss_progress_bar.setMaximum(total)
        self.ss_progress_bar.setValue(current)
        
        if eta_seconds > 0:
            if eta_seconds < 60:
                eta_str = f"{eta_seconds:.0f}s"
            elif eta_seconds < 3600:
                eta_str = f"{eta_seconds/60:.1f}m"
            else:
                eta_str = f"{eta_seconds/3600:.1f}h"
            self.ss_progress_info.setText(f"{current}/{total} (Skipped: {skipped}) - ETA: {eta_str}")
        else:
            self.ss_progress_info.setText(f"{current}/{total} (Skipped: {skipped})")
    
    def ss_on_indexing_finished(self, indexed_count: int, skipped_count: int):
        """Handle indexing completion."""
        self.ss_index_btn.setEnabled(True)
        self.ss_stop_index_btn.setEnabled(False)
        self.ss_progress_bar.setVisible(False)
        self.ss_status_label.setText(f"Indexing complete. Indexed: {indexed_count}, Skipped: {skipped_count}")
        self.ss_progress_info.setText("")
        
        if indexed_count == 0 and skipped_count == 0:
            QMessageBox.information(self, "No Images", "No images were found in the selected folder.")
        else:
            QMessageBox.information(self, "Indexing Complete", 
                                    f"Successfully indexed {indexed_count} new image(s).\nSkipped {skipped_count} already indexed image(s).")
    
    def ss_on_error(self, error_message: str):
        """Handle error from worker."""
        self.ss_status_label.setText(f"Error: {error_message}")
        QMessageBox.critical(self, "Error", error_message)
    
    def ss_start_search(self):
        """Start the search process."""
        query = self.ss_search_edit.text().strip()
        if not query:
            QMessageBox.warning(self, "No Query", "Please enter a search query.")
            return
        
        # Check if search worker is already running
        if self.search_worker is not None and self.search_worker.isRunning():
            QMessageBox.warning(self, "Search in Progress", "Please wait for the current search to finish.")
            return
        
        # Get Ollama host from settings
        ollama_host = self.api_url_edit.text().rstrip("/")
        if ollama_host.endswith("/api/generate"):
            ollama_host = ollama_host[:-len("/api/generate")]
        if ollama_host.endswith("/api/tags"):
            ollama_host = ollama_host[:-len("/api/tags")]
        
        # Calculate distance threshold from strictness slider
        # Slider: 1 (loose) to 10 (strict)
        # Threshold: 1.5 (loose) to 0.3 (strict)
        strictness = self.ss_strictness_slider.value()
        distance_threshold = 1.5 - (strictness - 1) * (1.5 - 0.3) / 9
        
        # Clear previous results
        for i in reversed(range(self.ss_grid_layout.count())):
            widget = self.ss_grid_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        # Update UI
        self.ss_search_btn.setEnabled(False)
        self.ss_status_label.setText(f"Searching (threshold: {distance_threshold:.2f})...")
        
        # Get embedding model from settings
        embedding_model = self.embedding_model_edit.text()
        
        # Create and start search worker with distance threshold
        self.search_worker = SearchWorker(query, limit=50, ollama_host=ollama_host, 
                                          distance_threshold=distance_threshold,
                                          embedding_model=embedding_model)
        self.search_worker.status_update.connect(self.ss_on_search_status)
        self.search_worker.search_complete.connect(self.ss_on_search_complete)
        self.search_worker.search_error.connect(self.ss_on_search_error)
        self.search_worker.start()
        
        logger.debug(f"SearchWorker started with query: {query}, threshold: {distance_threshold}")
    
    def ss_on_search_status(self, message: str):
        """Handle search status update."""
        self.ss_status_label.setText(message)
    
    def ss_on_search_complete(self, results: list):
        """Handle search completion and display results."""
        self.ss_search_btn.setEnabled(True)
        
        # Cache all results for real-time filtering
        self.cached_search_results = results
        
        if not results:
            self.ss_status_label.setText("No matching images found.")
            return
        
        # Display results using current strictness threshold
        self.ss_filter_cached_results()
    
    def ss_filter_cached_results(self):
        """Filter and display cached search results based on current strictness slider value."""
        if not self.cached_search_results:
            return
        
        # Calculate distance threshold from strictness slider
        strictness = self.ss_strictness_slider.value()
        distance_threshold = 1.5 - (strictness - 1) * (1.5 - 0.3) / 9
        
        # Filter results by distance threshold
        filtered_results = [
            result for result in self.cached_search_results 
            if result.get('_distance', 0) <= distance_threshold
        ]
        
        # Clear previous results
        for i in reversed(range(self.ss_grid_layout.count())):
            widget = self.ss_grid_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        if not filtered_results:
            self.ss_status_label.setText(f"No images match current strictness (threshold: {distance_threshold:.2f}). Try lowering strictness.")
            return
        
        self.ss_status_label.setText(f"Found {len(filtered_results)} matching image(s) (threshold: {distance_threshold:.2f}).")
        
        # Display results in grid
        thumbnail_size = self.ss_thumbnail_slider.value()
        scroll_width = self.ss_scroll_area.viewport().width()
        padding = 10
        columns = max(1, scroll_width // (thumbnail_size + padding))
        
        for i, result in enumerate(filtered_results):
            filepath = result.get('filepath', '')
            if not filepath or not os.path.exists(filepath):
                continue
            
            label = ClickableImageLabel(filepath)
            pixmap = QPixmap(filepath)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(thumbnail_size, thumbnail_size, 
                                       Qt.AspectRatioMode.KeepAspectRatio, 
                                       Qt.TransformationMode.SmoothTransformation)
                label.setPixmap(pixmap)
                label.setFixedSize(thumbnail_size, thumbnail_size)
                # Add tooltip with description and distance
                description = result.get('description', '')
                distance = result.get('_distance', 0)
                if description:
                    label.setToolTip(f"{os.path.basename(filepath)}\nDistance: {distance:.3f}\n\n{description[:200]}...")
            else:
                label.setText("Failed to load")
            
            row, col = divmod(i, columns)
            self.ss_grid_layout.addWidget(label, row, col)
    
    def ss_on_search_error(self, error_message: str):
        """Handle search error."""
        self.ss_search_btn.setEnabled(True)
        self.ss_status_label.setText(f"Search error: {error_message}")
        QMessageBox.critical(self, "Search Error", error_message)
    
    def ss_update_thumbnail_size(self, size: int):
        """Update thumbnail sizes in search results."""
        for i in range(self.ss_grid_layout.count()):
            widget = self.ss_grid_layout.itemAt(i).widget()
            if isinstance(widget, ClickableImageLabel):
                widget.updatePixmapWithSize(size)
        
        # Re-layout the grid
        scroll_width = self.ss_scroll_area.viewport().width()
        padding = 10
        columns = max(1, scroll_width // (size + padding))
        
        widgets = []
        for i in range(self.ss_grid_layout.count()):
            widget = self.ss_grid_layout.itemAt(i).widget()
            if widget:
                widgets.append(widget)
        
        for i in reversed(range(self.ss_grid_layout.count())):
            widget = self.ss_grid_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        for i, widget in enumerate(widgets):
            row, col = divmod(i, columns)
            self.ss_grid_layout.addWidget(widget, row, col)
    
    def ss_update_strictness_label(self, value: int):
        """Update the strictness label based on slider value."""
        if value <= 2:
            label = "Very Loose"
        elif value <= 4:
            label = "Loose"
        elif value <= 6:
            label = "Moderate"
        elif value <= 8:
            label = "Strict"
        else:
            label = "Very Strict"
        
        # Calculate and show threshold value
        threshold = 1.5 - (value - 1) * (1.5 - 0.3) / 9
        self.ss_strictness_label.setText(f"{label} ({threshold:.2f})")