# VoiceROI Circuit Breaker Fix

## 🚨 CRITICAL BUG IDENTIFIED

The embedding circuit breakers (`embedding_breaker`, `openai_breaker`) show **0 calls** after queries because the query path bypasses the breaker-wrapped functions.

**Evidence:** After 10+ queries: `circuit_breaker_calls_total{name="embedding"} 0`

---

## 📦 This Package Contains

| File | Purpose |
|------|---------|
| `CLAUDE_CODE_EXECUTE_STEPS.md` | Step-by-step execution guide with copy-paste commands |
| `CLAUDE_CODE_CIRCUIT_BREAKER_FIX.md` | Detailed implementation reference |
| `CLAUDE_EXECUTE_NOW.py` | Python automation script (optional) |

---

## 🚀 CLAUDE CODE: Quick Start

### Step 1: Clone this repo
```bash
cd /Users/michaelweiss
git clone https://github.com/cea-tech/voiceroi-circuit-breaker-fix.git
cd voiceroi-circuit-breaker-fix
```

### Step 2: Read the execution guide
```bash
cat CLAUDE_CODE_EXECUTE_STEPS.md
```

### Step 3: Execute the fix
The main fix is in `app/main.py` - change `get_embedding()` to use `embed_text` from `infra.py`:

**FIND:**
```python
async def get_embedding(text: str) -> list[float]:
    resp = await openai_client.embeddings.create(
        input=text,
        model="text-embedding-3-small",
    )
    return resp.data[0].embedding
```

**REPLACE WITH:**
```python
async def get_embedding(text: str) -> list[float]:
    """Routes through circuit-breaker-protected embed_text."""
    from app.services.infra import embed_text
    return await embed_text(text)
```

### Step 4: Update version and deploy
```bash
cd "/Users/michaelweiss/RAG API/voiceroi-rag-api"
# Update APP_VERSION to "1.0.6-circuit-breakers-fixed" in app/main.py
fly deploy --now
```

### Step 5: Verify fix worked
```bash
# Send test queries
for i in 1 2 3 4 5; do
  curl -s -X POST "https://voiceroi-rag-api.fly.dev/query" \
    -H "Content-Type: application/json" \
    -H "x-api-key: -qTH30qS0b8iCQDlEUGlFYFybNxXwY5Vd7tBbj4jV7M" \
    -d '{"question": "Test query '$RANDOM' about VoiceROI"}' > /dev/null
done

# Check metrics - MUST show embedding calls > 0
curl -s https://voiceroi-rag-api.fly.dev/metrics | grep "calls_total"
```

---

## ✅ Success Criteria

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

## 📂 Target Files

- `/Users/michaelweiss/RAG API/voiceroi-rag-api/app/main.py` - Fix `get_embedding()`
- `/Users/michaelweiss/RAG API/voiceroi-rag-api/app/services/infra.py` - Canonical `embed_text()`
- `/Users/michaelweiss/RAG API/voiceroi-rag-api/app/middleware/circuit_breaker.py` - Breaker implementation

---

## 🔄 Rollback (if needed)

```bash
cd "/Users/michaelweiss/RAG API/voiceroi-rag-api"
git checkout app/main.py app/services/infra.py
fly deploy --now
```
