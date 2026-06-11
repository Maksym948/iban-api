import os
import json
import aiosqlite
import redis.asyncio as redis
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from models import IBANRequest, IBANResponse
from iban_logic import validate_iban
from middleware import AuthRateLimitMiddleware

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

# 1. Auth Middleware (Виконується ДРУГИМ, після того як CORS пропустить запит)
app.add_middleware(AuthRateLimitMiddleware, redis_client=redis_client)

# 2. CORS Middleware (Виконується ПЕРШИМ, безпечно відповідає на OPTIONS preflight)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://pactops.pro"], # Жорстко зафіксовано нашу Вітрину
    allow_credentials=True,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"], # Пропускає X-API-Key
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
