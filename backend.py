import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, List
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from collections import Counter

# --- KONFIGURACJA ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = "recorded_sessions"
os.makedirs(BASE_DIR, exist_ok=True)

# --- MODELE DANYCH ---
class TrackingEvent(BaseModel):
    session_id: str
    timestamp: str
    type: str
    url: str
    details: Dict[str, Any]

class RecordingChunk(BaseModel):
    session_id: str
    events: List[Dict[str, Any]] # To są eventy z rrweb (DOM recording)

# --- LOGIKA ZAPISU ---
def append_to_jsonl(path: str, data: dict):
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(data) + "\n")

def save_recording_chunk(chunk: RecordingChunk):
    """Zapisuje fragmenty nagrania sesji (rrweb)"""
    session_dir = f"{BASE_DIR}/{chunk.session_id}"
    os.makedirs(session_dir, exist_ok=True)
    # Zapisujemy jako jsonl, żeby łatwo doklejać nowe fragmenty
    append_to_jsonl(f"{session_dir}/recording.jsonl", {"chunk": chunk.events})

@app.post("/api/track")
async def track_event(event: TrackingEvent, background_tasks: BackgroundTasks):
    session_dir = f"{BASE_DIR}/{event.session_id}"
    os.makedirs(session_dir, exist_ok=True)
    background_tasks.add_task(append_to_jsonl, f"{session_dir}/events.jsonl", event.dict())
    return {"status": "ok"}

@app.post("/api/record")
async def track_recording(chunk: RecordingChunk, background_tasks: BackgroundTasks):
    background_tasks.add_task(save_recording_chunk, chunk)
    return {"status": "ok"}

# --- NOWOŚĆ: ANALITYKA I METRYKI ---

def calculate_session_metrics(session_id: str):
    session_dir = f"{BASE_DIR}/{session_id}"
    events_path = f"{session_dir}/events.jsonl"
    
    if not os.path.exists(events_path):
        raise FileNotFoundError("Session not found")

    events = []
    with open(events_path, 'r', encoding='utf-8') as f:
        for line in f:
            events.append(json.loads(line))

    if not events:
        return {}

    # 1. Czas trwania sesji
    start_time = datetime.fromisoformat(events[0]['timestamp'].replace('Z', ''))
    end_time = datetime.fromisoformat(events[-1]['timestamp'].replace('Z', ''))
    duration_seconds = (end_time - start_time).total_seconds()

    # 2. Liczniki akcji
    clicks = [e for e in events if e['type'] == 'click']
    click_count = len(clicks)
    
    # 3. Rage Clicks (Szybkie kliknięcia w to samo miejsce)
    rage_clicks = 0
    for i in range(1, len(clicks)):
        t1 = datetime.fromisoformat(clicks[i-1]['timestamp'].replace('Z', ''))
        t2 = datetime.fromisoformat(clicks[i]['timestamp'].replace('Z', ''))
        # Jeśli kliknięto ponownie w ciągu 300ms w ten sam element (po ID lub tagu)
        if (t2 - t1).total_seconds() < 0.3 and clicks[i]['details'].get('path') == clicks[i-1]['details'].get('path'):
            rage_clicks += 1

    # 4. Eye Tracking Metrics (Heatmapa danych)
    gaze_events = [e for e in events if e['type'] == 'gaze_fixation']
    
    # Suma czasu spędzonego na każdym elemencie
    element_attention = {}
    total_fixation_time = 0
    
    for g in gaze_events:
        el_id = g['details'].get('element', 'unknown')
        duration = g['details'].get('duration_ms', 0)
        
        element_attention[el_id] = element_attention.get(el_id, 0) + duration
        total_fixation_time += duration

    # Sortowanie elementów wg czasu skupienia wzroku
    top_elements = sorted(element_attention.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "session_id": session_id,
        "duration_sec": round(duration_seconds, 2),
        "total_clicks": click_count,
        "rage_clicks": rage_clicks,
        "interaction_velocity": round(click_count / duration_seconds * 60, 2) if duration_seconds > 0 else 0, # Kliki na minutę
        "eye_tracking": {
            "total_fixation_time_ms": total_fixation_time,
            "top_focused_elements": [
                {"element": k, "time_ms": v, "percentage": round((v/total_fixation_time)*100, 1) if total_fixation_time > 0 else 0}
                for k, v in top_elements
            ]
        }
    }

@app.get("/api/session/{session_id}/metrics")
async def get_metrics(session_id: str):
    try:
        return calculate_session_metrics(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Error calculating metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)