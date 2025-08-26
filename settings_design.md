# ระบบการบันทึกและโหลดการตั้งค่า

## โครงสร้างไฟล์การตั้งค่า

ไฟล์: `app_settings.json`

```json
{
  "ollama_url": "http://192.168.50.55:11434",
  "selected_model": "gemma3:4b-it-qat",
  "temperature": 0,
  "max_workers": 4
}
```

## ฟังก์ชันที่จำเป็น

### 1. บันทึกการตั้งค่า
```python
def save_settings(self):
    settings = {
        "ollama_url": self.ollama_url_edit.text(),
        "selected_model": self.model_combo.currentText(),
        "temperature": self.temp_spin.value(),
        "max_workers": self.max_workers_spin.value()
    }
    
    with open("app_settings.json", "w") as f:
        json.dump(settings, f, indent=2)
```

### 2. โหลดการตั้งค่า
```python
def load_settings(self):
    try:
        with open("app_settings.json", "r") as f:
            settings = json.load(f)
        
        self.ollama_url_edit.setText(settings.get("ollama_url", self.OLLAMA_API_URL))
        self.temp_spin.setValue(settings.get("temperature", 0))
        self.max_workers_spin.setValue(settings.get("max_workers", 4))
        
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
```

### 3. ปรับปรุง fetch_ollama_models
```python
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
```

### 4. เพิ่มการยืนยันการบันทึกเมื่อเลือกโมเดลใหม่
```python
def on_model_changed(self):
    reply = QMessageBox.question(self, 'บันทึกการตั้งค่า', 
                                'คุณต้องการบันทึกการตั้งค่าโมเดลนี้เป็นค่าเริ่มต้นหรือไม่?',
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.Yes)
    
    if reply == QMessageBox.StandardButton.Yes:
        self.save_settings()
        self.model_label.setText(f"Model: {self.model_combo.currentText()}")
        QMessageBox.information(self, 'บันทึกการตั้งค่า', 'บันทึกการตั้งค่าโมเดลเรียบร้อยแล้ว')