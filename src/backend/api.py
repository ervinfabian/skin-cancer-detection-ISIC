"""
api.py — FastAPI Mobile Backend
================================
Mobile-optimized backend for the DermAI Android app.

Endpoints:
  POST /analyze          — upload image → classify (MCP) → store (Firebase) → chat (Gemini)
  POST /chat             — continue a conversation (text only, no image)
  GET  /history/{session_id} — fetch past sessions from Firestore
  GET  /image/{image_id}     — get a Firebase Storage download URL for an image

Firebase setup:
  1. Create a Firebase project at https://console.firebase.google.com
  2. Enable Firestore and Storage
  3. Download your service account JSON → set FIREBASE_CREDENTIALS_PATH below
  4. Set your Storage bucket name in FIREBASE_STORAGE_BUCKET

HOW TO RUN:
  pip install -r requirements_mobile.txt
  uvicorn api:app --host 0.0.0.0 --port 8000 --reload
"""

import os
import sys
import json
import base64
import uuid
import subprocess
import threading
import datetime
from typing import AsyncGenerator

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, firestore, storage

# Gemini new SDK
from google import genai
from google.genai import types

# =============================================================================
# CONFIGURATION — edit these
# =============================================================================

GEMINI_API_KEY          = os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY_HERE")
GEMINI_MODEL            = "gemini-2.5-flash"

# Path to your Firebase service account JSON (download from Firebase Console)
FIREBASE_CREDENTIALS_PATH = os.environ.get("FIREBASE_CREDENTIALS_PATH", "firebase_credentials.json")

# Your Firebase Storage bucket (e.g. "your-project-id.appspot.com")
FIREBASE_STORAGE_BUCKET   = os.environ.get("FIREBASE_STORAGE_BUCKET", "your-project-id.appspot.com")

MCP_SERVER_PATH = os.path.join(os.path.dirname(__file__), "mcp_server.py")

SYSTEM_PROMPT = """You are DermAI, a helpful medical AI assistant specializing in dermatology.

When a skin lesion image is provided, you will receive a classification result from
a specialized PyTorch model. Use this result as a strong signal in your analysis.

IMPORTANT GUIDELINES:
- Always remind the user that AI analysis is NOT a substitute for a dermatologist.
- Be empathetic and clear — patients may be anxious about results.
- Explain medical terms in plain language.
- If the model flags malignancy with high confidence, recommend urgent in-person consultation.
- Do not make definitive diagnoses — frame findings as observations and recommendations.
- Keep responses concise and mobile-friendly (shorter paragraphs).
"""

# =============================================================================
# FIREBASE INITIALIZATION
# =============================================================================

def init_firebase():
    """Initialize Firebase Admin SDK. Called once at startup."""
    try:
        cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
        firebase_admin.initialize_app(cred, {"storageBucket": FIREBASE_STORAGE_BUCKET})
        print("[Firebase] Initialized successfully.")
    except Exception as e:
        print(f"[Firebase] WARNING: Could not initialize — {e}")
        print("[Firebase] Running without Firebase (local mode).")

init_firebase()

def get_db():
    """Return Firestore client."""
    return firestore.client()

def get_bucket():
    """Return Firebase Storage bucket."""
    return storage.bucket()

# =============================================================================
# MCP CLIENT (reused from web app — same stdio subprocess pattern)
# =============================================================================

class MCPClient:
    """Manages a persistent mcp_server.py subprocess via stdin/stdout."""

    def __init__(self, server_script: str):
        self.server_script = server_script
        self.process       = None
        self.lock          = threading.Lock()
        self._request_id   = 0
        self._start()

    def _start(self):
        self.process = subprocess.Popen(
            [sys.executable, self.server_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            bufsize=1,
        )
        # MCP handshake
        self._call("initialize", {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "fastapi-mobile-client", "version": "1.0.0"},
            "capabilities": {},
        })

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _call(self, method: str, params: dict) -> dict:
        req_id  = self._next_id()
        payload = json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        with self.lock:
            self.process.stdin.write(payload + "\n")
            self.process.stdin.flush()
            line = self.process.stdout.readline()
        return json.loads(line)

    def classify_lesion(self, image_bytes: bytes) -> dict:
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        response  = self._call("tools/call", {
            "name": "classify_lesion",
            "arguments": {"image_base64": image_b64},
        })
        result_text = response["result"]["content"][0]["text"]
        return json.loads(result_text)


mcp_client    = MCPClient(MCP_SERVER_PATH)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# =============================================================================
# FIREBASE HELPERS
# =============================================================================

def upload_image_to_storage(image_bytes: bytes, image_id: str, content_type: str = "image/jpeg") -> str:
    """
    Upload raw image bytes to Firebase Storage.
    Returns the gs:// path (use get_download_url to get an HTTPS link).
    """
    bucket = get_bucket()
    blob   = bucket.blob(f"lesions/{image_id}.jpg")
    blob.upload_from_string(image_bytes, content_type=content_type)
    # Make publicly readable (or use signed URLs for private access)
    blob.make_public()
    return blob.public_url


def save_session_to_firestore(session_id: str, image_id: str | None,
                               classification: dict | None, messages: list) -> None:
    """
    Save or update a chat session in Firestore.

    Firestore structure:
      sessions/{session_id}
        ├── created_at: timestamp
        ├── image_id:   str | null
        ├── classification: {label, confidence, all_scores} | null
        └── messages: [{role, text, timestamp}, ...]
    """
    db  = get_db()
    ref = db.collection("sessions").document(session_id)
    ref.set({
        "created_at":     datetime.datetime.utcnow().isoformat(),
        "image_id":       image_id,
        "classification": classification,
        "messages":       messages,
    }, merge=True)   # merge=True so subsequent /chat calls append without overwriting


def append_message_to_firestore(session_id: str, role: str, text: str) -> None:
    """Append a single message to an existing Firestore session."""
    db  = get_db()
    ref = db.collection("sessions").document(session_id)
    ref.update({
        "messages": firestore.ArrayUnion([{
            "role":      role,
            "text":      text,
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }])
    })

# =============================================================================
# FASTAPI APP
# =============================================================================

app = FastAPI(
    title="DermAI Mobile API",
    description="FastAPI backend for the DermAI Android app.",
    version="1.0.0",
)

# ── Request/Response models ───────────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str         # ties the conversation to a Firestore document
    message:    str
    history:    list[dict]  # [{role: "user"|"assistant", text: "..."}]


class SessionResponse(BaseModel):
    session_id:     str
    image_url:      str | None
    classification: dict | None
    messages:       list[dict]

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/analyze")
async def analyze(
    image:      UploadFile = File(...),
    message:    str        = Form(default="Please analyze this skin lesion."),
    session_id: str        = Form(default=""),
):
    """
    Main endpoint called by the Android app when the user sends an image.

    Steps:
      1. Read image bytes
      2. Upload to Firebase Storage
      3. Classify via MCP (PyTorch model)
      4. Save session skeleton to Firestore
      5. Stream Gemini response (SSE)

    Returns: text/event-stream  (SSE tokens)
    """
    # Generate IDs
    image_id   = str(uuid.uuid4())
    sid        = session_id or str(uuid.uuid4())
    image_bytes = await image.read()

    # ── 1. Upload image to Firebase Storage ──────────────────────────────────
    try:
        image_url = upload_image_to_storage(image_bytes, image_id, image.content_type)
    except Exception as e:
        image_url = None
        print(f"[Storage] Upload failed: {e}")

    # ── 2. Classify via MCP ──────────────────────────────────────────────────
    classification = None
    classification_context = ""
    try:
        classification = mcp_client.classify_lesion(image_bytes)
        classification_context = (
            f"\n\n[CLASSIFICATION MODEL RESULT]\n"
            f"Prediction: {classification['label']}\n"
            f"Confidence: {classification['confidence'] * 100:.1f}%\n"
            f"All scores: {json.dumps(classification['all_scores'])}\n"
            f"[END]\n\n"
            f"Please incorporate this classification in your response."
        )
    except Exception as e:
        classification_context = f"\n\n[Classification unavailable: {e}]\n"

    # ── 3. Save initial session to Firestore ─────────────────────────────────
    user_message_text = message + classification_context
    try:
        save_session_to_firestore(
            session_id=sid,
            image_id=image_id,
            classification=classification,
            messages=[{"role": "user", "text": message,
                       "timestamp": datetime.datetime.utcnow().isoformat()}],
        )
    except Exception as e:
        print(f"[Firestore] Save failed: {e}")

    # ── 4. Stream Gemini response ─────────────────────────────────────────────
    async def generate() -> AsyncGenerator[str, None]:
        full_response = ""
        # Send session_id and image_url as first SSE event so Android can store them
        meta = json.dumps({"session_id": sid, "image_url": image_url,
                           "classification": classification})
        yield f"data: {meta}\n\n"

        try:
            contents = [
                types.Content(role="user",
                              parts=[types.Part(text=user_message_text)])
            ]
            stream = gemini_client.models.generate_content_stream(
                model=GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.7,
                ),
            )
            for chunk in stream:
                if chunk.text:
                    full_response += chunk.text
                    yield f"data: {json.dumps({'token': chunk.text})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            # Save assistant response to Firestore
            try:
                append_message_to_firestore(sid, "assistant", full_response)
            except Exception:
                pass
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/chat")
async def chat(req: ChatRequest):
    """
    Continue a conversation without a new image.
    Called by the Android app for follow-up messages.
    Returns SSE stream.
    """
    # Build Gemini history from prior turns
    gemini_history = []
    for turn in req.history:
        role = "model" if turn["role"] == "assistant" else "user"
        gemini_history.append(
            types.Content(role=role, parts=[types.Part(text=turn["text"])])
        )

    # Save user message to Firestore
    try:
        append_message_to_firestore(req.session_id, "user", req.message)
    except Exception as e:
        print(f"[Firestore] Append failed: {e}")

    async def generate() -> AsyncGenerator[str, None]:
        full_response = ""
        try:
            contents = gemini_history + [
                types.Content(role="user", parts=[types.Part(text=req.message)])
            ]
            stream = gemini_client.models.generate_content_stream(
                model=GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.7,
                ),
            )
            for chunk in stream:
                if chunk.text:
                    full_response += chunk.text
                    yield f"data: {json.dumps({'token': chunk.text})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            try:
                append_message_to_firestore(req.session_id, "assistant", full_response)
            except Exception:
                pass
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/history/{session_id}", response_model=SessionResponse)
async def get_history(session_id: str):
    """
    Fetch a past session from Firestore.
    Called by the Android app to restore a conversation.
    """
    try:
        db  = get_db()
        doc = db.collection("sessions").document(session_id).get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail="Session not found")
        data = doc.to_dict()
        return SessionResponse(
            session_id=session_id,
            image_url=data.get("image_url"),
            classification=data.get("classification"),
            messages=data.get("messages", []),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions")
async def list_sessions(limit: int = 20):
    """
    List recent sessions (for history screen in Android app).
    Returns newest-first, limited to `limit` results.
    """
    try:
        db   = get_db()
        docs = (db.collection("sessions")
                  .order_by("created_at", direction=firestore.Query.DESCENDING)
                  .limit(limit)
                  .stream())
        return [{"session_id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    """Health check — used by Android app to verify server reachability."""
    return {"status": "ok", "model": GEMINI_MODEL}
