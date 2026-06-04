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
import time  # already imported — used for MCP retry backoff
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

from dotenv import load_dotenv
load_dotenv()  # loads .env from the current directory (or any parent)

from functools import wraps
from flask import Flask, g, render_template, request, Response, stream_with_context
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

def upload_image_to_storage(image_bytes: bytes, image_id: str, uid: str, content_type: str = "image/jpeg") -> str:
    """Upload image bytes to Firebase Storage under users/<uid>/lesions/<image_id>.jpg.
    Returns the public HTTPS URL."""
    bucket = get_bucket()
    blob   = bucket.blob(f"users/{uid}/lesions/{image_id}.jpg")
    blob.upload_from_string(image_bytes, content_type=content_type)
    blob.make_public()
    return blob.public_url


def save_session_to_firestore(session_id: str, image_id: str | None,
                               classification: dict | None, messages: list,
                               uid: str = "") -> None:
    """Create or merge a session document in Firestore.

    Structure:
      sessions/{session_id}
        ├── user_id:        Firebase UID of the owner
        ├── created_at:     ISO timestamp
        ├── source:         "web"           ← marks origin as the web UI
        ├── image_id:       str | null
        ├── classification: {label, confidence, all_scores} | null
        └── messages:       [{role, text, timestamp}, ...]
    """
    db  = get_db()
    ref = db.collection("sessions").document(session_id)
    ref.set({
        "user_id":        uid,
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

# ── Firebase Auth token verification ─────────────────────────────────────────

def require_auth(f):
    """Decorator that verifies the Firebase ID token in the Authorization header."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token:
            return {"error": "Unauthorized"}, 401
        try:
            decoded = firebase_admin.auth.verify_id_token(token)
            g.uid = decoded.get("uid", "")
        except Exception:
            return {"error": "Invalid or expired token"}, 401
        return f(*args, **kwargs)
    return decorated

# Configure Gemini client (new google.genai SDK)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# =============================================================================
# MCP CLIENT — communicates with mcp_server.py via subprocess stdio
# =============================================================================

class MCPClient:
    """
    Manages a persistent subprocess running mcp_server.py.
    Sends JSON-RPC requests via stdin, reads responses from stdout.
    Thread-safe via a lock. Restarts the subprocess automatically on failure.
    """

    def __init__(self, server_script: str):
        self.server_script = server_script
        self.process = None
        self.lock = threading.Lock()
        self._request_id = 0
        self._current_url = os.environ.get("COLAB_MODEL_URL", "")
        self._start()

    def _start(self):
        """Spawn the MCP server subprocess, forwarding the current model URL."""
        env = os.environ.copy()
        if self._current_url:
            env["COLAB_MODEL_URL"] = self._current_url
        self.process = subprocess.Popen(
            [sys.executable, self.server_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            bufsize=1,
            env=env,
        )
        self._raw_call("initialize", {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "flask-client", "version": "1.0.0"},
            "capabilities": {},
        })

    def _restart(self):
        try:
            self.process.kill()
            self.process.wait(timeout=5)
        except Exception:
            pass
        self._start()

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _raw_call(self, method: str, params: dict) -> dict:
        """Single call attempt — no retry."""
        req_id  = self._next_id()
        payload = json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        with self.lock:
            self.process.stdin.write(payload + "\n")
            self.process.stdin.flush()
            line = self.process.stdout.readline()
        return json.loads(line)

    def _call(self, method: str, params: dict) -> dict:
        """Call with up to 3 attempts, restarting the subprocess on failure."""
        last_exc = None
        for attempt in range(3):
            try:
                return self._raw_call(method, params)
            except Exception as e:
                last_exc = e
                print(f"[MCP] Attempt {attempt + 1}/3 failed: {e}")
                if attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
                    self._restart()
        raise RuntimeError(f"MCP call failed after 3 attempts: {last_exc}")

    def classify_lesion(self, image_bytes: bytes) -> dict:
        """Call the classify_lesion MCP tool. Returns {label, confidence, all_scores}."""
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        response  = self._call("tools/call", {
            "name": "classify_lesion",
            "arguments": {"image_base64": image_b64},
        })
        result_text = response["result"]["content"][0]["text"]
        return json.loads(result_text)

    def update_model_url(self, url: str) -> None:
        """Update the Colab ViT endpoint at runtime — no server restart needed."""
        self._current_url = url.rstrip("/")
        self._raw_call("update_model_url", {"url": self._current_url})


# Instantiate the MCP client once (reused across all requests)
mcp_client = MCPClient(MCP_SERVER_PATH)

# =============================================================================
# ROUTES
# =============================================================================

@app.route("/")
def index():
    """Serve the chat UI — passes Firebase web config for client-side auth."""
    import json as _json
    firebase_config = _json.dumps({
        "apiKey":             os.environ.get("FIREBASE_WEB_API_KEY", ""),
        "authDomain":         os.environ.get("FIREBASE_AUTH_DOMAIN", ""),
        "projectId":          os.environ.get("FIREBASE_PROJECT_ID", ""),
        "storageBucket":      FIREBASE_STORAGE_BUCKET,
        "messagingSenderId":  os.environ.get("FIREBASE_MESSAGING_SENDER_ID", ""),
        "appId":              os.environ.get("FIREBASE_APP_ID", ""),
        "measurementId":      os.environ.get("FIREBASE_MEASUREMENT_ID", ""),
    })
    return render_template("index.html", firebase_config=firebase_config)


@app.route("/chat", methods=["POST"])
@require_auth
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
    REJECTION_MESSAGES = {
        "NOT_SKIN":       ("The uploaded image doesn't appear to show a skin lesion or dermatological finding. "
                           "Please upload a close-up photo of the specific skin area you'd like analyzed — "
                           "such as a mole, rash, or other skin change."),
        "TOO_FAR":        ("The lesion appears too far away to analyze accurately. "
                           "Please hold the camera 5–10 cm from the skin and retake the photo so the lesion fills most of the frame."),
        "MULTIPLE":       ("The image contains multiple lesions. "
                           "Please upload a separate photo focusing on a single lesion at a time for accurate analysis."),
        "BLURRY":         ("The image is too blurry or out of focus for reliable analysis. "
                           "Please retake the photo — use macro mode and keep the camera steady."),
        "NOT_ASSESSABLE": ("The image quality is insufficient for analysis (e.g. poor lighting, obstruction, or motion blur). "
                           "Please retake the photo in good lighting, close up, and in focus."),
    }

    image_bytes = None
    if image_file:
        image_bytes = image_file.read()

        # ── Step 0: Validate image before upload/classify ────────────────────
        validation_code = "OK"
        try:
            validation = gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Content(role="user", parts=[
                        types.Part.from_bytes(data=image_bytes, mime_type=image_file.content_type or "image/jpeg"),
                        types.Part(text=(
                            "Evaluate this image for skin lesion analysis. Reply with exactly one of these codes:\n"
                            "OK — image shows a single, close-up, in-focus skin lesion suitable for analysis\n"
                            "NOT_SKIN — image does not show a skin lesion or dermatological finding\n"
                            "TOO_FAR — the lesion is visible but too small/distant to assess\n"
                            "MULTIPLE — image shows more than one distinct lesion\n"
                            "BLURRY — image is out of focus or motion-blurred\n"
                            "NOT_ASSESSABLE — other quality issue (poor lighting, obstruction, etc.)\n"
                            "Reply with the code only, nothing else."
                        )),
                    ])
                ],
            )
            validation_code = (validation.text or "").strip().upper()
            print(f"[Validation] Result: {validation_code}")
        except Exception as e:
            print(f"[Validation] Check failed, proceeding anyway: {e}")

        if validation_code not in ("OK", ""):
            rejection_msg = REJECTION_MESSAGES.get(validation_code, REJECTION_MESSAGES["NOT_ASSESSABLE"])
            def reject():
                meta = json.dumps({"session_id": session_id, "image_url": None, "classification": None})
                yield f"data: {meta}\n\n"
                yield f"data: {json.dumps({'token': rejection_msg})}\n\n"
                yield "data: [DONE]\n\n"
            return Response(reject(), mimetype="text/event-stream",
                            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        try:
            image_url = upload_image_to_storage(image_bytes, image_id, g.uid, image_file.content_type)
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
            uid=g.uid,
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

@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/model-url", methods=["POST"])
def update_model_url():
    """Update the Colab ViT model URL without restarting the server."""
    data = request.get_json() or {}
    url  = data.get("url", "").strip()
    if not url:
        return {"error": "url required"}, 400
    mcp_client.update_model_url(url)
    return {"status": "updated", "url": url}


if __name__ == "__main__":
    # debug=False in production; threaded=True supports concurrent SSE streams
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
