# app/utils/cache.py
import asyncio

class SimpleCache:
    def __init__(self):
        self.store = {}
        self.lock = asyncio.Lock()

    async def set(self, key, value, timeout=None):
        async with self.lock:
            self.store[key] = value  # You can add TTL support if needed

    async def get(self, key):
        async with self.lock:
            return self.store.get(key)
        
    async def delete(self, key):  # 👈 Add this method
        async with self.lock:
            if key in self.store:
                del self.store[key]

cache = SimpleCache()