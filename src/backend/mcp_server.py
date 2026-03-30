"""
mcp_server.py — MCP Server for Skin Lesion Classification
==========================================================
This process is launched as a subprocess by Flask (app.py) and api.py.
It communicates via stdin/stdout using the MCP protocol (JSON-RPC 2.0).

The MCP server exposes one tool:
  classify_lesion(image_base64: str) -> dict
    Forwards the image to your Google Colab-hosted ViT model endpoint
    (exposed via a Cloudflare tunnel) and returns the result.

ARCHITECTURE:
  Flask/FastAPI → MCP server (this file) → HTTP → Colab (Cloudflare URL)
                                                        ↓
                                              ViT model on GPU
                                                        ↓
                                         {label, confidence, all_scores}

HOW TO UPDATE THE URL AFTER EACH COLAB RESTART:
  Option A (recommended): set the environment variable before starting Flask:
      export COLAB_MODEL_URL="https://xxxx-xxxx.trycloudflare.com"
      python app.py

  Option B: edit COLAB_MODEL_URL_FALLBACK below directly.

The /classify endpoint on Colab expects:
  POST /classify
  Content-Type: application/json
  Body: {"image_base64": "<base64 string>"}

And returns:
  {"label": "Benign"|"Malignant", "confidence": float, "all_scores": {...}}
"""

import sys
import os
import json
import logging
import urllib.request
import urllib.error
# ── CHANGED BY CLAUDE (2026-03-30) ───────────────────────────────────────────
# ORIGINAL: no ssl/certifi imports
# ADDED: ssl + certifi to fix SSL: CERTIFICATE_VERIFY_FAILED on macOS when
#        connecting to Cloudflare tunnel HTTPS URLs. Python (python.org install)
#        ships without system root certs, so HTTPS verification fails.
#        Requires: pip install certifi
# ─────────────────────────────────────────────────────────────────────────────
import ssl
import certifi

# ── Logging (to stderr so it doesn't pollute the MCP stdio channel) ──────────
logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="[MCP] %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# The Cloudflare tunnel URL printed by your Colab cell.
# Set via environment variable so you don't have to edit this file each restart:
#   export COLAB_MODEL_URL="https://xxxx-xxxx.trycloudflare.com"
#
# The fallback below is used if the env var is not set.
COLAB_MODEL_URL_FALLBACK = "https://YOUR-TUNNEL-URL.trycloudflare.com"

COLAB_MODEL_URL = os.environ.get("COLAB_MODEL_URL", COLAB_MODEL_URL_FALLBACK).rstrip("/")

# Full endpoint path — matches @app.route('/classify') in your Colab notebook
CLASSIFY_ENDPOINT = f"{COLAB_MODEL_URL}/classify"

# Timeout in seconds — Colab GPU inference can take 2-5s on cold start
REQUEST_TIMEOUT = 30

log.info(f"Colab model endpoint: {CLASSIFY_ENDPOINT}")

# =============================================================================
# TOOL IMPLEMENTATION
# =============================================================================

def classify_lesion(image_base64: str) -> dict:
    """
    Forward a base64-encoded image to the Colab-hosted ViT model.

    The Colab /classify endpoint accepts:
      POST /classify
      {"image_base64": "<base64 string>"}

    And returns:
      {"label": str, "confidence": float, "all_scores": {str: float}}

    Args:
        image_base64: Base64-encoded image string (no data URI prefix).

    Returns:
        {"label": str, "confidence": float, "all_scores": dict}

    Raises:
        RuntimeError: if the Colab endpoint is unreachable or returns an error.
    """
    # Build the JSON payload — matches what your Colab Flask app expects
    payload = json.dumps({"image_base64": image_base64}).encode("utf-8")

    # ── CHANGED BY CLAUDE (2026-03-30) ───────────────────────────────────────
    # ORIGINAL headers had only "Content-Type": "application/json"
    # PROBLEM: Cloudflare's free tunnel (trycloudflare.com) runs a Browser
    #          Integrity Check and blocks requests with no User-Agent, returning
    #          an HTML challenge page instead of forwarding to Flask. The MCP
    #          server then crashes trying to parse that HTML as JSON.
    # FIX:     Added a browser-like User-Agent so Cloudflare lets the request
    #          through to the Colab Flask server.
    # ─────────────────────────────────────────────────────────────────────────
    req = urllib.request.Request(
        url=CLASSIFY_ENDPOINT,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; DermAI-MCP/1.0)",
        },
        method="POST",
    )

    # ── CHANGED BY CLAUDE (2026-03-30) ───────────────────────────────────────
    # ORIGINAL: urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
    # PROBLEM:  SSL: CERTIFICATE_VERIFY_FAILED — Python on macOS can't verify
    #           Cloudflare's HTTPS cert because system root certs are missing.
    # FIX:      Pass a certifi-backed SSL context so Python uses the correct
    #           certificate bundle regardless of the OS/Python install method.
    # ─────────────────────────────────────────────────────────────────────────
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=ssl_ctx) as response:
            raw = response.read().decode("utf-8")
            result = json.loads(raw)

        # Validate expected fields are present
        if "label" not in result or "confidence" not in result:
            raise RuntimeError(f"Unexpected response format from Colab: {raw}")

        log.info(f"Classification result: {result['label']} ({result['confidence']:.2%})")
        return {
            "label":      result["label"],
            "confidence": round(float(result["confidence"]), 4),
            "all_scores": {k: round(float(v), 4) for k, v in result.get("all_scores", {}).items()},
        }

    except urllib.error.URLError as e:
        # Colab is offline or URL has changed after restart
        raise RuntimeError(
            f"Cannot reach Colab model at {CLASSIFY_ENDPOINT}. "
            f"Did the Cloudflare URL change? Update COLAB_MODEL_URL env var. "
            f"Error: {e}"
        )
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Colab returned non-JSON response: {e}")

# =============================================================================
# MCP PROTOCOL — JSON-RPC 2.0 over stdio
# =============================================================================

def send(obj: dict):
    """Write a JSON-RPC message to stdout (the MCP channel)."""
    line = json.dumps(obj)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def handle(request: dict):
    """Dispatch an incoming JSON-RPC request and return a response dict."""
    req_id  = request.get("id")
    method  = request.get("method", "")
    params  = request.get("params", {})

    # ── MCP handshake: initialize ────────────────────────────────────────────
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "skin-lesion-mcp", "version": "1.0.0"},
                "capabilities": {"tools": {}},
            }
        }

    # ── Tool discovery: list available tools ─────────────────────────────────
    if method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "tools": [{
                    "name": "classify_lesion",
                    "description": (
                        "Classify a skin lesion image as Benign or Malignant "
                        "using a ViT model hosted on Google Colab. "
                        "Call this whenever the user uploads a skin lesion image."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "image_base64": {
                                "type": "string",
                                "description": "Base64-encoded image of the skin lesion."
                            }
                        },
                        "required": ["image_base64"]
                    }
                }]
            }
        }

    # ── Tool execution: call classify_lesion ─────────────────────────────────
    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name == "classify_lesion":
            try:
                result = classify_lesion(arguments["image_base64"])
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {
                        "content": [{
                            "type": "text",
                            "text": json.dumps(result)
                        }]
                    }
                }
            except Exception as e:
                log.error(f"classify_lesion failed: {e}")
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32000, "message": str(e)}
                }

    # ── Unknown method ────────────────────────────────────────────────────────
    return {
        "jsonrpc": "2.0", "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    }


def main():
    """
    Main loop: read JSON-RPC lines from stdin, respond to stdout.
    Flask (app.py) and FastAPI (api.py) start this process via subprocess.
    """
    log.info("MCP server started — waiting for requests on stdin.")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request  = json.loads(line)
            response = handle(request)
            send(response)
        except json.JSONDecodeError as e:
            log.error(f"Bad JSON received: {e}")
            send({"jsonrpc": "2.0", "id": None,
                  "error": {"code": -32700, "message": "Parse error"}})


if __name__ == "__main__":
    main()
