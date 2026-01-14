# CLAUDE CODE: Circuit Breaker Integration Fix

## CRITICAL BUG IDENTIFIED
**Issue:** `embedding_breaker` and `openai_breaker` show 0 calls after queries.
**Root Cause:** Query path bypasses breaker-wrapped functions.
**Evidence:** After 10+ queries: `circuit_breaker_calls_total{name="embedding"} 0`

---

## PHASE 1: Identify All Embedding Call Sites

### Step 1.1: Search for embedding calls
```bash
cd "/Users/michaelweiss/RAG API/voiceroi-rag-api"
grep -rn "embeddings.create" app/
grep -rn "get_embedding" app/
grep -rn "embed_text" app/
grep -rn "openai_client" app/
```

**Expected findings:**
- `app/services/infra.py` - contains `embed_text()` (should be breaker-wrapped)
- `app/main.py` - contains `get_embedding()` or direct OpenAI calls (THIS IS THE BUG)

---

## PHASE 2: Fix infra.py as Canonical Embedding Source

### Step 2.1: Read current infra.py
```bash
cat "/Users/michaelweiss/RAG API/voiceroi-rag-api/app/services/infra.py"
```

### Step 2.2: Replace infra.py with fixed version

**REPLACE ENTIRE FILE** `/Users/michaelweiss/RAG API/voiceroi-rag-api/app/services/infra.py`:

```python
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

# Redis connection (initialized lazily)
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
    All embedding calls in the entire codebase MUST route through here.
    Protected by embedding_breaker circuit breaker.
    
    Args:
        text: Text to embed
        
    Returns:
        List of floats representing the embedding vector
        
    Raises:
        CircuitBreakerOpen: If embedding service is unavailable
    """
    async def _do_embed():
        response = await openai_client.embeddings.create(
            input=text,
            model="text-embedding-3-small",
        )
        return response.data[0].embedding
    
    try:
        embedding = await embedding_breaker.call(_do_embed)
        logger.debug(f"embed_text: Generated embedding for '{text[:50]}...' via breaker")
        return embedding
    except CircuitBreakerOpen:
        logger.warning(f"embed_text: Circuit OPEN, cannot embed '{text[:50]}...'")
        raise
    except Exception as e:
        logger.error(f"embed_text: Failed to embed text: {e}")
        raise


async def health_check() -> dict:
    """
    Check health of Redis connection.
    Protected by redis_breaker circuit breaker.
    """
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
        logger.error(f"Health check failed: {e}")
        return {"redis": "error", "status": "unhealthy", "error": str(e)}
```

---

## PHASE 3: Fix main.py to Use Canonical embed_text

### Step 3.1: Read current main.py get_embedding function
```bash
grep -n -A 20 "async def get_embedding" "/Users/michaelweiss/RAG API/voiceroi-rag-api/app/main.py"
```

### Step 3.2: Find and replace get_embedding in main.py

**FIND THIS PATTERN** (or similar):
```python
async def get_embedding(text: str) -> list[float]:
    """Get embedding for semantic cache lookup."""
    resp = await openai_client.embeddings.create(
        input=text,
        model="text-embedding-3-small",
    )
    return resp.data[0].embedding
```

**REPLACE WITH:**
```python
async def get_embedding(text: str) -> list[float]:
    """
    Get embedding for semantic cache lookup.
    Routes through canonical embed_text() which is protected by circuit breaker.
    """
    from app.services.infra import embed_text
    return await embed_text(text)
```

### Step 3.3: Update imports at top of main.py

**ADD these imports** near the top (after existing imports):
```python
from app.services.infra import embed_text
from app.middleware.circuit_breaker import (
    CircuitBreakerOpen,
    CircuitBreakerRegistry,
    embedding_breaker,
    redis_breaker,
    openai_breaker,
)
```

### Step 3.4: Update APP_VERSION
```python
APP_VERSION = "1.0.6-circuit-breakers-fixed"
```

---

## PHASE 4: Fix /query Endpoint to Handle CircuitBreakerOpen

### Step 4.1: Find the /query endpoint
```bash
grep -n -A 50 '@app.post("/query")' "/Users/michaelweiss/RAG API/voiceroi-rag-api/app/main.py"
```

### Step 4.2: Wrap the query logic with proper exception handling

**ADD this try/except wrapper** around the main query logic:

```python
@app.post("/query")
async def query_endpoint(request: Request, x_api_key: str = Header(...)):
    """Query the knowledge base with circuit breaker protection."""
    
    # Validate API key
    if x_api_key != os.getenv("API_KEY"):
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    body = await request.json()
    question = body.get("question", "").strip()
    
    if not question:
        raise HTTPException(status_code=400, detail="Question is required")
    
    request_id = secrets.token_hex(4)
    start_time = time.time()
    
    try:
        # === EXISTING QUERY LOGIC HERE ===
        # (Keep all existing layer traversal code)
        # ...
        
        # Return normal response
        return result
        
    except CircuitBreakerOpen as e:
        # Handle circuit breaker trip gracefully
        logger.warning(f"[{request_id}] Circuit breaker OPEN: {e.name}")
        
        if e.name in ("openai", "embedding"):
            error_code = "embedding_unavailable"
            message = "Embedding service temporarily unavailable. Please retry."
        elif e.name == "redis":
            error_code = "kb_unavailable"
            message = "Knowledge base temporarily unavailable. Please retry."
        else:
            error_code = "dependency_unavailable"
            message = "A dependency is temporarily unavailable."
        
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "error": error_code,
                "circuit": e.name,
                "message": message,
                "retry_after": e.retry_after,
                "source": "CIRCUIT_OPEN",
                "request_id": request_id,
            },
            headers={"Retry-After": str(int(e.retry_after))},
        )
```

---

## PHASE 5: Standardize Prometheus Metrics

### Step 5.1: Update metrics.py

**REPLACE** `/Users/michaelweiss/RAG API/voiceroi-rag-api/app/metrics.py`:

```python
"""
VoiceROI RAG API - Prometheus Metrics
Standardized metric names with voiceroi_ prefix.
"""

from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST

# Circuit Breaker Metrics
voiceroi_circuit_calls_total = Counter(
    "voiceroi_circuit_calls_total",
    "Total calls through circuit breaker",
    ["name"],
)

voiceroi_circuit_successes_total = Counter(
    "voiceroi_circuit_successes_total",
    "Successful calls through circuit breaker",
    ["name"],
)

voiceroi_circuit_failures_total = Counter(
    "voiceroi_circuit_failures_total",
    "Failed calls through circuit breaker",
    ["name"],
)

voiceroi_circuit_rejections_total = Counter(
    "voiceroi_circuit_rejections_total",
    "Rejected calls (circuit open)",
    ["name"],
)

voiceroi_circuit_timeouts_total = Counter(
    "voiceroi_circuit_timeouts_total",
    "Timed out calls",
    ["name"],
)

voiceroi_circuit_state = Gauge(
    "voiceroi_circuit_state",
    "Current circuit state (0=CLOSED, 0.5=HALF_OPEN, 1=OPEN)",
    ["name"],
)

voiceroi_circuit_consecutive_opens = Gauge(
    "voiceroi_circuit_consecutive_opens",
    "Number of consecutive OPEN transitions",
    ["name"],
)

voiceroi_circuit_success_rate = Gauge(
    "voiceroi_circuit_success_rate",
    "Success rate percentage",
    ["name"],
)

# Query Metrics
voiceroi_query_total = Counter(
    "voiceroi_query_total",
    "Total queries processed",
    ["layer", "source"],
)

voiceroi_query_latency_seconds = Gauge(
    "voiceroi_query_latency_seconds",
    "Query latency in seconds",
    ["layer"],
)


def get_metrics_output() -> bytes:
    """Generate Prometheus metrics output."""
    return generate_latest()
```

### Step 5.2: Update circuit_breaker.py to use new metrics

**ADD these imports** at top of `app/middleware/circuit_breaker.py`:
```python
from app.metrics import (
    voiceroi_circuit_calls_total,
    voiceroi_circuit_successes_total,
    voiceroi_circuit_failures_total,
    voiceroi_circuit_rejections_total,
    voiceroi_circuit_timeouts_total,
    voiceroi_circuit_state,
    voiceroi_circuit_consecutive_opens,
    voiceroi_circuit_success_rate,
)
```

**UPDATE the call() method** to increment metrics:

In the `call()` method, add metric increments:

```python
async def call(self, func, *args, **kwargs):
    """Execute function with circuit breaker protection."""
    async with self._lock:
        # Update call counter
        self.metrics.total_calls += 1
        voiceroi_circuit_calls_total.labels(name=self.name).inc()
        
        # Check if circuit is OPEN
        if self._state == CircuitState.OPEN:
            if time.time() < self._next_retry_time:
                self.metrics.total_rejections += 1
                voiceroi_circuit_rejections_total.labels(name=self.name).inc()
                retry_after = self._next_retry_time - time.time()
                raise CircuitBreakerOpen(self.name, retry_after)
            else:
                # Transition to HALF_OPEN
                self._transition_to(CircuitState.HALF_OPEN)
    
    # Execute the function
    try:
        if asyncio.iscoroutinefunction(func):
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=self.call_timeout,
            )
        else:
            result = func(*args, **kwargs)
        
        await self._record_success()
        return result
        
    except asyncio.TimeoutError:
        self.metrics.total_timeouts += 1
        voiceroi_circuit_timeouts_total.labels(name=self.name).inc()
        await self._record_failure()
        raise
        
    except Exception as e:
        if not self._should_ignore_exception(e):
            await self._record_failure()
        raise


async def _record_success(self):
    """Record a successful call."""
    async with self._lock:
        self.metrics.total_successes += 1
        voiceroi_circuit_successes_total.labels(name=self.name).inc()
        self.failure_count = 0
        self.success_count += 1
        self.metrics.last_success_time = time.time()
        
        # Update state gauge
        self._update_state_metrics()
        
        if self._state == CircuitState.HALF_OPEN:
            if self.success_count >= self.success_threshold:
                self._transition_to(CircuitState.CLOSED)


async def _record_failure(self):
    """Record a failed call."""
    async with self._lock:
        self.metrics.total_failures += 1
        voiceroi_circuit_failures_total.labels(name=self.name).inc()
        self.failure_count += 1
        self.success_count = 0
        self.metrics.last_failure_time = time.time()
        
        # Update state gauge
        self._update_state_metrics()
        
        if self._state == CircuitState.HALF_OPEN:
            self._transition_to(CircuitState.OPEN)
        elif self._state == CircuitState.CLOSED:
            if self.failure_count >= self.failure_threshold:
                self._transition_to(CircuitState.OPEN)


def _update_state_metrics(self):
    """Update Prometheus state gauges."""
    state_value = {
        CircuitState.CLOSED: 0.0,
        CircuitState.HALF_OPEN: 0.5,
        CircuitState.OPEN: 1.0,
    }.get(self._state, 0.0)
    
    voiceroi_circuit_state.labels(name=self.name).set(state_value)
    voiceroi_circuit_consecutive_opens.labels(name=self.name).set(self.metrics.consecutive_opens)
    voiceroi_circuit_success_rate.labels(name=self.name).set(self.metrics.success_rate)
```

---

## PHASE 6: Deploy and Verify

### Step 6.1: Deploy to Fly.io
```bash
cd "/Users/michaelweiss/RAG API/voiceroi-rag-api"
fly deploy --now
```

### Step 6.2: Verify deployment
```bash
curl -s https://voiceroi-rag-api.fly.dev/healthz | jq .
```

**Expected:**
```json
{
  "ok": true,
  "version": "1.0.6-circuit-breakers-fixed"
}
```

### Step 6.3: Run integration test
```bash
# Send 5 unique queries to force real embeddings
for i in 1 2 3 4 5; do
  curl -s -X POST "https://voiceroi-rag-api.fly.dev/query" \
    -H "Content-Type: application/json" \
    -H "x-api-key: -qTH30qS0b8iCQDlEUGlFYFybNxXwY5Vd7tBbj4jV7M" \
    -d "{\"question\": \"Unique test query $RANDOM about VoiceROI investment terms\"}" > /dev/null
done

echo "Checking metrics..."
curl -s https://voiceroi-rag-api.fly.dev/metrics | grep "voiceroi_circuit_calls_total"
```

**SUCCESS CRITERIA:**
```
voiceroi_circuit_calls_total{name="embedding"} > 0  # MUST BE > 0
voiceroi_circuit_calls_total{name="redis"} > 0
```

---

## VERIFICATION CHECKLIST

- [ ] `grep -rn "embeddings.create" app/` returns ONLY `app/services/infra.py`
- [ ] `grep -rn "get_embedding" app/main.py` shows it calls `embed_text`
- [ ] Version shows `1.0.6-circuit-breakers-fixed`
- [ ] After 5 queries: `voiceroi_circuit_calls_total{name="embedding"} >= 5`
- [ ] Admin endpoint works: `curl -H "x-api-key: ..." .../admin/circuit-breakers`

---

## ROLLBACK (if needed)
```bash
cd "/Users/michaelweiss/RAG API/voiceroi-rag-api"
git stash
fly deploy --now
```
