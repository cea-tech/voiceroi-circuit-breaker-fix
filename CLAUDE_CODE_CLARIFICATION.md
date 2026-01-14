# CLAUDE CODE: Clarification on the Circuit Breaker Bug

## ✅ What You Found Is Correct

You correctly identified:
- `infra.py` has `embed_text()` wrapped with `embedding_breaker.call()`
- `main.py` line 845-846 has a fallback that uses `embed_text`

## ❌ THE ACTUAL BUG

The problem is the **PRIMARY PATH** (not the fallback) bypasses the breaker.

Look at `get_embedding()` in `main.py` around lines 816-852:

```python
async def get_embedding(text: str) -> list[float]:
    # PRIMARY PATH - Check semantic cache first
    if semantic_cache:
        cached = await semantic_cache.get(text)  # <-- This may call OpenAI DIRECTLY
        if cached:
            return cached
    
    # FALLBACK PATH (line 845-846) - only reached if cache miss
    from app.services.infra import embed_text
    embedding = await embed_text(text)  # <-- This uses breaker (but rarely called!)
    return embedding
```

**The bug:** `SemanticEmbeddingCache.get()` or its internal embedding logic calls OpenAI **directly** without going through `embedding_breaker`.

## 🔍 DIAGNOSTIC STEP

Run this to confirm the bug:

```bash
curl -s https://voiceroi-rag-api.fly.dev/metrics | grep -E "circuit.*calls.*total"
```

**If you see:**
```
circuit_breaker_calls_total{name="embedding"} 0    <-- BUG CONFIRMED
circuit_breaker_calls_total{name="redis"} 15       <-- Redis breaker works
```

This proves: queries hit Redis (15 calls) but NOT the embedding breaker (0 calls).

## 🔧 THE FIX

You need to find WHERE `SemanticEmbeddingCache` creates embeddings and make it use `embed_text()`.

### Step 1: Find the SemanticEmbeddingCache class

```bash
grep -rn "class SemanticEmbeddingCache" "/Users/michaelweiss/RAG API/voiceroi-rag-api/app/"
grep -rn "embeddings.create" "/Users/michaelweiss/RAG API/voiceroi-rag-api/app/"
```

### Step 2: Look for direct OpenAI calls

The bug is wherever you find code like:
```python
await openai_client.embeddings.create(...)
```
that is NOT inside `infra.py`'s `embed_text()` function.

### Step 3: Replace direct calls with embed_text

Every place that does:
```python
response = await openai_client.embeddings.create(input=text, model="text-embedding-3-small")
embedding = response.data[0].embedding
```

Should instead do:
```python
from app.services.infra import embed_text
embedding = await embed_text(text)
```

## 📋 SPECIFIC LOCATIONS TO CHECK

1. **`app/main.py`** - `get_embedding()` function's primary path before the fallback
2. **`app/services/semantic_cache.py`** (or similar) - `SemanticEmbeddingCache` class
3. **Any file** with `embeddings.create` that isn't `infra.py`

## ✅ VERIFY FIX WORKED

After making changes and deploying:

```bash
# Deploy
cd "/Users/michaelweiss/RAG API/voiceroi-rag-api"
fly deploy --now

# Wait 30 seconds, then send test queries
sleep 30
for i in 1 2 3 4 5; do
  curl -s -X POST "https://voiceroi-rag-api.fly.dev/query" \
    -H "Content-Type: application/json" \
    -H "x-api-key: -qTH30qS0b8iCQDlEUGlFYFybNxXwY5Vd7tBbj4jV7M" \
    -d "{\"question\": \"Test query $RANDOM about investment\"}" > /dev/null
done

# Check metrics - embedding MUST now be > 0
curl -s https://voiceroi-rag-api.fly.dev/metrics | grep -E "circuit.*calls.*total"
```

**SUCCESS:**
```
circuit_breaker_calls_total{name="embedding"} 5   <-- NOW > 0!
circuit_breaker_calls_total{name="redis"} 20
```
