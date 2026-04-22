from collections import defaultdict
from datetime import datetime, timedelta
import threading

class RateLimiter:
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = timedelta(seconds=window_seconds)
        self._store: dict[str, list[datetime]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        now = datetime.utcnow()
        cutoff = now - self.window
        with self._lock:
            self._store[key] = [t for t in self._store[key] if t > cutoff]
            if len(self._store[key]) >= self.max_requests:
                return False
            self._store[key].append(now)
            return True

# Global limiters
register_limiter = RateLimiter(max_requests=5, window_seconds=60)
scan_limiter = RateLimiter(max_requests=60, window_seconds=60)
vote_limiter = RateLimiter(max_requests=5, window_seconds=60)
