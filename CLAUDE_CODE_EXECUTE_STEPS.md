# CLAUDE CODE: Execute These Steps NOW

## ⚠️ CRITICAL BUG TO FIX
Embedding circuit breakers show `0 calls` after queries. The embedding path bypasses the breaker.

---

## STEP 1: Verify Current Problem

```bash
cd "/Users/michaelweiss/RAG API/voiceroi-rag-api"
echo "=== Finding direct OpenAI embedding calls ==="
grep -rn "embeddings.create" app/
echo ""
echo "=== Finding get_embedding function ==="
grep -n -A 10 "async def get_embedding" app/main.py
```

**Problem:** `app/main.py` has `get_embedding()` that calls `openai_client.embeddings.create()` DIRECTLY, bypassing the circuit breaker.

---

## STEP 2: Fix app/services/infra.py

This is the CANONICAL embedding function. Replace the entire file:

```bash
cat > "/Users/michaelweiss/RAG API/voiceroi-rag-api/app/services/infra.py" << 'INFRA_EOF'
"""
VoiceROI RAG API - Infrastructure Services
Canonical embedding function - ALL embedding calls MUST go through here.
Version: 1.0.6-circuit-breaker-fixed
"""

import os
import logging
import asyncio
from typing import Optional, List
from openai import AsyncOpenAI
from redis.asyncio import Redis

from app.middleware.circuit_breaker import (
    embedding_breaker,
    redis_breaker,
    CircuitBreakerOpen,
)

logger = logging.getLogger("voiceroi.infra")

# Initialize OpenAI client
openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Redis connection
_redis_client: Optional[Redis] = None


async def get_redis_client() -> Redis:
    """Get or create Redis client."""
    global _redis_client
    if _redis_client is None:
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            raise ValueError("REDIS_URL not configured")
        _redis_client = Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
        )
    return _redis_client


async def embed_text(text: str) -> List[float]:
    """
    Get embedding for text using OpenAI.
    
    THIS IS THE CANONICAL EMBEDDING FUNCTION.
    All embedding calls MUST route through here.
    Protected by embedding_breaker circuit breaker.
    """
    async def _do_embed():
        response = await openai_client.embeddings.create(
            input=text,
            model="text-embedding-3-small",
        )
        return response.data[0].embedding
    
    try:
        embedding = await embedding_breaker.call(_do_embed)
        logger.debug(f"embed_text: Generated embedding via breaker")
        return embedding
    except CircuitBreakerOpen:
        logger.warning(f"embed_text: Circuit OPEN")
        raise
    except Exception as e:
        logger.error(f"embed_text: Failed: {e}")
        raise


async def health_check() -> dict:
    """Check Redis health via circuit breaker."""
    async def _do_ping():
        client = await get_redis_client()
        await client.ping()
        return True
    
    try:
        await redis_breaker.call(_do_ping)
        return {"redis": "connected", "status": "healthy"}
    except CircuitBreakerOpen:
        return {"redis": "circuit_open", "status": "degraded"}
    except Exception as e:
        return {"redis": "error", "status": "unhealthy", "error": str(e)}
INFRA_EOF
echo "✅ Fixed infra.py"
```

---

## STEP 3: Fix get_embedding in app/main.py

### 3a. First, find the function:
```bash
grep -n "async def get_embedding" "/Users/michaelweiss/RAG API/voiceroi-rag-api/app/main.py"
```

### 3b. Edit main.py using sed or manual edit

Replace the `get_embedding` function with this:

```python
async def get_embedding(text: str) -> list[float]:
    """
    Get embedding for semantic cache lookup.
    Routes through canonical embed_text() which is protected by circuit breaker.
    """
    from app.services.infra import embed_text
    return await embed_text(text)
```

### 3c. Using Python to do the replacement:
```python
import re

main_path = "/Users/michaelweiss/RAG API/voiceroi-rag-api/app/main.py"

with open(main_path, 'r') as f:
    content = f.read()

# Backup
with open(main_path + ".backup_before_fix", 'w') as f:
    f.write(content)

# New function
new_func = '''async def get_embedding(text: str) -> list[float]:
    """
    Get embedding for semantic cache lookup.
    Routes through canonical embed_text() which is protected by circuit breaker.
    """
    from app.services.infra import embed_text
    return await embed_text(text)'''

# Replace - find the function and replace it
pattern = r'async def get_embedding\(text: str\)[^:]*:(?:[^a]|a(?!sync def))*?return[^\n]*embedding[^\n]*'
content = re.sub(pattern, new_func, content, flags=re.DOTALL)

# Update version
content = re.sub(r'APP_VERSION\s*=\s*"[^"]+"', 'APP_VERSION = "1.0.6-circuit-breakers-fixed"', content)

with open(main_path, 'w') as f:
    f.write(content)

print("Fixed main.py")
```

---

## STEP 4: Update APP_VERSION

```bash
sed -i '' 's/APP_VERSION = "[^"]*"/APP_VERSION = "1.0.6-circuit-breakers-fixed"/' "/Users/michaelweiss/RAG API/voiceroi-rag-api/app/main.py"
grep APP_VERSION "/Users/michaelweiss/RAG API/voiceroi-rag-api/app/main.py"
```

---

## STEP 5: Verify Fix Before Deploy

```bash
cd "/Users/michaelweiss/RAG API/voiceroi-rag-api"
echo "=== Verify: Only infra.py should have embeddings.create ==="
grep -rn "embeddings.create" app/
echo ""
echo "=== Verify: get_embedding now calls embed_text ==="
grep -n -A 8 "async def get_embedding" app/main.py
echo ""
echo "=== Verify: Version updated ==="
grep APP_VERSION app/main.py
```

**EXPECTED OUTPUT:**
- `embeddings.create` appears ONLY in `app/services/infra.py`
- `get_embedding` calls `from app.services.infra import embed_text`
- `APP_VERSION = "1.0.6-circuit-breakers-fixed"`

---

## STEP 6: Deploy

```bash
cd "/Users/michaelweiss/RAG API/voiceroi-rag-api"
fly deploy --now
```

---

## STEP 7: Verify Deployment

```bash
echo "=== Health Check ==="
curl -s https://voiceroi-rag-api.fly.dev/healthz | jq .

echo ""
echo "=== Send 5 Test Queries ==="
for i in 1 2 3 4 5; do
  curl -s -X POST "https://voiceroi-rag-api.fly.dev/query" \
    -H "Content-Type: application/json" \
    -H "x-api-key: -qTH30qS0b8iCQDlEUGlFYFybNxXwY5Vd7tBbj4jV7M" \
    -d "{\"question\": \"Random test $RANDOM about VoiceROI investment terms\"}" > /dev/null
  echo "Query $i sent"
done

echo ""
echo "=== Check Metrics ==="
curl -s https://voiceroi-rag-api.fly.dev/metrics | grep -E "circuit.*calls_total"
```

---

## ✅ SUCCESS CRITERIA

**BEFORE (BUG):**
```
circuit_breaker_calls_total{name="embedding"} 0
circuit_breaker_calls_total{name="redis"} 11
```

**AFTER (FIXED):**
```
circuit_breaker_calls_total{name="embedding"} 5  ← MUST BE > 0
circuit_breaker_calls_total{name="redis"} 16
```

---

## 🔧 MANUAL EDIT GUIDE (if scripts fail)

### In app/main.py, find this:
```python
async def get_embedding(text: str) -> list[float]:
    resp = await openai_client.embeddings.create(
        input=text,
        model="text-embedding-3-small",
    )
    return resp.data[0].embedding
```

### Replace with:
```python
async def get_embedding(text: str) -> list[float]:
    """
    Get embedding via circuit-breaker-protected embed_text.
    """
    from app.services.infra import embed_text
    return await embed_text(text)
```

---

## ROLLBACK (if needed)

```bash
cd "/Users/michaelweiss/RAG API/voiceroi-rag-api"
git checkout app/main.py app/services/infra.py
fly deploy --now
```
