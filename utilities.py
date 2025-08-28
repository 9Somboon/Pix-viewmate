import base64
import json
import requests
from PIL import Image
import io
import piexif
from piexif import helper

def embed_keywords_in_exif(image_path: str, keywords: list[str]) -> bool:
    """
    Embeds a list of keywords into the EXIF data of a JPEG or PNG image.
    For JPEG, it uses the XPKeywords tag.
    For PNG, it creates a tEXt chunk.
    """
    try:
        # For JPEG files
        if image_path.lower().endswith(('.jpg', '.jpeg')):
            try:
                exif_dict = piexif.load(image_path)
            except piexif.InvalidImageDataError:
                # If no EXIF data exists, create an empty dictionary
                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

            # XPKeywords uses UTF-16LE encoding. Each character is 2 bytes.
            # The keywords are joined by semicolons.
            keyword_string = ";".join(keywords)
            # Encode to bytes and add a null terminator
            xp_keywords_bytes = keyword_string.encode('utf-16le') + b'\x00\x00'
            
            # Add to the '0th' IFD (Image File Directory)
            exif_dict["0th"][piexif.ImageIFD.XPKeywords] = xp_keywords_bytes
            
            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, image_path)

        # For PNG files
        elif image_path.lower().endswith('.png'):
            img = Image.open(image_path)
            
            # Create a tEXt chunk for keywords
            keyword_string = ", ".join(keywords)
            
            # PIL's PngInfo object can be used to add text chunks
            png_info = img.info or {}
            png_info['Keywords'] = keyword_string
            
            # Save the image with the new metadata
            img.save(image_path, "PNG", pnginfo=png_info)
            
        else:
            print(f"Unsupported file format for EXIF embedding: {image_path}")
            return False
            
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