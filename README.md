# VoiceROI Circuit Breaker Fix

## 🎯 THE BUG (Read This First!)

**Symptom:** After 10+ queries, metrics show:
```
circuit_breaker_calls_total{name="embedding"} 0    ← BUG! Should be > 0
circuit_breaker_calls_total{name="redis"} 15       ← Works fine
```

**Root Cause:** The **primary embedding path** bypasses `embedding_breaker`. 

The fallback in `get_embedding()` (line ~845) uses `embed_text()` correctly, BUT:
- `SemanticEmbeddingCache` or the primary path calls OpenAI **directly**
- This direct call doesn't go through `embedding_breaker`

---

## 🔍 CLAUDE CODE: Diagnostic Steps

### Step 1: Confirm the bug exists
```bash
curl -s https://voiceroi-rag-api.fly.dev/metrics | grep -E "circuit.*calls.*total"
```

If `embedding` shows 0, the bug is confirmed.

### Step 2: Find ALL direct OpenAI embedding calls
```bash
cd "/Users/michaelweiss/RAG API/voiceroi-rag-api"
grep -rn "embeddings.create" app/
```

**You should find calls in:**
- `app/services/infra.py` - This is CORRECT (breaker-wrapped)
- Anywhere else - This is the BUG (bypasses breaker)

### Step 3: Check get_embedding() primary path
```bash
grep -n -A 30 "async def get_embedding" app/main.py
```

Look for code like:
```python
if semantic_cache:
    cached = await semantic_cache.get(text)  # Does THIS call OpenAI directly?
```

### Step 4: Check SemanticEmbeddingCache
```bash
grep -rn "class SemanticEmbeddingCache" app/
# Then read that file
```

---

## 🔧 THE FIX

**Every** place that does this:
```python
response = await openai_client.embeddings.create(input=text, model="...")
```

Must instead do this:
```python
from app.services.infra import embed_text
embedding = await embed_text(text)
```

This ensures ALL embedding calls go through `embedding_breaker`.

---

## 📦 Files in This Repo

| File | Description |
|------|-------------|
| `CLAUDE_CODE_CLARIFICATION.md` | **READ THIS FIRST** - Explains the actual bug |
| `CLAUDE_CODE_EXECUTE_STEPS.md` | Step-by-step fix guide |
| `CLAUDE_CODE_CIRCUIT_BREAKER_FIX.md` | Full implementation details |

---

## ✅ Success Criteria

After fix + deploy:
```
circuit_breaker_calls_total{name="embedding"} > 0  ← FIXED!
```
