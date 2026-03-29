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
      - message (str):         The user's text message.
      - history (str):         JSON array of prior turns [{role, text}, ...].
      - image (file, optional): A skin lesion image to classify.

    Returns a text/event-stream (SSE) of Gemini's streamed response.
    """
    user_message = request.form.get("message", "").strip()
    history_json  = request.form.get("history", "[]")
    history       = json.loads(history_json)
    image_file    = request.files.get("image")

    # ── Step 1: If image provided, classify it via MCP ───────────────────────
    classification_context = ""
    if image_file:
        image_bytes = image_file.read()
        try:
            result = mcp_client.classify_lesion(image_bytes)
            # Build a context string that Gemini will receive alongside the user message
            classification_context = (
                f"\n\n[CLASSIFICATION MODEL RESULT]\n"
                f"Prediction: {result['label']}\n"
                f"Confidence: {result['confidence'] * 100:.1f}%\n"
                f"All class scores: {json.dumps(result['all_scores'], indent=2)}\n"
                f"[END CLASSIFICATION RESULT]\n\n"
                f"Please incorporate the above classification result in your response."
            )
        except Exception as e:
            classification_context = f"\n\n[Classification failed: {e}]\n"

    # ── Step 2: Build Gemini conversation history ─────────────────────────────
    # New SDK uses types.Content with types.Part
    gemini_history = []
    for turn in history:
        role = "model" if turn["role"] == "assistant" else "user"
        gemini_history.append(
            types.Content(role=role, parts=[types.Part(text=turn["text"])])
        )

    # ── Step 3: Compose the final user message (text + classification result) ─
    full_user_message = user_message + classification_context

    # ── Step 4: Stream Gemini's response back to the browser via SSE ──────────
    def generate():
        """Generator that yields SSE-formatted chunks from Gemini."""
        try:
            # generate_content_stream handles multi-turn via contents list
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
                # chunk.text is a convenience property on the new SDK
                if chunk.text:
                    data = json.dumps({"token": chunk.text})
                    yield f"data: {data}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            # Signal end of stream to the browser
            yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering if proxied
        },
    )


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # debug=False in production; threaded=True supports concurrent SSE streams
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
