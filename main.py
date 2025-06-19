import os
import json
import asyncio
import websockets
from fastapi import FastAPI, WebSocket
from fastapi.responses import PlainTextResponse
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

ELEVENLABS_AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID")


@app.get("/")
async def root():
    return PlainTextResponse("✅ ElevenLabs WebSocket server is ready.")


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("🔌 WebSocket client connected")

    try:
        async with websockets.connect(
            f"wss://api.elevenlabs.io/v1/convai/conversation?agent_id={ELEVENLABS_AGENT_ID}"
        ) as eleven_ws:
            print("🧠 Connected to ElevenLabs")

            # Start conversation — ElevenLabs agent handles the rest
            await eleven_ws.send(json.dumps({
                "text": "Hello! How can I help you today?",
                "start_conversation": True
            }))

            async def handle_from_eleven():
                async for msg in eleven_ws:
                    data = json.loads(msg)
                    if data.get("type") == "ping":
                        await eleven_ws.send(json.dumps({
                            "type": "pong",
                            "event_id": data["ping_event"]["event_id"]
                        }))
                    elif data.get("type") == "audio":
                        audio = data["audio_event"]["audio_base_64"]
                        await websocket.send_text(json.dumps({
                            "event": "media",
                            "media": {"payload": audio}
                        }))
                        print("🔊 Sent audio to client")
                    elif data.get("type") == "interruption":
                        await websocket.send_text(json.dumps({"event": "clear"}))

            async def handle_from_client():
                async for msg in websocket.iter_text():
                    print("📥 Client said:", msg)
                    data = json.loads(msg)
                    if data.get("event") == "media":
                        await eleven_ws.send(json.dumps({
                            "user_audio_chunk": data["media"]["payload"]
                        }))
                    elif data.get("event") == "stop":
                        await eleven_ws.close()

            await asyncio.gather(handle_from_client(), handle_from_eleven())

    except Exception as e:
        print("❌ WebSocket error:", e)
        await websocket.send_text(f"❌ Error: {str(e)}")

    finally:
        await websocket.close()
        print("🔴 WebSocket closed")


if _name_ == "_main_":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8500, reload=True)