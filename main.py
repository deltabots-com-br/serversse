# main.py
import json
import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
import redis.asyncio as aioredis # Cliente Redis assíncrono

# --- Configuração do Redis e Variáveis de Ambiente ---

# Ponto de Diagnóstico: Mostra a leitura da ENV
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
print(f"DIAGNÓSTICO: REDIS_URL lida do ambiente: {REDIS_URL}")

# Variável global para armazenar o cliente Redis
redis_client: aioredis.Redis = None


# --- Lifespan: Inicialização e Fechamento do Redis ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Inicia e fecha a conexão com o Redis.
    """
    global redis_client
    print("DIAGNÓSTICO: --- 1. INICIANDO O LIFESPAN DA APLICAÇÃO ---")
    
    try:
        # Tenta a conexão com o URL configurado
        redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
        await redis_client.ping()
        print(f"✅ DIAGNÓSTICO: 2. Conexão com Redis estabelecida com sucesso!")
        
    except Exception as e:
        # Se a conexão falhar, loga o erro CRÍTICO e força a parada (fail-fast)
        print(f"❌ DIAGNÓSTICO: 2. FALHA CRÍTICA ao conectar ao Redis em {REDIS_URL}: {e}")
        
        # Em produção, você pode querer forçar o container a parar para que o orquestrador reinicie.
        # Caso o problema seja persistente, a EasyPanel mostrará o status 'CrashLoopBackOff'
        # ou 'Exited'. Comente a linha abaixo se preferir que a API suba mesmo sem o Redis
        # (mas as rotas SSE não funcionarão).
        # os._exit(1)
        
    yield # A aplicação está rodando (aguardando requisições)

    # Fechamento do Redis ao desligar
    if redis_client:
        await redis_client.close()
        print("🛑 DIAGNÓSTICO: Conexão com Redis fechada.")

app = FastAPI(lifespan=lifespan)
print("DIAGNÓSTICO: --- 3. FastAPI App inicializado. Aguardando o Uvicorn... ---")


# --- Dependências de Injeção ---

async def get_redis() -> aioredis.Redis:
    """Dependência para obter o cliente Redis, garantindo que foi inicializado."""
    if redis_client is None:
        # Gera erro 503 Service Unavailable se o Redis não estiver vivo
        raise HTTPException(status_code=503, detail="Serviço de Mensageria (Redis) indisponível.")
    return redis_client

# --- Segurança e Rotas Dinâmicas ---

def require_auth_and_get_channel(channel_id: str, request: Request):
    """
    Dependência de segurança para autorizar o acesso ao canal dinâmico.
    """
    user_id_header = request.headers.get("X-User-ID")
    
    # Validação da Rota Dinâmica
    if not channel_id.isalnum(): 
        raise HTTPException(status_code=400, detail="ID de canal inválido.")
        
    # Autorização: Verifica se o usuário tem permissão para assinar este canal
    if user_id_header != channel_id:
        raise HTTPException(status_code=403, detail="Acesso negado ao canal: ID de usuário não corresponde ou cabeçalho 'X-User-ID' ausente.")
        
    return f"sse_channel:{channel_id}"

# --- Rota Dinâmica SSE (O Consumidor) ---

@app.get("/stream/{channel_id}")
async def event_stream(
    request: Request,
    redis_channel: str = Depends(require_auth_and_get_channel),
    r: aioredis.Redis = Depends(get_redis)
):
    """
    Endpoint SSE que assina o canal dinâmico do Redis.
    """
    
    print(f"DIAGNÓSTICO: Novo cliente conectando-se ao canal {redis_channel}")

    async def event_generator():
        # Cria um objeto PubSub e se inscreve no canal
        pubsub = r.pubsub()
        await pubsub.subscribe(redis_channel)

        try:
            while True:
                if await request.is_disconnected():
                    print(f"DIAGNÓSTICO: Cliente desconectado de {redis_channel}.")
                    break
                
                # Timeout reduzido para verificar mais rápido a desconexão
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5) 
                
                if message and message.get('data'):
                    try:
                        data_str = message.get('data')
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        print(f"DIAGNÓSTICO: Erro ao decodificar JSON do Redis: {data_str}")
                        continue

                    # Formata a mensagem para o padrão SSE
                    yield {
                        "event": data.get("event", "update"), 
                        "data": json.dumps(data.get("payload")) 
                    }
                else:
                    # Envia um "keep-alive" a cada 5s (o timeout atual) se não houver mensagem
                    yield {"event": "keep-alive", "data": ""}

        except asyncio.CancelledError:
            print(f"DIAGNÓSTICO: Conexão SSE com {redis_channel} cancelada (provavelmente shutdown).")
        except Exception as e:
            print(f"ERRO CRÍTICO no gerador de eventos para {redis_channel}: {e}")
        finally:
            await pubsub.unsubscribe(redis_channel)
            await pubsub.close()
            print(f"DIAGNÓSTICO: PubSub para {redis_channel} finalizado.")

    return EventSourceResponse(event_generator())


# --- Rota de Publicação (O Produtor) ---

@app.post("/publish/{channel_id}")
async def publish_message(
    channel_id: str,
    message: dict,
    r: aioredis.Redis = Depends(get_redis)
):
    """
    Rota para publicar uma mensagem no canal do Redis.
    """
    
    # Validação do channel_id para ser seguro
    if not channel_id.isalnum():
        raise HTTPException(status_code=400, detail="ID de canal inválido para publicação.")

    payload = {
        "event": message.get("event", "update"),
        "payload": message.get("data")
    }
    
    redis_channel = f"sse_channel:{channel_id}"
    print(f"DIAGNÓSTICO: Publicando mensagem em {redis_channel}")
    await r.publish(redis_channel, json.dumps(payload))
    
    return JSONResponse(
        content={"status": "published", "channel": channel_id},
        status_code=202 
    )
