#!/usr/bin/env python3
"""
CLAUDE CODE EXECUTION SCRIPT
Circuit Breaker Fix for VoiceROI RAG API

Run this in Claude Code on Mac:
    python3 /path/to/CLAUDE_EXECUTE_NOW.py

Or execute sections manually.
"""

import os
import subprocess
import sys

RAG_API_PATH = "/Users/michaelweiss/RAG API/voiceroi-rag-api"

# =============================================================================
# STEP 1: VERIFY CURRENT STATE
# =============================================================================

def step1_verify_state():
    print("\n" + "="*60)
    print("STEP 1: Verifying Current State")
    print("="*60)
    
    os.chdir(RAG_API_PATH)
    
    print("\n[1.1] Finding all embedding call sites...")
    subprocess.run(["grep", "-rn", "embeddings.create", "app/"])
    
    print("\n[1.2] Finding get_embedding calls...")
    subprocess.run(["grep", "-rn", "get_embedding", "app/"])
    
    print("\n[1.3] Current version...")
    subprocess.run(["grep", "-n", "APP_VERSION", "app/main.py"])

# =============================================================================
# STEP 2: FIX INFRA.PY - CANONICAL EMBEDDING FUNCTION
# =============================================================================

INFRA_PY_FIXED = '''\
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
        logger.debug(f"embed_text: Generated embedding via breaker for '{text[:40]}...'")
        return embedding
    except CircuitBreakerOpen:
        logger.warning(f"embed_text: Circuit OPEN, cannot embed '{text[:40]}...'")
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
'''

def step2_fix_infra():
    print("\n" + "="*60)
    print("STEP 2: Fixing infra.py")
    print("="*60)
    
    infra_path = os.path.join(RAG_API_PATH, "app/services/infra.py")
    
    # Backup
    backup_path = infra_path + ".backup"
    if os.path.exists(infra_path):
        with open(infra_path, 'r') as f:
            with open(backup_path, 'w') as b:
                b.write(f.read())
        print(f"[2.1] Backed up to {backup_path}")
    
    # Write fixed version
    with open(infra_path, 'w') as f:
        f.write(INFRA_PY_FIXED)
    print(f"[2.2] Written fixed infra.py")

# =============================================================================
# STEP 3: FIX main.py GET_EMBEDDING
# =============================================================================

GET_EMBEDDING_FIXED = '''
async def get_embedding(text: str) -> list[float]:
    """
    Get embedding for semantic cache lookup.
    Routes through canonical embed_text() which is protected by circuit breaker.
    
    IMPORTANT: This function MUST call embed_text from infra.py to ensure
    all embeddings go through the circuit breaker.
    """
    from app.services.infra import embed_text
    return await embed_text(text)
'''

def step3_fix_main_get_embedding():
    print("\n" + "="*60)
    print("STEP 3: Fixing main.py get_embedding")
    print("="*60)
    
    main_path = os.path.join(RAG_API_PATH, "app/main.py")
    
    with open(main_path, 'r') as f:
        content = f.read()
    
    # Backup
    with open(main_path + ".backup", 'w') as f:
        f.write(content)
    print("[3.1] Backed up main.py")
    
    # Find and replace get_embedding function
    # This is a targeted replacement
    import re
    
    # Pattern to match the get_embedding function
    pattern = r'async def get_embedding\(text: str\)[^:]*:[^}]+?return resp\.data\[0\]\.embedding'
    
    if re.search(pattern, content, re.DOTALL):
        content = re.sub(pattern, GET_EMBEDDING_FIXED.strip(), content, flags=re.DOTALL)
        print("[3.2] Replaced get_embedding function")
    else:
        # Alternative: look for simpler pattern
        alt_pattern = r'async def get_embedding\([^)]+\):[\s\S]*?return[^\n]+embedding'
        if re.search(alt_pattern, content):
            content = re.sub(alt_pattern, GET_EMBEDDING_FIXED.strip(), content)
            print("[3.2] Replaced get_embedding (alt pattern)")
        else:
            print("[3.2] WARNING: Could not find get_embedding pattern. Manual fix needed.")
            print("      Look for 'async def get_embedding' and replace with:")
            print(GET_EMBEDDING_FIXED)
    
    # Update version
    content = re.sub(
        r'APP_VERSION\s*=\s*"[^"]+"',
        'APP_VERSION = "1.0.6-circuit-breakers-fixed"',
        content
    )
    print("[3.3] Updated APP_VERSION")
    
    with open(main_path, 'w') as f:
        f.write(content)
    print("[3.4] Written fixed main.py")

# =============================================================================
# STEP 4: UPDATE METRICS.PY
# =============================================================================

METRICS_PY_FIXED = '''\
"""
VoiceROI RAG API - Prometheus Metrics
Standardized metric names with voiceroi_ prefix.
"""

from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST

# Circuit Breaker Metrics - STANDARDIZED NAMES
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
'''

def step4_fix_metrics():
    print("\n" + "="*60)
    print("STEP 4: Fixing metrics.py")
    print("="*60)
    
    metrics_path = os.path.join(RAG_API_PATH, "app/metrics.py")
    
    if os.path.exists(metrics_path):
        with open(metrics_path, 'r') as f:
            with open(metrics_path + ".backup", 'w') as b:
                b.write(f.read())
        print("[4.1] Backed up metrics.py")
    
    with open(metrics_path, 'w') as f:
        f.write(METRICS_PY_FIXED)
    print("[4.2] Written fixed metrics.py")

# =============================================================================
# STEP 5: DEPLOY AND VERIFY
# =============================================================================

def step5_deploy():
    print("\n" + "="*60)
    print("STEP 5: Deploy to Fly.io")
    print("="*60)
    
    os.chdir(RAG_API_PATH)
    
    print("[5.1] Deploying...")
    result = subprocess.run(["fly", "deploy", "--now"], capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(f"ERROR: {result.stderr}")
        return False
    
    print("\n[5.2] Verifying deployment...")
    subprocess.run(["curl", "-s", "https://voiceroi-rag-api.fly.dev/healthz"])
    
    return True

def step6_verify():
    print("\n" + "="*60)
    print("STEP 6: Verification Test")
    print("="*60)
    
    import time
    import json
    import urllib.request
    import random
    
    API_URL = "https://voiceroi-rag-api.fly.dev"
    API_KEY = "-qTH30qS0b8iCQDlEUGlFYFybNxXwY5Vd7tBbj4jV7M"
    
    print("[6.1] Sending 5 unique queries...")
    for i in range(5):
        q = f"Unique test query {random.randint(10000,99999)} about VoiceROI investment"
        req = urllib.request.Request(
            f"{API_URL}/query",
            data=json.dumps({"question": q}).encode(),
            headers={"Content-Type": "application/json", "x-api-key": API_KEY},
            method="POST"
        )
        try:
            urllib.request.urlopen(req, timeout=10)
            print(f"  Query {i+1}: OK")
        except Exception as e:
            print(f"  Query {i+1}: {e}")
    
    print("\n[6.2] Checking metrics...")
    req = urllib.request.Request(f"{API_URL}/metrics")
    resp = urllib.request.urlopen(req, timeout=10)
    metrics = resp.read().decode()
    
    for line in metrics.split("\n"):
        if "voiceroi_circuit_calls_total" in line or "circuit_breaker_calls_total" in line:
            print(f"  {line}")
    
    # Check success
    if 'voiceroi_circuit_calls_total{name="embedding"}' in metrics:
        import re
        match = re.search(r'voiceroi_circuit_calls_total\{name="embedding"\}\s+(\d+)', metrics)
        if match and int(match.group(1)) > 0:
            print("\n✅ SUCCESS: Embedding circuit breaker is now being invoked!")
            return True
    
    print("\n⚠️ WARNING: Check if embedding breaker calls increased")
    return False


if __name__ == "__main__":
    print("="*60)
    print("VOICEROI CIRCUIT BREAKER FIX SCRIPT")
    print("="*60)
    
    # Run all steps
    step1_verify_state()
    step2_fix_infra()
    step3_fix_main_get_embedding()
    step4_fix_metrics()
    
    print("\n" + "="*60)
    print("READY TO DEPLOY")
    print("="*60)
    print("\nRun these commands manually:")
    print(f'  cd "{RAG_API_PATH}"')
    print("  fly deploy --now")
    print("")
    print("Then run verification:")
    print("  python3 -c 'from CLAUDE_EXECUTE_NOW import step6_verify; step6_verify()'") 
