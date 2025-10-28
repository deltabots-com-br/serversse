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

# O EasyPanel deve fornecer a URL do Redis via variável de ambiente.
# Use 'redis://localhost:6379' como fallback para desenvolvimento local.
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Variável global para armazenar o cliente Redis
redis_client: aioredis.Redis = None


# --- Lifespan: Inicialização e Fechamento do Redis ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Inicia e fecha a conexão com o Redis.
    """
    global redis_client
    try:
        # A decode_responses=True garante que as strings retornadas do Redis sejam decodificadas
        redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
        await redis_client.ping()
        print(f"✅ Conexão com Redis estabelecida em: {REDIS_URL}")
    except Exception as e:
        # É crucial falhar se não conseguir conectar, especialmente em produção
        print(f"❌ FALHA CRÍTICA ao conectar ao Redis: {e}")
        # Em um cenário real de produção, você pode relançar a exceção ou sair.
        
    yield # A aplicação está rodando

    # Fechamento do Redis ao desligar
    if redis_client:
        await redis_client.close()
        print("🛑 Conexão com Redis fechada.")

app = FastAPI(lifespan=lifespan)


# --- Dependências de Injeção ---

async def get_redis() -> aioredis.Redis:
    """Dependência para obter o cliente Redis, garantindo que foi inicializado."""
    if redis_client is None:
        raise HTTPException(status_code=500, detail="Serviço Redis indisponível.")
    return redis_client

# --- Segurança e Rotas Dinâmicas ---

def require_auth_and_get_channel(channel_id: str, request: Request):
    """
    Dependência de segurança para autorizar o acesso ao canal dinâmico.
    
    A implementação atual requer que o header "X-User-ID"
    corresponda ao {channel_id} da rota.
    """
    user_id_header = request.headers.get("X-User-ID")
    
    # Validação da Rota Dinâmica
    if not channel_id.isalnum(): # Aceita letras e números
        raise HTTPException(status_code=400, detail="ID de canal inválido.")
        
    # Autorização: Verifica se o usuário tem permissão para assinar este canal
    if user_id_header != channel_id:
        # No front-end, o cliente precisa incluir o header X-User-ID
        raise HTTPException(status_code=403, detail="Acesso negado ao canal: ID de usuário não corresponde.")
        
    # O canal do Redis será prefixado
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
    
    async def event_generator():
        # Cria um objeto PubSub e se inscreve no canal
        pubsub = r.pubsub()
        await pubsub.subscribe(redis_channel)

        try:
            while True:
                # 1. Verifica se o cliente web desconectou
                if await request.is_disconnected():
                    print(f"Cliente desconectado de {redis_channel}.")
                    break
                
                # 2. Aguarda a próxima mensagem do Redis
                # O timeout garante que o loop não trave e permite checar a desconexão
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
                
                if message and message.get('data'):
                    try:
                        # O dado do Redis é uma string JSON.
                        data_str = message.get('data')
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        print(f"Erro ao decodificar JSON do Redis: {data_str}")
                        continue

                    # Formata a mensagem para o padrão SSE
                    yield {
                        "event": data.get("event", "update"), # Tipo de evento (ex: 'order_status', 'new_notification')
                        "data": json.dumps(data.get("payload")) # O payload real
                    }
                else:
                    # 3. Envia um "keep-alive" se não houver mensagem, 
                    # útil para evitar que proxies (como Nginx/Load Balancers) fechem a conexão
                    yield {"event": "keep-alive", "data": ""}

        except asyncio.CancelledError:
            # Captura exceção se o gerador for cancelado (shutdown do servidor)
            pass 
        finally:
            # 4. Garante que a assinatura e o objeto PubSub sejam fechados
            await pubsub.unsubscribe(redis_channel)
            await pubsub.close()
            print(f"PubSub para {redis_channel} finalizado.")

    # Retorna o EventSourceResponse
    # O parâmetro 'ping' padrão do SSE-Starlette ajuda a manter a conexão viva
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
    Idealmente, esta rota só deve ser acessível internamente ou por um serviço autorizado.
    """
    
    # Crie o payload no formato que o consumidor espera
    payload = {
        "event": message.get("event", "update"),
        "payload": message.get("data")
    }
    
    # Publica no canal do Redis
    await r.publish(f"sse_channel:{channel_id}", json.dumps(payload))
    
    return JSONResponse(
        content={"status": "published", "channel": channel_id},
        status_code=202 # Accepted
    )
