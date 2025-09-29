import os
import redis
import json
from langchain.globals import set_llm_cache
from langchain_community.cache import RedisCache, InMemoryCache
from typing import Any

def setup_llm_cache():
    """
    Sets up the LLM cache based on environment variables.
    If USE_LLM_REDIS_CACHE is 'true', configures RedisCache.
    Otherwise, uses InMemoryCache (which is Langchain's default if no cache is set).
    """
    if os.getenv("USE_LLM_REDIS_CACHE", "false").lower() == "true":
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        try:
            # Test connection
            client = redis.from_url(redis_url)
            client.ping()
            set_llm_cache(RedisCache(redis_client=client))
            print(f"LLM caching enabled with Redis at {redis_url}")
        except redis.exceptions.ConnectionError as e:
            print(f"Could not connect to Redis at {redis_url}. LLM caching will be in-memory. Error: {e}")
            set_llm_cache(InMemoryCache())
    else:
        # Use in-memory caching (default) - no need to announce this
        set_llm_cache(InMemoryCache())

class LLMCache:
    """
    A wrapper around Langchain's LLM cache for direct interaction if needed,
    though set_llm_cache handles most use cases globally.
    """
    def __init__(self):
        self._cache = {} # This is just a placeholder, actual caching is handled by set_llm_cache

    def get(self, prompt: str, llm_model_name: str, **kwargs) -> Any:
        # Langchain's set_llm_cache handles this globally.
        # This method is more for conceptual understanding or if we needed a custom cache lookup.
        pass

    def set(self, prompt: str, llm_model_name: str, response: Any, **kwargs):
        # Langchain's set_llm_cache handles this globally.
        pass
