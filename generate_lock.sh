#!/bin/bash
# Corre este script uma vez na tua máquina para gerar o uv.lock
# Requer: uv instalado (pip install uv)
cd "$(dirname "$0")"
source .venv/bin/activate 2>/dev/null || true
pip install uv --quiet
uv lock
echo "uv.lock gerado com sucesso!"
