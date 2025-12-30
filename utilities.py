import base64
import json
import requests
from PIL import Image, PngImagePlugin
import io
import os
import piexif
from piexif import helper
from iptcinfo3 import IPTCInfo
from urllib.parse import urlparse, urljoin

def read_existing_keywords(image_path: str) -> list[str]:
    """
    Reads existing keywords from EXIF and IPTC metadata of a JPEG or PNG image.
    Returns a list of unique keywords found.
    """
    keywords = set()
    
    try:
        if image_path.lower().endswith(('.jpg', '.jpeg')):
            # Read IPTC keywords
            try:
                info = IPTCInfo(image_path, force=True)
                iptc_keywords = info.get('keywords', [])
                if iptc_keywords:
                    for kw in iptc_keywords:
                        if isinstance(kw, bytes):
                            kw = kw.decode('utf-8', errors='ignore')
                        keywords.add(kw.strip())
            except Exception as e:
                print(f"Error reading IPTC keywords from {image_path}: {e}")
            
            # Read EXIF XPKeywords
            try:
                exif_dict = piexif.load(image_path)
                xp_keywords = exif_dict.get("0th", {}).get(piexif.ImageIFD.XPKeywords)
                if xp_keywords:
                    if isinstance(xp_keywords, bytes):
                        # XPKeywords is UTF-16LE encoded
                        keyword_string = xp_keywords.decode('utf-16le').rstrip('\x00')
                        for kw in keyword_string.split(';'):
                            keywords.add(kw.strip())
            except Exception as e:
                print(f"Error reading EXIF keywords from {image_path}: {e}")
                
        elif image_path.lower().endswith('.png'):
            # Read PNG tEXt Keywords
            try:
                img = Image.open(image_path)
                png_keywords = img.info.get('Keywords', '')
                if png_keywords:
                    for kw in png_keywords.split(','):
                        keywords.add(kw.strip())
                img.close()
            except Exception as e:
                print(f"Error reading PNG keywords from {image_path}: {e}")
    except Exception as e:
        print(f"Error reading keywords from {image_path}: {e}")
    
    return list(keywords)


def embed_keywords_in_exif(image_path: str, keywords: list[str]) -> bool:
    """
    Embeds a list of keywords into the IPTC and EXIF data of a JPEG or PNG image,
    preserving the original file's modification and access times.
    For JPEG, it uses both IPTC 'keywords' and EXIF 'XPKeywords'.
    For PNG, it creates a tEXt chunk.
    """
    try:
        # 1. Store original file timestamps
        stat = os.stat(image_path)
        original_atime = stat.st_atime
        original_mtime = stat.st_mtime

        # For JPEG files
        if image_path.lower().endswith(('.jpg', '.jpeg')):
            # ---- IPTC writing ----
            try:
                info = IPTCInfo(image_path, force=True)
                # Encode keywords to bytes, as required by iptcinfo3
                encoded_keywords = [k.encode('utf-8') for k in keywords]
                info['keywords'] = encoded_keywords
                info.save()
            except Exception as e:
                print(f"Error writing IPTC data to {image_path}: {e}")
                # We can choose to continue to write EXIF data or return False
                # For now, let's print the error and continue

            # ---- EXIF writing (for Windows compatibility) ----
            try:
                exif_dict = piexif.load(image_path)
            except (piexif.InvalidImageDataError, ValueError):
                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

            keyword_string = ";".join(keywords)
            xp_keywords_bytes = keyword_string.encode('utf-16le') + b'\x00\x00'
            exif_dict["0th"][piexif.ImageIFD.XPKeywords] = xp_keywords_bytes
            
            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, image_path)

        # For PNG files (PNG does not support standard EXIF/IPTC well)
        elif image_path.lower().endswith('.png'):
            img = Image.open(image_path)
            png_info = PngImagePlugin.PngInfo()
            if img.info:
                for key, value in img.info.items():
                    png_info.add_text(key, value)
            
            keyword_string = ", ".join(keywords)
            png_info.add_text('Keywords', keyword_string)
            
            img.save(image_path, "PNG", pnginfo=png_info)
            
        else:
            print(f"Unsupported file format for metadata embedding: {image_path}")
            return False

        # 2. Restore original file timestamps
        os.utime(image_path, (original_atime, original_mtime))
            
        return True
    except Exception as e:
        print(f"Error embedding keywords in {image_path}: {e}")
        return False

def resize_and_encode_image(image_path: str, max_size: int = 640, quality: int = 85) -> str | None:
    """
    Resizes an image to a max size, converts it to base64, and handles quality for JPEGs.
    """
    try:
        with Image.open(image_path) as img:
            # Preserve aspect ratio
            img.thumbnail((max_size, max_size))
            
            # Save to a byte buffer
            buffer = io.BytesIO()
            img_format = img.format
            
            if img_format == 'JPEG':
                img.save(buffer, format='JPEG', quality=quality)
            else:
                # For PNG and other formats, save without quality setting
                img.save(buffer, format=img_format or 'PNG')
                
            # Encode to base64
            encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return encoded
    except Exception as e:
        print(f"Error processing image {image_path}: {e}")
        return None

def detect_api_type(api_url: str) -> str:
    """
    ตรวจจับประเภทของ API โดยอัตโนมัติ
    คืนค่า "ollama", "openai" หรือ "unknown"
    """
    try:
        # แยก endpoint ออกจาก URL
        parsed_url = urlparse(api_url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        
        # ลองเรียก endpoint ของ Ollama API
        try:
            url = urljoin(base_url, "/api/tags")
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
            url = urljoin(base_url, "/v1/models")
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                # ตรวจสอบโครงสร้างข้อมูลของ API ที่เข้ากันได้กับ OpenAI
                if 'data' in data:
                    return "openai"
        except:
            pass
        
        return "unknown"
    except Exception as e:
        print(f"Error detecting API type: {e}")
        return "unknown"

def ask_api_about_image(api_url: str, model_name: str, image_base64: str, user_prompt_object: str, temp: float, api_type: str, session: requests.Session = None) -> bool:
    # ตรวจจับประเภทของ API หากไม่ได้ระบุ
    if api_type == "unknown":
        api_type = detect_api_type(api_url)
    
    # แยก endpoint ออกจาก URL
    parsed_url = urlparse(api_url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    
    # Use the provided session or the default requests module
    requester = session if session else requests

    if api_type == "ollama":
        # ใช้ endpoint ของ Ollama API
        url = urljoin(base_url, "/api/generate")
        payload = {
            "model": model_name,
            "prompt": f"Analyze the provided image carefully. Does this image contain a {user_prompt_object}? Please answer with only 'YES' or 'NO'.",
            "images": [image_base64],
            "stream": False,
            "options": {"temperature": temp}
        }
        try:
            response = requester.post(
                url,
                json=payload,
                timeout=90
            )
            response.raise_for_status()
            data = response.json()
            answer = data.get("response", "").strip().upper()
            # Debug: แสดงคำตอบจาก API
            print(f"[DEBUG] API Response: '{answer}'")
            # ปรับ logic: ตรวจสอบว่าคำตอบขึ้นต้นด้วย YES หรือมี YES เป็นคำแรก
            # หรือตอบ YES โดยไม่มี NO นำหน้า
            answer_words = answer.split()
            if answer_words:
                first_word = answer_words[0].strip('.,!?')
                is_yes = first_word == "YES" or (first_word.startswith("YES") and not first_word.startswith("NO"))
                # ถ้าคำแรกไม่ชัด ให้ตรวจสอบว่ามี YES อยู่และไม่มี NO อยู่
                if not is_yes:
                    is_yes = "YES" in answer and "NO" not in answer
                return is_yes
            return False
        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            print(f"Ollama API error: {e}")
            return False
    elif api_type == "openai":
        # ใช้ endpoint ของ API ที่เข้ากันได้กับ OpenAI
        url = urljoin(base_url, "/v1/chat/completions")
        headers = {
            "Content-Type": "application/json"
        }
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Analyze the provided image carefully. Does this image contain a {user_prompt_object}? Please answer with only 'YES' or 'NO'."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            "temperature": temp,
            "max_tokens": 10
        }
        try:
            response = requester.post(
                url,
                headers=headers,
                json=payload,
                timeout=90
            )
            response.raise_for_status()
            data = response.json()
            answer = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip().upper()
            # Debug: แสดงคำตอบจาก API
            print(f"[DEBUG] OpenAI API Response: '{answer}'")
            # ปรับ logic: ตรวจสอบว่าคำตอบขึ้นต้นด้วย YES หรือมี YES เป็นคำแรก
            answer_words = answer.split()
            if answer_words:
                first_word = answer_words[0].strip('.,!?')
                is_yes = first_word == "YES" or (first_word.startswith("YES") and not first_word.startswith("NO"))
                # ถ้าคำแรกไม่ชัด ให้ตรวจสอบว่ามี YES อยู่และไม่มี NO อยู่
                if not is_yes:
                    is_yes = "YES" in answer and "NO" not in answer
                return is_yes
            return False
        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            print(f"OpenAI API error: {e}")
            return False
    else:
        print(f"Unknown API type: {api_type}")
        return False