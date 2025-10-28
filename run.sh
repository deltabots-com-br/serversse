#!/bin/bash
# run.sh

# A porta 8000 é a porta padrão que o Uvicorn irá expor,
# e que você configurará no EasyPanel.
PORT=8000

echo "Iniciando servidor FastAPI com Uvicorn na porta $PORT..."

# Executa o servidor ASGI Uvicorn
# --host 0.0.0.0: permite acessos externos (obrigatório em containers/EasyPanel)
# --workers 4: O EasyPanel é multi-core; utilize workers para melhor desempenho.
uvicorn main:app --host 0.0.0.0 --port $PORT --workers 4
