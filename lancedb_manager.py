# LanceDB Manager
# Handles all interactions with the LanceDB vector database

import lancedb
import pyarrow as pa
import os
import requests
import logging
from config import LANCEDB_PATH, OLLAMA_HOST, EMBEDDING_MODEL

# Setup logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global database connection
_db = None
_table = None
_embedding_dim = None  # Will be auto-detected

# Table name for images
TABLE_NAME = "images"


def detect_embedding_dimension(ollama_host: str = OLLAMA_HOST, model: str = EMBEDDING_MODEL) -> int:
    """
    Detect the embedding dimension by sending a test request to the Ollama server.
    
    Args:
        ollama_host: The Ollama server URL
        model: The embedding model name
        
    Returns:
        The dimension of the embedding vector
    """
    global _embedding_dim
    
    if _embedding_dim is not None:
        return _embedding_dim
    
    url = f"{ollama_host.rstrip('/')}/api/embed"
    
    payload = {
        "model": model,
        "input": "test"
    }
    
    try:
        logger.info(f"Detecting embedding dimension from model: {model}")
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        
        # Ollama returns embeddings in 'embeddings' array (for batch) or 'embedding' (for single)
        embeddings = data.get("embeddings")
        if embeddings and len(embeddings) > 0:
            _embedding_dim = len(embeddings[0])
            logger.info(f"Detected embedding dimension: {_embedding_dim}")
            return _embedding_dim
        
        embedding = data.get("embedding")
        if embedding:
            _embedding_dim = len(embedding)
            logger.info(f"Detected embedding dimension: {_embedding_dim}")
            return _embedding_dim
            
        logger.error(f"No embedding in response: {data}")
        raise ValueError("Could not detect embedding dimension from Ollama response")
    except Exception as e:
        logger.error(f"Error detecting embedding dimension: {e}")
        # Fallback to a common dimension if detection fails
        logger.warning("Falling back to default dimension: 1024")
        _embedding_dim = 1024
        return _embedding_dim


def get_schema(dimension: int) -> pa.Schema:
    """
    Create PyArrow schema with the specified vector dimension.
    
    Args:
        dimension: The embedding vector dimension
        
    Returns:
        PyArrow schema for the images table
    """
    return pa.schema([
        pa.field("filepath", pa.string()),
        pa.field("description", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), dimension))
    ])


def connect():
    """
    Connect to or create the LanceDB database.
    Returns the database connection.
    """
    global _db
    if _db is None:
        # Create directory if it doesn't exist
        os.makedirs(LANCEDB_PATH, exist_ok=True)
        _db = lancedb.connect(LANCEDB_PATH)
    return _db


def get_table(dimension: int = None):
    """
    Get or create the images table.
    
    Args:
        dimension: The embedding dimension. If None, will be auto-detected.
        
    Returns:
        The table object.
    """
    global _table
    if _table is None:
        db = connect()
        # Check if table exists
        if TABLE_NAME in db.table_names():
            _table = db.open_table(TABLE_NAME)
        else:
            # Auto-detect dimension if not provided
            if dimension is None:
                dimension = detect_embedding_dimension()
            # Create empty table with schema
            schema = get_schema(dimension)
            _table = db.create_table(TABLE_NAME, schema=schema)
            logger.info(f"Created new table with dimension: {dimension}")
    return _table



def is_indexed(filepath: str) -> bool:
    """
    Check if an image is already indexed in the database.
    
    Args:
        filepath: Absolute path to the image file
        
    Returns:
        True if the image is already indexed, False otherwise
    """
    table = get_table()
    try:
        # Search for the filepath in the table
        result = table.search().where(f"filepath = '{filepath}'", prefilter=True).limit(1).to_list()
        return len(result) > 0
    except Exception as e:
        print(f"Error checking if indexed: {e}")
        return False


def add_image(filepath: str, description: str, vector: list) -> bool:
    """
    Add a new image to the database.
    
    Args:
        filepath: Absolute path to the image file
        description: Text description of the image
        vector: Embedding vector (list of floats)
        
    Returns:
        True if successful, False otherwise
    """
    table = get_table()
    try:
        table.add([{
            "filepath": filepath,
            "description": description,
            "vector": vector
        }])
        return True
    except Exception as e:
        print(f"Error adding image to database: {e}")
        return False


def search(query_vector: list, limit: int = 20) -> list:
    """
    Search for similar images using vector similarity.
    
    Args:
        query_vector: The query embedding vector
        limit: Maximum number of results to return
        
    Returns:
        List of dictionaries with 'filepath', 'description', and '_distance' fields
    """
    table = get_table()
    try:
        results = table.search(query_vector).limit(limit).to_list()
        return results
    except Exception as e:
        print(f"Error searching database: {e}")
        return []


def get_total_count() -> int:
    """
    Get the total number of indexed images.
    
    Returns:
        Total count of images in the database
    """
    table = get_table()
    try:
        return table.count_rows()
    except Exception as e:
        print(f"Error counting rows: {e}")
        return 0


def delete_by_filepath(filepath: str) -> bool:
    """
    Delete an image from the database by filepath.
    
    Args:
        filepath: Absolute path to the image file
        
    Returns:
        True if successful, False otherwise
    """
    table = get_table()
    try:
        table.delete(f"filepath = '{filepath}'")
        return True
    except Exception as e:
        print(f"Error deleting from database: {e}")
        return False


def clear_database():
    """
    Clear all data from the database.
    """
    global _table
    db = connect()
    try:
        if TABLE_NAME in db.table_names():
            db.drop_table(TABLE_NAME)
        _table = None
    except Exception as e:
        print(f"Error clearing database: {e}")
