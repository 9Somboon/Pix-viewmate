import unittest
from unittest.mock import MagicMock, patch
import requests
import io
from PIL import Image
import base64
from utilities import resize_and_encode_image, ask_api_about_image

class TestOptimizations(unittest.TestCase):
    def test_resize_and_encode_image(self):
        # Create a dummy large image
        img = Image.new('RGB', (2000, 2000), color = 'red')
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG')
        img_byte_arr = img_byte_arr.getvalue()
        
        # Save to a temporary file
        with open("temp_test_image.jpg", "wb") as f:
            f.write(img_byte_arr)
            
        # Test resizing
        encoded = resize_and_encode_image("temp_test_image.jpg", max_size=640)
        self.assertIsNotNone(encoded)
        
        # Decode and check size
        decoded_bytes = base64.b64decode(encoded)
        decoded_img = Image.open(io.BytesIO(decoded_bytes))
        self.assertTrue(decoded_img.width <= 640)
        self.assertTrue(decoded_img.height <= 640)
        print(f"Original size: 2000x2000, Resized: {decoded_img.size}")
        
        import os
        os.remove("temp_test_image.jpg")

    @patch('requests.Session')
    def test_ask_api_with_session(self, mock_session_cls):
        mock_session = mock_session_cls.return_value
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "YES"}
        mock_session.post.return_value = mock_response
        
        # Test calling with session
        session = requests.Session()
        result = ask_api_about_image(
            "http://localhost:11434", 
            "llava", 
            "base64string", 
            "cat", 
            0.0, 
            "ollama", 
            session=session
        )
        
        self.assertTrue(result)
        # Verify session.post was called
        mock_session.post.assert_called_once()
        print("ask_api_about_image correctly used the session.")

if __name__ == '__main__':
    unittest.main()
