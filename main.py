import os
import json
import base64
import asyncio
import websockets
import requests

from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TELECMI_APP_ID = int(os.getenv("TELECMI_APP_ID"))
TELECMI_SECRET = os.getenv("TELECMI_SECRET")
TELECMI_FROM_NUMBER = os.getenv("TELECMI_FROM_NUMBER")
ELEVENLABS_AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID")

@app.get("/")
async def health():
    return {"message": "Server is running"}

@app.post("/make-outbound-call")
async def make_outbound_call(request: Request):
    body = await request.json()
    to = body.get("to")

    if not to:
        return JSONResponse(status_code=400, content={"error": "Missing 'to' number"})

    ws_url = "wss://tele2-2.onrender.com/ws"

    payload = {
        "appid": TELECMI_APP_ID,
        "secret": TELECMI_SECRET,
        "from": TELECMI_FROM_NUMBER,
        "to": to,
        "pcmo": [
            {
                "action": "stream",
                "ws_url": ws_url,
                "listen_mode": "callee"
            }
        ]
    }

    try:
        response = requests.post("https://rest.telecmi.com/v2/ind_pcmo_make_call", json=payload)
        response.raise_for_status()
        return {"message": "TeleCMI call initiated", "data": response.json()}
    except requests.RequestException as e:
        return JSONResponse(status_code=500, content={"error": f"Call initiation failed: {e}"})


@app.websocket("/ws")
async def media_stream(websocket: WebSocket):
    await websocket.accept()
    print("[TeleCMI] WebSocket connected.")

    try:
        elevenlabs_ws = await websockets.connect(
            f"wss://api.elevenlabs.io/v1/convai/conversation?agent_id={ELEVENLABS_AGENT_ID}"
        )
        print("[ElevenLabs] Connected.")

        async def from_elevenlabs():
            async for msg in elevenlabs_ws:
                message = json.loads(msg)
                if message.get("type") == "audio":
                    audio_base64 = message.get("audio_event", {}).get("audio_base_64")
                    if audio_base64:
                        await websocket.send_text(json.dumps({
                            "event": "media",
                            "media": {"payload": audio_base64}
                        }))
                elif message.get("type") == "interruption":
                    await websocket.send_text(json.dumps({"event": "clear"}))
                elif message.get("type") == "ping":
                    await elevenlabs_ws.send(json.dumps({
                        "type": "pong",
                        "event_id": message["ping_event"]["event_id"]
                    }))

        async def from_telecmi():
            async for msg in websocket.iter_text():
                print("[TeleCMI → WS] Message:", msg)
                try:
                    data = json.loads(msg)
                    event = data.get("event")
                    if event == "media":
                        chunk = data.get("media", {}).get("payload")
                        if chunk:
                            await elevenlabs_ws.send(json.dumps({
                                "user_audio_chunk": chunk
                            }))
                    elif event == "stop":
                        await elevenlabs_ws.close()
                except Exception as e:
                    print("Parsing error:", e)

        await asyncio.gather(from_telecmi(), from_elevenlabs())

    except Exception as e:
        print("[Error]", str(e))
        await websocket.close()
    finally:
        print("[TeleCMI] WebSocket closed.")