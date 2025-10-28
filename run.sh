#!/bin/bash
# run.sh (Atualizado para Forçar Logs de Erro)

PORT=${APP_PORT:-8000}
WORKERS=${UVICORN_WORKERS:-1} 

echo "--- EXECUTANDO COMANDO DE STARTUP DO UVICORN ---"
echo "Porta: $PORT, Workers: $WORKERS"
echo "------------------------------------------------"

# Executa o Uvicorn e redireciona o stderr (2) para o stdout (1)
# O erro real de 'ImportError' ou configuração deve aparecer aqui
uvicorn main:app --host 0.0.0.0 --port $PORT --workers $WORKERS 2>&1
