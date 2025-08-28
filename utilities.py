import base64
import json
import requests
from PIL import Image, PngImagePlugin
import io
import os
import piexif
from piexif import helper
from iptcinfo3 import IPTCInfo

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

def resize_and_encode_image(image_path: str, max_size: int = 1024, quality: int = 85) -> str | None:
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