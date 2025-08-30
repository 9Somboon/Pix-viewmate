# แผนการปรับปรุงระบบการส่งข้อมูลไปยัง API สำหรับประมวลผลภาพ

## 1. เพิ่มฟังก์ชัน detect_api_type() ใน utilities.py

### รายละเอียดฟังก์ชัน:
- ชื่อฟังก์ชัน: `detect_api_type(api_url)`
- พารามิเตอร์: `api_url` (string) - URL ของ API
- ค่าที่คืน: "ollama", "openai" หรือ "unknown"

### ตรรกะของฟังก์ชัน:
1. ลบ endpoint ที่เฉพาะเจาะจงออกจาก `api_url` (เช่น `/api/generate`, `/v1/chat/completions`)
2. ลองเรียก endpoint ของ Ollama API (`/api/tags`) ด้วย timeout สั้น ๆ
3. หากสำเร็จ ตรวจสอบ headers และโครงสร้างข้อมูลเพื่อยืนยันว่าเป็น Ollama API
4. หากไม่ใช่ Ollama API ลองเรียก endpoint ของ API ที่เข้ากันได้กับ OpenAI (`/v1/models`) ด้วย timeout สั้น ๆ
5. หากสำเร็จ ตรวจสอบ headers และโครงสร้างข้อมูลเพื่อยืนยันว่าเป็น API ที่เข้ากันได้กับ OpenAI
6. หากทั้งสองวิธีไม่สำเร็จ คืนค่า "unknown"

## 2. ปรับปรุงฟังก์ชัน ask_ollama_about_image() ให้สามารถทำงานกับทั้ง Ollama API และ API ที่เข้ากันได้กับ OpenAI

### รายละเอียดฟังก์ชัน:
- ชื่อฟังก์ชัน: `ask_api_about_image(api_url, model_name, image_base64, user_prompt_object, temp, api_type)`
- พารามิเตอร์เพิ่มเติม: `api_type` (string) - ประเภทของ API ("ollama" หรือ "openai")

### ตรรกะของฟังก์ชัน:
1. ตรวจสอบ `api_type` เพื่อเลือกวิธีการส่ง request:
   - สำหรับ "ollama": ใช้ endpoint `/api/generate` และ payload เดิม
   - สำหรับ "openai": ใช้ endpoint `/v1/chat/completions` และ payload ที่เหมาะสมกับ OpenAI API
2. ปรับปรุงการประมวลผล response ให้เหมาะสมกับแต่ละประเภทของ API

## 3. ปรับปรุง worker.py ให้สามารถส่งข้อมูลไปยัง endpoint ที่เหมาะสมตามประเภทของ API

### การเปลี่ยนแปลงที่ต้องทำ:
1. เพิ่มพารามิเตอร์ `api_type` ให้กับคลาส `FilterWorker`
2. ปรับปรุงเมธอด `process_image()` ให้เรียกฟังก์ชัน `ask_api_about_image()` แทน `ask_ollama_about_image()`
3. ส่งค่า `api_type` ไปยังฟังก์ชัน `ask_api_about_image()`

## 4. ทดสอบการส่งข้อมูลไปยังทั้ง Ollama API และ API ที่เข้ากันได้กับ OpenAI

### แผนการทดสอบ:
1. ทดสอบกับ Ollama API:
   - ป้อน URL ของ Ollama API
   - ตรวจสอบว่าสามารถส่งข้อมูลไปยัง endpoint `/api/generate` ได้สำเร็จ
   - ตรวจสอบว่าได้รับ response ที่ถูกต้องจาก Ollama API

2. ทดสอบกับ API ที่เข้ากันได้กับ OpenAI:
   - ป้อน URL ของ API ที่เข้ากันได้กับ OpenAI
   - ตรวจสอบว่าสามารถส่งข้อมูลไปยัง endpoint `/v1/chat/completions` ได้สำเร็จ
   - ตรวจสอบว่าได้รับ response ที่ถูกต้องจาก API ที่เข้ากันได้กับ OpenAI

3. ทดสอบกับ URL ที่ไม่ถูกต้อง:
   - ป้อน URL ที่ไม่ถูกต้อง
   - ตรวจสอบว่าระบบแสดงข้อความข้อผิดพลาดอย่างเหมาะสม