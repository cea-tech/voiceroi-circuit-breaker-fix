#!/bin/bash
# VoiceROI Circuit Breaker Quick Fix Script
# Run this on Mac with Claude Code

set -e

RAG_API_PATH="/Users/michaelweiss/RAG API/voiceroi-rag-api"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     VOICEROI CIRCUIT BREAKER FIX                            ║"
echo "╚══════════════════════════════════════════════════════════════╝"

# Step 1: Backup
echo ""
echo "[1/5] Backing up files..."
cp "$RAG_API_PATH/app/main.py" "$RAG_API_PATH/app/main.py.backup_$(date +%Y%m%d_%H%M%S)"
echo "  ✓ Backup created"

# Step 2: Find and show current get_embedding
echo ""
echo "[2/5] Current get_embedding function:"
grep -n -A 8 "async def get_embedding" "$RAG_API_PATH/app/main.py" | head -12

# Step 3: Apply fix using Python
echo ""
echo "[3/5] Applying fix..."
python3 << 'PYTHON_EOF'
import re

main_path = "/Users/michaelweiss/RAG API/voiceroi-rag-api/app/main.py"

with open(main_path, 'r') as f:
    content = f.read()

# New get_embedding function
new_func = '''async def get_embedding(text: str) -> list[float]:
    """
    Get embedding via circuit-breaker-protected embed_text.
    FIXED: Now routes through infra.embed_text which uses embedding_breaker.
    """
    from app.services.infra import embed_text
    return await embed_text(text)'''

# Pattern to find get_embedding function
# Match from "async def get_embedding" to "return resp.data[0].embedding" or similar
pattern = r'async def get_embedding\(text: str\)[^\n]*\n(?:.*\n)*?.*return.*embedding.*'

if re.search(pattern, content):
    content = re.sub(pattern, new_func, content)
    print("  ✓ Replaced get_embedding function")
else:
    # Alternative simpler pattern
    pattern2 = r'async def get_embedding\([^)]+\):[^}]+?return[^\n]+embedding'
    if re.search(pattern2, content, re.DOTALL):
        content = re.sub(pattern2, new_func, content, flags=re.DOTALL)
        print("  ✓ Replaced get_embedding (alt pattern)")
    else:
        print("  ⚠ Could not find get_embedding - manual edit needed")

# Update version
old_version = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', content)
if old_version:
    print(f"  Old version: {old_version.group(1)}")
content = re.sub(r'APP_VERSION\s*=\s*"[^"]+"', 'APP_VERSION = "1.0.6-circuit-breakers-fixed"', content)
print("  ✓ Updated APP_VERSION to 1.0.6-circuit-breakers-fixed")

with open(main_path, 'w') as f:
    f.write(content)
print("  ✓ Saved main.py")
PYTHON_EOF

# Step 4: Verify fix
echo ""
echo "[4/5] Verifying fix..."
echo "  get_embedding now:"
grep -n -A 6 "async def get_embedding" "$RAG_API_PATH/app/main.py" | head -8
echo ""
echo "  Version:"
grep "APP_VERSION" "$RAG_API_PATH/app/main.py"

# Step 5: Deploy instructions
echo ""
echo "[5/5] Ready to deploy!"
echo ""
echo "Run these commands:"
echo "  cd \"$RAG_API_PATH\""
echo "  fly deploy --now"
echo ""
echo "Then verify with:"
echo "  curl -s https://voiceroi-rag-api.fly.dev/healthz"
echo "  # Send test queries and check metrics"
