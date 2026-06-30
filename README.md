# DermAI — Skin Lesion Analysis System

AI-powered skin lesion classification with a native Android app and web interface.

> **Disclaimer:** DermAI is not a substitute for professional medical diagnosis. Always consult a dermatologist for a definitive assessment.

---

## Architecture

```
Android App (Kotlin MVVM)
       │
       │ HTTP / SSE
       ▼
FastAPI Backend  (api.py)
       │
       ├─► Gemini 2.5 Flash — image validation + ABCDE analysis + chat
       ├─► MCP Server       — JSON-RPC 2.0 over stdio subprocess
       │       └─► Google Colab (Cloudflare tunnel) — ViT-Base classifier
       └─► Firebase
               ├─ Auth     — user authentication
               ├─ Storage  — lesion images (per-user isolation)
               └─ Firestore — analysis history + chat sessions

Web Browser
       │
       │ HTTP / SSE
       ▼
Flask Backend  (app.py)  — same pipeline, served as a web chat UI
```

---

## Project Structure

```
skin-cancer-detection-ISIC/
└── src/
    ├── backend/
    │   ├── api.py                  # FastAPI backend (Android)
    │   ├── app.py                  # Flask backend (web)
    │   ├── mcp_server.py           # MCP subprocess — bridges backend ↔ Colab
    │   ├── requirements.txt        # Flask dependencies
    │   ├── requirements_mobile.txt # FastAPI dependencies
    │   └── templates/
    │       └── index.html          # Web chat UI
    └── android/
        └── app/src/main/
            ├── java/com/dermai/app/
            │   ├── ui/
            │   │   ├── MainActivity.kt      # Chat screen
            │   │   ├── CameraActivity.kt    # Macro camera (CameraX)
            │   │   ├── ChatAdapter.kt       # RecyclerView adapter
            │   │   ├── ChatViewModel.kt     # State + LiveData
            │   │   └── HistoryActivity.kt   # Past sessions
            │   ├── api/ApiService.kt        # SSE streaming client
            │   └── model/                   # Data classes
            └── res/                         # Layouts, drawables, themes
```

---

## Setup

The backend loads its secrets and the model URL from a `src/backend/.env` file (via `python-dotenv`):

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | Google Gemini API key |
| `COLAB_MODEL_URL` | Cloudflare tunnel URL of the Colab `/classify` endpoint |
| `FIREBASE_STORAGE_BUCKET` | Firebase Storage bucket (e.g. `your-project-id.appspot.com`) |

### 1. Colab Model (ViT)

Open the training/inference notebook in Google Colab, run all cells, and expose the `/classify` endpoint via a Cloudflare tunnel. Use the tunnel URL as `COLAB_MODEL_URL`.

### 2. Firebase

1. Create a project at [Firebase Console](https://console.firebase.google.com)
2. Enable **Authentication**, **Firestore**, and **Storage**
3. Download the service account JSON → save as `src/backend/firebase_credentials.json`

### 3. Web Backend

```bash
cd src/backend
pip install -r requirements.txt
python app.py
# → http://localhost:5000
```

### 4. Mobile Backend

```bash
cd src/backend
pip install -r requirements_mobile.txt
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Android App

1. Open `src/android` in Android Studio
2. Set the backend IP in `app/build.gradle`:
   ```groovy
   buildConfigField "String", "API_BASE_URL", "\"http://<your-machine-ip>:8000\""
   ```
3. Add `google-services.json` (from Firebase Console) to `app/`
4. **Build → Rebuild Project**, then run on device

---

## Image Validation Codes

| Code | Meaning |
|---|---|
| `OK` | Proceeds to ViT classification |
| `NOT_SKIN` | Image does not show a skin lesion |
| `TOO_FAR` | Lesion too small / camera too distant |
| `MULTIPLE` | More than one lesion in frame |
| `BLURRY` | Out of focus or motion blur |
| `NOT_ASSESSABLE` | Other quality issue |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Android | Kotlin, CameraX, OkHttp, Glide, Firebase SDK |
| Mobile API | FastAPI, Uvicorn |
| Web API | Flask |
| AI | Google Gemini 2.5 Flash |
| ML model | ViT-Base (timm), ISIC 2024 |
| Model serving | Google Colab + Cloudflare tunnel |
| Persistence | Firebase Auth + Firestore + Storage |
| Streaming | Server-Sent Events (SSE) |
| Model protocol | MCP (JSON-RPC 2.0 over stdio) |

---

## Dataset

[ISIC 2024 — Skin Cancer Detection with 3D-TBP](https://www.kaggle.com/competitions/isic-2024-challenge/)
