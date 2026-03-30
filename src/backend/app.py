"""
app.py — Flask Backend
======================
Responsibilities:
  1. Serve the HTML chat page (index.html).
  2. Receive chat messages + optional image uploads from the browser.
  3. If an image is attached:
       a. Call the MCP server's classify_lesion tool via subprocess stdin/stdout.
       b. Inject the classification result into the Gemini prompt as context.
  4. Stream Gemini Flash's response back to the browser via Server-Sent Events (SSE).

HOW TO RUN:
  1. Install dependencies:  pip install -r requirements.txt
  2. Set your Gemini API key in the GEMINI_API_KEY variable below (or via env var).
  3. Run:  python app.py
  4. Open:  http://localhost:5000
"""

import os
import sys
import json
import base64
import subprocess
import threading
import time
# ── CHANGED BY CLAUDE (2026-03-30) ───────────────────────────────────────────
# ORIGINAL: no Firebase imports — app.py was fully stateless (images discarded,
#           no sessions saved, no persistence at all)
# ADDED:    Firebase Admin SDK + uuid + datetime to support image uploads to
#           Firebase Storage and session persistence in Firestore
# ─────────────────────────────────────────────────────────────────────────────
import uuid
import datetime
import firebase_admin
from firebase_admin import credentials, firestore, storage

from flask import Flask, render_template, request, Response, stream_with_context
from google import genai
from google.genai import types

# =============================================================================
# CONFIGURATION
# =============================================================================

# ── Gemini API key — set here or via environment variable ────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY_HERE")

# ── Gemini model to use ──────────────────────────────────────────────────────
GEMINI_MODEL = "gemini-2.5-flash"

# ── CHANGED BY CLAUDE (2026-03-30) ───────────────────────────────────────────
# ORIGINAL: no Firebase config — app.py had no persistence whatsoever
# ADDED:    Firebase credentials path + storage bucket, read from env vars
#           (same pattern already used in api.py)
#           Set before running:
#             export FIREBASE_CREDENTIALS_PATH="path/to/firebase_credentials.json"
#             export FIREBASE_STORAGE_BUCKET="your-project-id.firebasestorage.app"
# ─────────────────────────────────────────────────────────────────────────────
FIREBASE_CREDENTIALS_PATH = os.environ.get("FIREBASE_CREDENTIALS_PATH", "firebase_credentials.json")
FIREBASE_STORAGE_BUCKET   = os.environ.get("FIREBASE_STORAGE_BUCKET", "your-project-id.firebasestorage.app")

# ── System prompt: defines Gemini's persona and behavior ────────────────────
SYSTEM_PROMPT = """You are a helpful medical AI assistant specializing in dermatology.

When a skin lesion image is provided, you will receive a classification result from
a specialized PyTorch model. Use this result as a strong signal in your analysis,
but also consider the user's description and ask clarifying questions when needed.

IMPORTANT GUIDELINES:
- Always remind the user that AI analysis is NOT a substitute for a dermatologist.
- Be empathetic and clear — patients may be anxious about results.
- Explain medical terms in plain language.
- If the model flags malignancy, always recommend an in-person consultation urgently.
- Do not make definitive diagnoses — frame findings as observations and recommendations.
"""

# ── Path to the MCP server script ────────────────────────────────────────────
MCP_SERVER_PATH = os.path.join(os.path.dirname(__file__), "mcp_server.py")

# =============================================================================
# CHANGED BY CLAUDE (2026-03-30) — FIREBASE INITIALIZATION
# ORIGINAL: no Firebase init existed in app.py at all
# ADDED:    init_firebase() + get_db() + get_bucket() helpers, matching the
#           pattern already used in api.py, so both backends share the same
#           Firebase project
# =============================================================================

def init_firebase():
    """Initialize Firebase Admin SDK once at startup. Fails gracefully so the
    web UI still works even if Firebase credentials are not configured."""
    try:
        # Avoid re-initializing if already done (e.g. during Flask hot-reload)
        if not firebase_admin._apps:
            cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
            firebase_admin.initialize_app(cred, {"storageBucket": FIREBASE_STORAGE_BUCKET})
            print("[Firebase] Initialized successfully.")
        else:
            print("[Firebase] Already initialized — skipping.")
    except Exception as e:
        print(f"[Firebase] WARNING: Could not initialize — {e}")
        print("[Firebase] Running without Firebase (stateless mode).")

init_firebase()

def get_db():
    """Return Firestore client."""
    return firestore.client()

def get_bucket():
    """Return Firebase Storage bucket."""
    return storage.bucket()

# =============================================================================
# CHANGED BY CLAUDE (2026-03-30) — FIREBASE HELPER FUNCTIONS
# ORIGINAL: none — images were discarded after classification, nothing was saved
# ADDED:    three helpers for uploading images and saving/updating sessions,
#           identical in structure to the ones in api.py
# =============================================================================

def upload_image_to_storage(image_bytes: bytes, image_id: str, content_type: str = "image/jpeg") -> str:
    """Upload image bytes to Firebase Storage under lesions/<image_id>.jpg.
    Returns the public HTTPS URL."""
    bucket = get_bucket()
    blob   = bucket.blob(f"lesions/{image_id}.jpg")
    blob.upload_from_string(image_bytes, content_type=content_type)
    blob.make_public()
    return blob.public_url


def save_session_to_firestore(session_id: str, image_id: str | None,
                               classification: dict | None, messages: list) -> None:
    """Create or merge a session document in Firestore.

    Structure:
      sessions/{session_id}
        ├── created_at:     ISO timestamp
        ├── source:         "web"           ← marks origin as the web UI
        ├── image_id:       str | null
        ├── classification: {label, confidence, all_scores} | null
        └── messages:       [{role, text, timestamp}, ...]
    """
    db  = get_db()
    ref = db.collection("sessions").document(session_id)
    ref.set({
        "created_at":     datetime.datetime.utcnow().isoformat(),
        "source":         "web",
        "image_id":       image_id,
        "classification": classification,
        "messages":       messages,
    }, merge=True)


def append_message_to_firestore(session_id: str, role: str, text: str) -> None:
    """Append a single {role, text, timestamp} entry to an existing session."""
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
# FLASK APP SETUP
# =============================================================================

app = Flask(__name__)

# Configure Gemini client (new google.genai SDK)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# =============================================================================
# MCP CLIENT — communicates with mcp_server.py via subprocess stdio
# =============================================================================

class MCPClient:
    """
    Manages a persistent subprocess running mcp_server.py.
    Sends JSON-RPC requests via stdin, reads responses from stdout.
    Thread-safe via a lock.
    """

    def __init__(self, server_script: str):
        self.server_script = server_script
        self.process = None
        self.lock = threading.Lock()
        self._request_id = 0
        self._start()

    def _start(self):
        """Spawn the MCP server subprocess."""
        self.process = subprocess.Popen(
            [sys.executable, self.server_script],  # sys.executable = the running python (python3, venv, etc.)
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,          # MCP server logs to its own stderr
            text=True,
            bufsize=1,            # line-buffered
        )
        # Perform MCP handshake (initialize)
        self._call("initialize", {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "flask-client", "version": "1.0.0"},
            "capabilities": {},
        })

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _call(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request and block until the response arrives."""
        req_id  = self._next_id()
        payload = json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})

        with self.lock:
            # Write request to MCP server stdin
            self.process.stdin.write(payload + "\n")
            self.process.stdin.flush()

            # Read response from MCP server stdout
            line = self.process.stdout.readline()

        return json.loads(line)

    def classify_lesion(self, image_bytes: bytes) -> dict:
        """
        Call the MCP tool 'classify_lesion' with a raw image.
        Returns a dict: {label, confidence, all_scores}
        """
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        response  = self._call("tools/call", {
            "name": "classify_lesion",
            "arguments": {"image_base64": image_b64},
        })

        # Parse the text content returned by the MCP tool
        result_text = response["result"]["content"][0]["text"]
        return json.loads(result_text)


# Instantiate the MCP client once (reused across all requests)
mcp_client = MCPClient(MCP_SERVER_PATH)

# =============================================================================
# ROUTES
# =============================================================================

@app.route("/")
def index():
    """Serve the chat UI."""
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    """
    Endpoint called by the browser for each chat message.

    Expects multipart/form-data with:
      - message (str):          The user's text message.
      - history (str):          JSON array of prior turns [{role, text}, ...].
      - image (file, optional): A skin lesion image to classify.
      - session_id (str):       CHANGED BY CLAUDE (2026-03-30) — empty on first
                                message; the server assigns one and returns it in
                                the first SSE event so the frontend can reuse it
                                for follow-up messages in the same session.

    Returns a text/event-stream (SSE):
      - First event:  {"session_id": str, "image_url": str|null, "classification": dict|null}
      - Token events: {"token": str}
      - Final event:  [DONE]
    """
    user_message = request.form.get("message", "").strip()
    history_json  = request.form.get("history", "[]")
    history       = json.loads(history_json)
    image_file    = request.files.get("image")

    # ── CHANGED BY CLAUDE (2026-03-30) ───────────────────────────────────────
    # ORIGINAL: no session tracking — every request was independent
    # ADDED:    session_id received from frontend (empty = new session);
    #           server generates one if missing so all turns link to one document
    # ─────────────────────────────────────────────────────────────────────────
    session_id = request.form.get("session_id", "").strip() or str(uuid.uuid4())
    image_id   = str(uuid.uuid4())
    image_url  = None

    # ── Step 1: If image provided, upload to Firebase Storage ────────────────
    # CHANGED BY CLAUDE (2026-03-30) — ORIGINAL: image bytes were read and used
    # only for MCP classification, then discarded. ADDED: upload to Firebase
    # Storage first so the image is persisted before classification begins.
    image_bytes = None
    if image_file:
        image_bytes = image_file.read()
        try:
            image_url = upload_image_to_storage(image_bytes, image_id, image_file.content_type)
            print(f"[Storage] Uploaded image → {image_url}")
        except Exception as e:
            print(f"[Storage] Upload failed: {e}")

    # ── Step 2: If image provided, classify it via MCP ───────────────────────
    classification        = None
    classification_context = ""
    if image_bytes:
        try:
            classification = mcp_client.classify_lesion(image_bytes)
            classification_context = (
                f"\n\n[CLASSIFICATION MODEL RESULT]\n"
                f"Prediction: {classification['label']}\n"
                f"Confidence: {classification['confidence'] * 100:.1f}%\n"
                f"All class scores: {json.dumps(classification['all_scores'], indent=2)}\n"
                f"[END CLASSIFICATION RESULT]\n\n"
                f"Please incorporate the above classification result in your response."
            )
        except Exception as e:
            classification_context = f"\n\n[Classification failed: {e}]\n"

    # ── Step 3: Save initial session to Firestore ─────────────────────────────
    # CHANGED BY CLAUDE (2026-03-30) — ORIGINAL: nothing was saved
    # ADDED: persist the user message + metadata before streaming starts,
    #        so the session exists even if streaming fails mid-way
    try:
        save_session_to_firestore(
            session_id=session_id,
            image_id=image_id if image_bytes else None,
            classification=classification,
            messages=[{
                "role":      "user",
                "text":      user_message,
                "timestamp": datetime.datetime.utcnow().isoformat(),
            }],
        )
    except Exception as e:
        print(f"[Firestore] Save failed: {e}")

    # ── Step 4: Build Gemini conversation history ─────────────────────────────
    gemini_history = []
    for turn in history:
        role = "model" if turn["role"] == "assistant" else "user"
        gemini_history.append(
            types.Content(role=role, parts=[types.Part(text=turn["text"])])
        )

    full_user_message = user_message + classification_context

    # ── Step 5: Stream Gemini's response back to the browser via SSE ──────────
    def generate():
        """Generator that yields SSE-formatted chunks from Gemini."""
        # CHANGED BY CLAUDE (2026-03-30) — ORIGINAL: first event was a token
        # ADDED: first event is a meta payload so the frontend receives the
        #        session_id, image_url, and classification before tokens arrive
        meta = json.dumps({
            "session_id":     session_id,
            "image_url":      image_url,
            "classification": classification,
        })
        yield f"data: {meta}\n\n"

        full_response = ""
        try:
            contents = gemini_history + [
                types.Content(role="user", parts=[types.Part(text=full_user_message)])
            ]
            response = gemini_client.models.generate_content_stream(
                model=GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.7,
                ),
            )
            for chunk in response:
                if chunk.text:
                    full_response += chunk.text
                    data = json.dumps({"token": chunk.text})
                    yield f"data: {data}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            # CHANGED BY CLAUDE (2026-03-30) — ORIGINAL: nothing saved on finish
            # ADDED: append the completed assistant response to Firestore
            try:
                append_message_to_firestore(session_id, "assistant", full_response)
            except Exception:
                pass
            yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # debug=False in production; threaded=True supports concurrent SSE streams
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
