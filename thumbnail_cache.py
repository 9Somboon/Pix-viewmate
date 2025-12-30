# Thumbnail Cache System
# In-memory LRU cache + disk-based cache for thumbnail images

import os
import hashlib
import logging
from collections import OrderedDict
from pathlib import Path
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ThumbnailCache:
    """
    Dual-layer thumbnail cache:
    1. In-memory LRU cache for fast access to recently used thumbnails
    2. Disk cache for persistence across sessions
    """
    
    def __init__(self, cache_dir: str = None, max_memory_items: int = 200, max_disk_size_mb: int = 500):
        """
        Initialize the thumbnail cache.
        
        Args:
            cache_dir: Directory for disk cache, defaults to .cache/thumbnails in project dir
            max_memory_items: Maximum number of thumbnails to keep in memory (LRU)
            max_disk_size_mb: Maximum disk cache size in MB
        """
        # Memory cache (LRU using OrderedDict)
        self.memory_cache: OrderedDict[str, QPixmap] = OrderedDict()
        self.max_memory_items = max_memory_items
        
        # Disk cache settings
        if cache_dir is None:
            cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "thumbnails")
        self.cache_dir = cache_dir
        self.max_disk_size_bytes = max_disk_size_mb * 1024 * 1024
        
        # Create cache directory if it doesn't exist
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # Stats
        self.hits = 0
        self.misses = 0
        
        logger.debug(f"ThumbnailCache initialized: memory={max_memory_items}, disk_dir={cache_dir}")
    
    def _generate_cache_key(self, image_path: str, size: int) -> str:
        """Generate a unique cache key based on file path, modification time, and size."""
        try:
            mtime = os.path.getmtime(image_path)
        except OSError:
            mtime = 0
        
        key_string = f"{image_path}_{mtime}_{size}"
        return hashlib.md5(key_string.encode()).hexdigest()
    
    def _get_disk_cache_path(self, cache_key: str) -> str:
        """Get the disk cache file path for a given cache key."""
        return os.path.join(self.cache_dir, f"{cache_key}.jpg")
    
    def get_thumbnail(self, image_path: str, size: int) -> QPixmap | None:
        """
        Get a thumbnail from cache.
        
        Args:
            image_path: Original image file path
            size: Thumbnail size (square dimension)
            
        Returns:
            QPixmap if found in cache, None otherwise
        """
        cache_key = self._generate_cache_key(image_path, size)
        
        # 1. Check memory cache (O(1) lookup)
        if cache_key in self.memory_cache:
            # Move to end (most recently used)
            self.memory_cache.move_to_end(cache_key)
            self.hits += 1
            return self.memory_cache[cache_key]
        
        # 2. Check disk cache
        disk_path = self._get_disk_cache_path(cache_key)
        if os.path.exists(disk_path):
            pixmap = QPixmap(disk_path)
            if not pixmap.isNull():
                # Load into memory cache
                self._add_to_memory_cache(cache_key, pixmap)
                self.hits += 1
                return pixmap
        
        # Cache miss
        self.misses += 1
        return None
    
    def cache_thumbnail(self, image_path: str, size: int, pixmap: QPixmap) -> bool:
        """
        Cache a thumbnail.
        
        Args:
            image_path: Original image file path
            size: Thumbnail size
            pixmap: The thumbnail QPixmap to cache
            
        Returns:
            True if cached successfully
        """
        if pixmap.isNull():
            return False
        
        cache_key = self._generate_cache_key(image_path, size)
        
        # Add to memory cache
        self._add_to_memory_cache(cache_key, pixmap)
        
        # Save to disk cache (async would be better, but keeping simple for now)
        disk_path = self._get_disk_cache_path(cache_key)
        try:
            pixmap.save(disk_path, "JPEG", 85)
        except Exception as e:
            logger.warning(f"Failed to save thumbnail to disk cache: {e}")
        
        return True
    
    def _add_to_memory_cache(self, cache_key: str, pixmap: QPixmap):
        """Add a thumbnail to memory cache with LRU eviction."""
        # Remove oldest items if at capacity
        while len(self.memory_cache) >= self.max_memory_items:
            self.memory_cache.popitem(last=False)
        
        self.memory_cache[cache_key] = pixmap
        self.memory_cache.move_to_end(cache_key)
    
    def clear_memory_cache(self):
        """Clear the in-memory cache."""
        self.memory_cache.clear()
        logger.debug("Memory cache cleared")
    
    def clear_disk_cache(self):
        """Clear the disk cache."""
        try:
            for filename in os.listdir(self.cache_dir):
                filepath = os.path.join(self.cache_dir, filename)
                if os.path.isfile(filepath) and filename.endswith('.jpg'):
                    os.remove(filepath)
            logger.debug("Disk cache cleared")
        except Exception as e:
            logger.warning(f"Error clearing disk cache: {e}")
    
    def cleanup_disk_cache(self):
        """Remove old cache files if disk cache exceeds max size."""
        try:
            cache_files = []
            total_size = 0
            
            for filename in os.listdir(self.cache_dir):
                filepath = os.path.join(self.cache_dir, filename)
                if os.path.isfile(filepath) and filename.endswith('.jpg'):
                    stat = os.stat(filepath)
                    cache_files.append((filepath, stat.st_mtime, stat.st_size))
                    total_size += stat.st_size
            
            # If under limit, nothing to do
            if total_size <= self.max_disk_size_bytes:
                return
            
            # Sort by modification time (oldest first)
            cache_files.sort(key=lambda x: x[1])
            
            # Remove oldest files until under limit
            for filepath, _, size in cache_files:
                if total_size <= self.max_disk_size_bytes:
                    break
                try:
                    os.remove(filepath)
                    total_size -= size
                except OSError:
                    pass
            
            logger.debug(f"Disk cache cleanup complete. Current size: {total_size / 1024 / 1024:.1f}MB")
        except Exception as e:
            logger.warning(f"Error during disk cache cleanup: {e}")
    
    def get_stats(self) -> dict:
        """Get cache statistics."""
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{hit_rate:.1f}%",
            "memory_items": len(self.memory_cache)
        }


# Global singleton instance
_thumbnail_cache: ThumbnailCache | None = None


def get_thumbnail_cache() -> ThumbnailCache:
    """Get the global thumbnail cache instance."""
    global _thumbnail_cache
    if _thumbnail_cache is None:
        _thumbnail_cache = ThumbnailCache()
    return _thumbnail_cache


def load_cached_thumbnail(image_path: str, size: int) -> QPixmap:
    """
    Convenience function to load a thumbnail with caching.
    
    Args:
        image_path: Path to the original image
        size: Desired thumbnail size (square)
        
    Returns:
        QPixmap of the thumbnail
    """
    cache = get_thumbnail_cache()
    
    # Try to get from cache
    pixmap = cache.get_thumbnail(image_path, size)
    if pixmap is not None:
        return pixmap
    
    # Load and scale from disk
    pixmap = QPixmap(image_path)
    if not pixmap.isNull():
        pixmap = pixmap.scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        # Cache it
        cache.cache_thumbnail(image_path, size, pixmap)
    
    return pixmap
