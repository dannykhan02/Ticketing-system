"""
Enhanced Cache Manager for AI Assistant
Provides intelligent caching for LLM responses to reduce API calls and costs
"""

import hashlib
import json
import time
import logging
from typing import Optional, Any, Dict, List
from collections import OrderedDict
from threading import Lock

logger = logging.getLogger(__name__)


class LRUCache:
    """Thread-safe LRU (Least Recently Used) Cache implementation"""
    
    def __init__(self, max_size: int = 1000):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.lock = Lock()
        self.hits = 0
        self.misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """Get item from cache"""
        with self.lock:
            if key in self.cache:
                # Move to end (most recently used)
                self.cache.move_to_end(key)
                self.hits += 1
                return self.cache[key]
            self.misses += 1
            return None
    
    def set(self, key: str, value: Any):
        """Set item in cache"""
        with self.lock:
            if key in self.cache:
                # Update existing item
                self.cache.move_to_end(key)
            else:
                # Add new item
                if len(self.cache) >= self.max_size:
                    # Remove oldest item
                    self.cache.popitem(last=False)
            self.cache[key] = value
    
    def clear(self):
        """Clear all cache"""
        with self.lock:
            self.cache.clear()
            self.hits = 0
            self.misses = 0
    
    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics"""
        with self.lock:
            total = self.hits + self.misses
            hit_rate = (self.hits / total * 100) if total > 0 else 0
            return {
                "size": len(self.cache),
                "max_size": self.max_size,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(hit_rate, 2)
            }


class CacheManager:
    """Intelligent cache manager for AI responses"""
    
    def __init__(self, max_size: int = 1000, ttl: int = 3600):
        """
        Initialize cache manager
        
        Args:
            max_size: Maximum number of cached items
            ttl: Time to live in seconds (default 1 hour)
        """
        self.cache = LRUCache(max_size=max_size)
        self.ttl = ttl
        self.timestamps = {}
        self.lock = Lock()
        logger.info(f"Cache Manager initialized - Max size: {max_size}, TTL: {ttl}s")
    
    def _generate_key(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        Generate a unique cache key from messages and parameters
        
        Args:
            messages: List of message dicts
            **kwargs: Additional parameters (temperature, max_tokens, etc.)
        
        Returns:
            str: MD5 hash key
        """
        # Create a deterministic string representation
        cache_data = {
            "messages": messages,
            "params": {k: v for k, v in sorted(kwargs.items())}
        }
        
        # Convert to JSON string (sorted for consistency)
        json_str = json.dumps(cache_data, sort_keys=True)
        
        # Generate MD5 hash
        return hashlib.md5(json_str.encode()).hexdigest()
    
    def get(self, messages: List[Dict[str, str]], **kwargs) -> Optional[str]:
        """
        Get cached response if available and not expired
        
        Args:
            messages: List of message dicts
            **kwargs: Additional parameters
        
        Returns:
            str: Cached response or None
        """
        key = self._generate_key(messages, **kwargs)
        
        # Check if cached
        cached_value = self.cache.get(key)
        
        if cached_value is None:
            return None
        
        # Check if expired
        with self.lock:
            timestamp = self.timestamps.get(key, 0)
            if time.time() - timestamp > self.ttl:
                # Expired - remove from cache
                self.timestamps.pop(key, None)
                logger.debug(f"Cache expired for key: {key[:8]}...")
                return None
        
        logger.info(f"Cache HIT for key: {key[:8]}...")
        return cached_value
    
    def set(self, messages: List[Dict[str, str]], response: str, **kwargs):
        """
        Cache a response
        
        Args:
            messages: List of message dicts
            response: LLM response to cache
            **kwargs: Additional parameters
        """
        key = self._generate_key(messages, **kwargs)
        
        self.cache.set(key, response)
        
        with self.lock:
            self.timestamps[key] = time.time()
        
        logger.debug(f"Cached response for key: {key[:8]}...")
    
    def invalidate_user_cache(self, user_id: int):
        """
        Invalidate cache entries for a specific user
        (useful when user data changes)
        
        Args:
            user_id: User ID to invalidate cache for
        """
        # For now, we'll implement a simple approach
        # In production, you might want to tag cache entries by user
        logger.info(f"Invalidating cache for user: {user_id}")
        # This is a simplified version - full implementation would need user tagging
    
    def clear(self):
        """Clear all cached data"""
        self.cache.clear()
        with self.lock:
            self.timestamps.clear()
        logger.info("Cache cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        stats = self.cache.get_stats()
        
        # Add timestamp info
        with self.lock:
            active_entries = sum(
                1 for timestamp in self.timestamps.values()
                if time.time() - timestamp <= self.ttl
            )
        
        stats["active_entries"] = active_entries
        stats["ttl_seconds"] = self.ttl
        
        return stats
    
    def cleanup_expired(self):
        """Remove expired entries (call periodically)"""
        current_time = time.time()
        expired_keys = []
        
        with self.lock:
            for key, timestamp in self.timestamps.items():
                if current_time - timestamp > self.ttl:
                    expired_keys.append(key)
        
        for key in expired_keys:
            with self.lock:
                self.timestamps.pop(key, None)
        
        if expired_keys:
            logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")


# Singleton instance - will be initialized in llm_client
_cache_instance = None


def get_cache_manager(max_size: int = 1000, ttl: int = 3600) -> CacheManager:
    """Get or create cache manager singleton"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = CacheManager(max_size=max_size, ttl=ttl)
    return _cache_instance
