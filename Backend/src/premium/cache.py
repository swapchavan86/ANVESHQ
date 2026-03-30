from __future__ import annotations

import threading
import time
from typing import Any


class InMemoryTTLCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.RLock()

    def get(self, key: str):
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at < time.time():
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: str, value, ttl_seconds: int) -> None:
        with self._lock:
            self._store[key] = (time.time() + ttl_seconds, value)

    def invalidate_prefix(self, prefix: str) -> None:
        with self._lock:
            keys_to_delete = [key for key in self._store if key.startswith(prefix)]
            for key in keys_to_delete:
                self._store.pop(key, None)
