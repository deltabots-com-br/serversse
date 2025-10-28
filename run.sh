#!/bin/bash
# run.sh (Versão aprimorada usando ENVs)

# Lê as variáveis de ambiente, com fallbacks seguros
PORT=${APP_PORT:-8000}
WORKERS=${UVICORN_WORKERS:-1} # 1 como um fallback seguro se a variável não for definida

echo "Iniciando servidor FastAPI com Uvicorn na porta $PORT e $WORKERS workers..."

# Executa o servidor ASGI Uvicorn
uvicorn main:app --host 0.0.0.0 --port $PORT --workers $WORKERS
