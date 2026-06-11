import aiosqlite
import redis.asyncio as redis
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Налаштування лімітів
RATE_LIMIT_REQUESTS = 1000
RATE_LIMIT_WINDOW = 3600 # 1 година

class AuthRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, redis_client: redis.Redis):
        super().__init__(app)
        self.redis = redis_client

    async def dispatch(self, request: Request, call_next):
        # Пропускаємо healthcheck
        if request.url.path == "/health":
            return await call_next(request)

        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return JSONResponse(status_code=401, content={"detail": "Missing X-API-Key"})

        # 1. COLD STORAGE: Перевірка валідності ключа в SQLite
        is_valid = await self._check_sqlite_key(api_key)
        if not is_valid:
            return JSONResponse(status_code=403, content={"detail": "Invalid or inactive API Key"})

        # 2. HOT STORAGE: Rate Limiting в Redis
        limit_key = f"auth:limits:{api_key}"
        
        # Використовуємо HINCRBY для зберігання лічильника
        current_count = await self.redis.hincrby(limit_key, "count", 1)
        
        # Якщо це перший запит у вікні, встановлюємо TTL
        if current_count == 1:
            await self.redis.expire(limit_key, RATE_LIMIT_WINDOW)
        else:
            # Перевіряємо, чи не сплив ліміт (захист від race condition)
            ttl = await self.redis.ttl(limit_key)
            if ttl == -1:
                await self.redis.expire(limit_key, RATE_LIMIT_WINDOW)

        if current_count > RATE_LIMIT_REQUESTS:
            return JSONResponse(
                status_code=429, 
                content={"detail": "Rate limit exceeded", "limit": RATE_LIMIT_REQUESTS, "window": f"{RATE_LIMIT_WINDOW}s"}
            )

        return await call_next(request)

    async def _check_sqlite_key(self, key: str) -> bool:
        try:
            async with aiosqlite.connect("/data/users.db") as db:
                cursor = await db.execute(
                    "SELECT is_active FROM api_keys WHERE key = ?", (key,)
                )
                row = await cursor.fetchone()
                return bool(row and row[0])
        except Exception as e:
            print(f"SQLite Auth Error: {e}")
            return False
