import base64
import json
import requests
from PIL import Image
import io

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