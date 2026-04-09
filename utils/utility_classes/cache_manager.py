import logging
from typing import Any

logger = logging.getLogger(__name__)

class CacheManager:
    """Utility class for cache management"""

    @staticmethod
    def get_cache_stats(fragmentation_manager) -> dict:
        """Get cache statistics from fragmentation manager"""
        if fragmentation_manager and fragmentation_manager.worker:
            worker_cache = fragmentation_manager.worker.fragment_cache
            # These would need to be passed in or tracked elsewhere
            hit_count = getattr(fragmentation_manager, 'cache_hit_count', 0)
            miss_count = getattr(fragmentation_manager, 'cache_miss_count', 0)
            total_requests = hit_count + miss_count
            hit_rate = (hit_count / total_requests * 100) if total_requests > 0 else 0

            return {
                'cache_size': len(worker_cache),
                'max_cache_size': 100,
                'hit_count': hit_count,
                'miss_count': miss_count,
                'hit_rate_percent': hit_rate,
                'total_requests': total_requests
            }
        return {
            'cache_size': 0, 'max_cache_size': 100, 'hit_count': 0,
            'miss_count': 0, 'hit_rate_percent': 0, 'total_requests': 0
        }

    @staticmethod
    def clear_cache(fragmentation_manager) -> int:
        """Clear cache and return number of items cleared"""
        if fragmentation_manager and fragmentation_manager.worker:
            cache_size = len(fragmentation_manager.worker.fragment_cache)
            fragmentation_manager.worker.fragment_cache.clear()
            return cache_size
        return 0
