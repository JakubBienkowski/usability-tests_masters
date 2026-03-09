import json
import asyncio
import aio_pika
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()
RABBITMQ_URL = "amqp://guest:guest@rabbitmq/"

async def push_to_queue(data: dict):
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        await channel.default_exchange.publish(
            aio_pika.Message(body=json.dumps(data).encode()),
            routing_key="ux_events",
        )

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            data['session_id'] = session_id
            # Szybka wrzutka do kolejki i powrót do słuchania
            await push_to_queue(data)
    except WebSocketDisconnect:
        print(f"Sesja {session_id} zakończona.")