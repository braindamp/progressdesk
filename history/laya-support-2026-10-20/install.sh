#!/usr/bin/env bash
# Build the Laya decision-model service in its own environment.
#
# It lives outside progressDesk on purpose: the product is zero-dependency and
# stays that way. This is a service it talks to over HTTP, not a library it
# imports. Everything lands on D:, including the uv cache, because C: is tight.
set -euo pipefail

export UV_CACHE_DIR="D:/Coding/.cache/uv"
VENV="D:/Coding/laya-serve/.venv"
PY="$VENV/Scripts/python.exe"
TORCH_INDEX="https://download.pytorch.org/whl/cu126"

echo "== 1. venv (3.12, matching the product) =="
uv venv "$VENV" --python 3.12

echo "== 2. torch (cu126, for the 3080 Ti) =="
uv pip install --python "$PY" --index-url "$TORCH_INDEX" torch

echo "== 3. laya =="
uv pip install --python "$PY" laya

echo "== 4. what landed =="
"$PY" -c "import laya, torch, transformers, sys
print('python  ', sys.version.split()[0])
print('laya    ', getattr(laya, '__version__', '?'))
print('torch   ', torch.__version__, 'cuda', torch.cuda.is_available())
print('device  ', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu')
print('transf  ', transformers.__version__)"

echo "== done =="
