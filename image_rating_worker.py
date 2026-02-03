# Image Rating Worker
# Background worker for rating images using Vision model for stock photography

import os
import threading
import time
import logging
import json
import re
import base64
import requests
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt6.QtCore import QThread, pyqtSignal
from PIL import Image
from config import OLLAMA_HOST, VISION_MODEL, MAX_IMAGE_SIZE

# Setup logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Rating criteria weights
RATING_WEIGHTS = {
    'technical': 0.25,      # 25%
    'composition': 0.20,    # 20%
    'commercial': 0.25,     # 25%
    'uniqueness': 0.15,     # 15%
    'editorial': 0.15       # 15%
}

# Rating prompt template
RATING_PROMPT = """You are a professional stock photography evaluator. Analyze this SPECIFIC image for commercial stock sales potential.

IMPORTANT: Evaluate THIS image carefully and give honest, varied scores based on what you actually see. Do NOT always give the same scores.

Rate each criterion from 1-10 (be honest and critical - scores should vary based on actual quality):
1. Technical Quality: sharpness, focus, noise level, lighting, exposure
2. Composition: rule of thirds, framing, balance, visual flow
3. Commercial Appeal: market demand, versatility, usability in ads/articles
4. Uniqueness: fresh perspective, not oversaturated in stock libraries
5. Editorial Value: storytelling, emotion, clear context

AI DEFECTS CHECK (for AI-generated images):
Look for common AI generation artifacts that would make the image unsellable:
- Extra or missing fingers/limbs
- Unnatural anatomy (twisted limbs, wrong proportions)
- Melted or distorted faces/hands
- Text/watermark artifacts
- Impossible physics or perspectives
- Blurry areas that should be sharp

Respond ONLY with valid JSON:
{
    "technical": <score 1-10>,
    "composition": <score 1-10>,
    "commercial": <score 1-10>,
    "uniqueness": <score 1-10>,
    "editorial": <score 1-10>,
    "defects": ["list", "of", "defects", "found"],
    "categories": ["category1", "category2"],
    "notes": "Specific feedback for THIS image"
}"""


def get_prompt_hash(prompt: str) -> str:
    """
    Generate a hash of the prompt for change detection.
    """
    import hashlib
    return hashlib.md5(prompt.encode('utf-8')).hexdigest()[:16]


def apply_echo_prompt(prompt: str) -> str:
    """
    Apply EchoPrompt technique: duplicate the prompt at the end.
    Research shows this improves LLM accuracy by up to 76%.
    """
    return f"{prompt}\n\n---\n\n{prompt}"


def resize_and_encode_image(image_path: str, max_size: int = MAX_IMAGE_SIZE) -> str | None:
    """
    Resize and encode image to base64 for sending to Vision API.
    """
    try:
        with Image.open(image_path) as img:
            # Convert to RGB if necessary
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            # Resize maintaining aspect ratio
            img.thumbnail((max_size, max_size))
            
            # Save to buffer as JPEG
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=85)
            
            # Encode to base64
            return base64.b64encode(buffer.getvalue()).decode('utf-8')
    except Exception as e:
        logger.error(f"Error processing image {image_path}: {e}")
        return None


def parse_rating_response(response_text: str) -> dict | None:
    """
    Parse JSON response from Vision model.
    Handles various response formats and extracts rating data.
    Due to EchoPrompt technique, we need to find the LAST JSON match
    (the actual response, not the example in the prompt).
    """
    # Find ALL JSON matches and use the LAST one (actual response, not prompt example)
    all_json_matches = []
    
    # Try to find JSON objects with "technical" field
    for match in re.finditer(r'\{[^{}]*"technical"[^{}]*\}', response_text, re.DOTALL):
        all_json_matches.append(match.group(0))
    
    # Try direct JSON parse on the last match first (most likely to be the response)
    for json_str in reversed(all_json_matches):
        try:
            data = json.loads(json_str)
            result = validate_rating_data(data)
            if result:
                return result
        except json.JSONDecodeError:
            continue
    
    # If no matches found, try to extract from markdown code block (last one)
    json_blocks = re.findall(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
    for json_str in reversed(json_blocks):
        try:
            data = json.loads(json_str)
            result = validate_rating_data(data)
            if result:
                return result
        except json.JSONDecodeError:
            continue
    
    # Last resort: try direct parse of entire response
    try:
        data = json.loads(response_text.strip())
        return validate_rating_data(data)
    except json.JSONDecodeError:
        pass
    
    logger.error(f"Failed to parse rating response: {response_text[:200]}")
    return None


def validate_rating_data(data: dict) -> dict | None:
    """
    Validate and normalize rating data.
    """
    required_fields = ['technical', 'composition', 'commercial', 'uniqueness', 'editorial']
    
    # Check required fields
    for field in required_fields:
        if field not in data:
            logger.warning(f"Missing field: {field}")
            return None
        # Ensure values are within range
        try:
            value = float(data[field])
            data[field] = max(1, min(10, value))
        except (ValueError, TypeError):
            logger.warning(f"Invalid value for {field}: {data[field]}")
            return None
    
    # Calculate weighted overall score
    overall = sum(data[field] * RATING_WEIGHTS[field] for field in required_fields)
    data['overall'] = round(overall, 1)
    
    # Determine recommendation
    if data['overall'] >= 7:
        data['recommendation'] = 'KEEP'
    elif data['overall'] >= 5:
        data['recommendation'] = 'REVIEW'
    else:
        data['recommendation'] = 'DELETE'
    
    # Ensure optional fields exist
    if 'categories' not in data:
        data['categories'] = []
    if 'notes' not in data:
        data['notes'] = ''
    
    return data


def get_image_rating(image_base64: str, api_url: str, model: str, 
                     api_type: str = "openai", temperature: float = 0.3,
                     custom_prompt: str = None) -> dict | None:
    """
    Send image to Vision model and get rating scores.
    Supports both Ollama and OpenAI-compatible APIs (vLLM, LM Studio).
    
    Args:
        custom_prompt: Custom prompt template to use instead of default RATING_PROMPT
    """
    from urllib.parse import urlparse, urljoin
    
    # Parse base URL
    parsed_url = urlparse(api_url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    # Use custom prompt if provided, otherwise use default
    prompt_to_use = custom_prompt if custom_prompt else RATING_PROMPT
    
    # Apply EchoPrompt technique for better accuracy
    echo_prompt = apply_echo_prompt(prompt_to_use)
    logger.debug(f"Using EchoPrompt technique (original length: {len(prompt_to_use)}, echo length: {len(echo_prompt)})")
    
    try:
        if api_type == "openai":
            # Use OpenAI-compatible API (vLLM, LM Studio)
            url = urljoin(base_url, "/v1/chat/completions")
            headers = {"Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": echo_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}"
                                }
                            }
                        ]
                    }
                ],
                "temperature": temperature,
                "max_tokens": 500
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
            response_text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            
        else:
            # Default to Ollama API
            url = urljoin(base_url, "/api/generate")
            payload = {
                "model": model,
                "prompt": echo_prompt,
                "images": [image_base64],
                "stream": False,
                "options": {"temperature": temperature}
            }
            
            response = requests.post(url, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
            response_text = data.get("response", "").strip()
        
        logger.debug(f"Rating response: {response_text[:200]}...")
        return parse_rating_response(response_text)
        
    except Exception as e:
        logger.error(f"Error getting image rating ({api_type}): {e}")
        return None


class RatingWorker(QThread):
    """
    Worker thread for rating images using Vision model.
    """
    # Signals
    progress_update = pyqtSignal(str)           # Status message
    progress_info = pyqtSignal(int, int, float) # current, total, eta_seconds
    image_rated = pyqtSignal(dict)              # Single image result with all data
    rating_finished = pyqtSignal(list)          # All results when done
    error_occurred = pyqtSignal(str)            # Error message

    def __init__(self, folder_path: str, include_subfolders: bool = True,
                 api_url: str = OLLAMA_HOST, vision_model: str = VISION_MODEL,
                 api_type: str = "openai", temperature: float = 0.3,
                 custom_prompt: str = None):
        super().__init__()
        self.folder_path = folder_path
        self.include_subfolders = include_subfolders
        self.api_url = api_url
        self.vision_model = vision_model
        self.api_type = api_type
        self.temperature = temperature
        self.custom_prompt = custom_prompt
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused by default
        self.results = []
        logger.debug(f"RatingWorker initialized: api_url={api_url}, model={vision_model}, api_type={api_type}")

    def stop(self):
        """Stop the worker."""
        self._stop_event.set()
        self._pause_event.set()  # Unpause to allow clean exit
        logger.debug("RatingWorker stop requested")

    def pause(self):
        """Pause the worker."""
        self._pause_event.clear()
        logger.debug("RatingWorker paused")

    def resume(self):
        """Resume the worker."""
        self._pause_event.set()
        logger.debug("RatingWorker resumed")

    def is_running(self):
        """Check if worker is running."""
        return self.isRunning()

    def run(self):
        import lancedb_manager
        
        logger.debug("RatingWorker started")
        self.results = []
        
        # Validate folder
        if not os.path.isdir(self.folder_path):
            self.error_occurred.emit("Selected folder does not exist.")
            self.rating_finished.emit([])
            return
        
        # Collect image files
        image_exts = ('.png', '.jpg', '.jpeg')
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
            self.rating_finished.emit([])
            return
        
        self.progress_update.emit(f"Found {total} images. Loading cache...")
        
        # Compute prompt hash for current prompt
        prompt_to_use = self.custom_prompt if self.custom_prompt else RATING_PROMPT
        current_prompt_hash = get_prompt_hash(prompt_to_use)
        logger.debug(f"Current prompt hash: {current_prompt_hash}")
        
        # OPTIMIZATION: Batch load all ratings into memory (fast single query)
        all_ratings = lancedb_manager.get_all_ratings()
        ratings_by_path = {r.get('filepath', ''): r for r in all_ratings}
        logger.debug(f"Loaded {len(ratings_by_path)} ratings from cache")
        
        self.progress_update.emit(f"Found {total} images. Checking {len(ratings_by_path)} cached ratings...")
        
        # Separate cached and new files (fast memory lookup)
        files_to_rate = []
        cached_count = 0
        prompt_changed_count = 0
        
        for filepath in image_files:
            cached_rating = ratings_by_path.get(filepath)
            if cached_rating:
                cached_prompt_hash = cached_rating.get('prompt_hash', '')
                # Check if prompt changed - if so, need to re-rate
                if cached_prompt_hash and cached_prompt_hash == current_prompt_hash:
                    # Use cached rating
                    result = {
                        'filepath': filepath,
                        'filename': os.path.basename(filepath),
                        'success': True,
                        'from_cache': True,
                        'technical': cached_rating.get('technical', 0),
                        'composition': cached_rating.get('composition', 0),
                        'commercial': cached_rating.get('commercial', 0),
                        'uniqueness': cached_rating.get('uniqueness', 0),
                        'editorial': cached_rating.get('editorial', 0),
                        'overall': cached_rating.get('overall', 0),
                        'defects': cached_rating.get('defects', []),
                        'recommendation': cached_rating.get('recommendation', ''),
                        'categories': cached_rating.get('categories', []),
                        'notes': cached_rating.get('notes', '')
                    }
                    self.results.append(result)
                    self.image_rated.emit(result)
                    cached_count += 1
                else:
                    # Prompt changed - need to re-rate
                    files_to_rate.append(filepath)
                    prompt_changed_count += 1
            else:
                files_to_rate.append(filepath)
        
        if prompt_changed_count > 0:
            self.progress_update.emit(f"Loaded {cached_count} from cache. Re-rating {prompt_changed_count} (prompt changed). New: {len(files_to_rate) - prompt_changed_count}.")
        else:
            self.progress_update.emit(f"Loaded {cached_count} from cache. Rating {len(files_to_rate)} new images...")
        
        # Emit progress for cached items
        self.progress_info.emit(cached_count, total, 0)
        
        if not files_to_rate:
            self.progress_update.emit(f"All {total} images already rated (from cache).")
            self.rating_finished.emit(self.results)
            return
        
        start_time = time.time()
        processed_count = 0
        
        for filepath in files_to_rate:
            # Check for stop request
            if self._stop_event.is_set():
                self.progress_update.emit(f"Rating stopped. Cached: {cached_count}, New: {processed_count}/{len(files_to_rate)}")
                break
            
            # Wait if paused
            self._pause_event.wait()
            
            filename = os.path.basename(filepath)
            self.progress_update.emit(f"Rating: {filename}")
            
            # Resize and encode image
            img_base64 = resize_and_encode_image(filepath)
            if img_base64 is None:
                logger.error(f"Failed to process image: {filename}")
                result = {
                    'filepath': filepath,
                    'filename': filename,
                    'success': False,
                    'from_cache': False,
                    'error': 'Failed to process image'
                }
                self.results.append(result)
                self.image_rated.emit(result)
                processed_count += 1
                continue
            
            # Get rating from Vision model
            rating_data = get_image_rating(
                img_base64, 
                self.api_url, 
                self.vision_model,
                self.api_type,
                self.temperature,
                self.custom_prompt
            )
            
            if rating_data:
                result = {
                    'filepath': filepath,
                    'filename': filename,
                    'success': True,
                    'from_cache': False,
                    **rating_data
                }
                # Save to LanceDB cache with prompt hash
                lancedb_manager.save_rating(result, current_prompt_hash)
            else:
                result = {
                    'filepath': filepath,
                    'filename': filename,
                    'success': False,
                    'from_cache': False,
                    'error': 'Failed to get rating from model'
                }
            
            self.results.append(result)
            self.image_rated.emit(result)
            
            processed_count += 1
            
            # Calculate ETA
            elapsed = time.time() - start_time
            if processed_count > 0:
                eta = (elapsed / processed_count) * (len(files_to_rate) - processed_count)
            else:
                eta = 0
            
            self.progress_info.emit(cached_count + processed_count, total, eta)
        
        # Final status
        success_count = sum(1 for r in self.results if r.get('success', False))
        self.progress_update.emit(f"Rating complete. Total: {total}, Cached: {cached_count}, New: {processed_count}, Success: {success_count}")
        self.rating_finished.emit(self.results)
        logger.debug(f"RatingWorker finished. Total: {total}, Cached: {cached_count}, Success: {success_count}")

