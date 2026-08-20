"""Provider-specific prompt cache capability and adapter contracts."""

from nanobot.providers.cache.capabilities import CacheCapabilities, capabilities_for
from nanobot.providers.cache.dashscope import QwenCacheAdapter
from nanobot.providers.cache.deepseek import DeepSeekCacheAdapter
from nanobot.providers.cache.openai import OpenAICacheAdapter
from nanobot.providers.cache.zhipu import GLMCacheAdapter

__all__ = [
    "CacheCapabilities",
    "DeepSeekCacheAdapter",
    "GLMCacheAdapter",
    "OpenAICacheAdapter",
    "QwenCacheAdapter",
    "capabilities_for",
]
