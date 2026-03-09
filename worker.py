import asyncio
import aio_pika
import json
import os

# Konfiguracja ścieżek
BASE_DIR = "recorded_sessions"

async def on_message(message: aio_pika.IncomingMessage):
    async with message.process():
        data = json.loads(message.body)
        session_id = data.get("session_id", "unknown")
        
        # Tworzymy strukturę plików dla każdej sesji
        session_path = os.path.join(BASE_DIR, session_id)
        os.makedirs(session_path, exist_ok=True)
        
        # Dzielimy logikę zapisu wg typu zdarzenia
        msg_type = data.get("type")
        
        if msg_type == "rrweb_chunk":
            # Zapisujemy nagranie DOM (rrweb)
            with open(f"{session_path}/dom_recording.jsonl", "a") as f:
                f.write(json.dumps(data.get("events")) + "\n")
        else:
            # Zapisujemy zdarzenia użytkownika (kliknięcia, nawigacja)
            with open(f"{session_path}/events.jsonl", "a") as f:
                f.write(json.dumps(data) + "\n")
                
        print(f" [x] Przetworzono event typu: {msg_type} dla sesji: {session_id}")

async def main():
    connection = await aio_pika.connect_robust("amqp://guest:guest@rabbitmq/")
    channel = await connection.channel()
    queue = await channel.declare_queue("ux_events", durable=True)
    
    await queue.consume(on_message)
    await asyncio.Future()  # Trzymaj proces uruchomiony

if __name__ == "__main__":
    asyncio.run(main())