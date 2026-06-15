import os
import json
import hmac
import hashlib
import aiosqlite
import redis.asyncio as redis
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import IBANRequest, IBANResponse
from iban_logic import validate_iban
from middleware import AuthRateLimitMiddleware as _OriginalAuthMiddleware

# Global Redis connection
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "core-redis"), 
    port=6379, 
    db=0, 
    decode_responses=True
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Init SQLite DB у підключеному томі
    os.makedirs("/data", exist_ok=True)
    async with aiosqlite.connect("/data/users.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                key TEXT PRIMARY KEY,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()
    print("✅ SQLite initialized at /data/users.db")
    yield
    # Shutdown
    await redis_client.close()

app = FastAPI(title="IBAN Validator API", version="1.0.0", lifespan=lifespan)

# Архітектурний патч: Успадковуємо оригінальний Middleware прямо в main.py, 
# щоб безпечно виключити Webhook з перевірки API-ключа без зміни файлу middleware.py
class PatchedAuthRateLimitMiddleware(_OriginalAuthMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Пропускаємо healthcheck та Lemon Squeezy Webhook
        if request.url.path in ["/health", "/v1/webhooks/lemonsqueezy"]:
            return await call_next(request)
        return await super().dispatch(request, call_next)

# 1. Auth Middleware (Виконується ДРУГИМ, після того як CORS пропустить запит)
app.add_middleware(PatchedAuthRateLimitMiddleware, redis_client=redis_client)

# 2. CORS Middleware (Виконується ПЕРШИМ, безпечно відповідає на OPTIONS preflight)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://pactops.pro"], # Жорстко зафіксовано нашу Вітрину
    allow_credentials=True,
    allow_methods=["POST", "OPTIONS", "GET"], # GET потрібен для /health та Swagger UI
    allow_headers=["*"], # Пропускає X-API-Key та X-Signature
)

@app.get("/health")
async def healthcheck():
    return {"status": "ok", "service": "iban-api"}

@app.post("/v1/iban/validate", response_model=IBANResponse)
async def validate_iban_endpoint(payload: IBANRequest):
    clean_iban = payload.iban.replace(" ", "").upper()
    cache_key = f"iban:cache:{clean_iban}"
    
    # 1. Check Redis Cache (24h TTL)
    cached_result = await redis_client.get(cache_key)
    if cached_result:
        return json.loads(cached_result)
    
    # 2. Validate (Zero-COGS)
    result = validate_iban(payload.iban)
    
    # 3. Save to Cache
    await redis_client.setex(cache_key, 86400, json.dumps(result))
    
    return result

@app.post("/v1/webhooks/lemonsqueezy")
async def lemonsqueezy_webhook(request: Request):
    """
    Захищений ендпоінт для прийому вебхуків від Lemon Squeezy.
    Автоматично генерує або блокує API-ключі в SQLite (Cold Storage).
    """
    secret = os.getenv("LEMON_SQUEEZY_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    # 1. Зчитуємо сире тіло запиту (Raw Body) для валідації підпису
    body = await request.body()
    
    # 2. Отримуємо підпис з заголовка
    signature = request.headers.get("X-Signature")
    if not signature:
        raise HTTPException(status_code=401, detail="Missing X-Signature header")

    # 3. Генеруємо HMAC-SHA256 хеш сирого тіла
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256
    ).hexdigest()

    # 4. Безпечне порівняння (захист від timing attacks)
    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # 5. Парсинг JSON тіла
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # 6. Обробка подій (Event Handling)
    event_name = payload.get("meta", {}).get("event_name")
    data_attributes = payload.get("data", {}).get("attributes", {})
    key = data_attributes.get("key")

    if not event_name:
        return {"status": "ignored", "reason": "no event_name provided"}

    # 7. Взаємодія з Cold Storage (SQLite)
    async with aiosqlite.connect("/data/users.db") as db:
        if event_name == "license_key.created":
            if key:
                # Активуємо новий ключ, куплений клієнтом
                await db.execute(
                    "INSERT OR REPLACE INTO api_keys (key, is_active) VALUES (?, 1)",
                    (key,)
                )
                await db.commit()
                
        elif event_name in ["subscription_cancelled", "subscription_expired", "license_key.disabled"]:
            if key:
                # Негайно блокуємо доступ клієнту при відписці або експайрації
                await db.execute(
                    "UPDATE api_keys SET is_active = 0 WHERE key = ?",
                    (key,)
                )
                await db.commit()

    return {"status": "ok", "event": event_name}
