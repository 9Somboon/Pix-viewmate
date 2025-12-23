# Smart Search Configuration
# This file contains configuration settings for the Smart Search feature

import os

# Ollama Server Configuration
OLLAMA_HOST = "http://192.168.1.114:11434"

# Vision Model for generating image descriptions
VISION_MODEL = "qwen3-vl:8b-instruct-q4_K_M"

# Embedding Model for converting text to vectors
EMBEDDING_MODEL = "hf.co/Qwen/Qwen3-Embedding-0.6B-GGUF:Q8_0"

# LanceDB Configuration
# Database will be stored in the project directory by default
LANCEDB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lancedb_data")

# Image processing settings
MAX_IMAGE_SIZE = 1024  # Max dimension for image resizing before sending to Vision model
