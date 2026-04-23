# DermAI — Skin Lesion Analysis System

An AI-powered skin lesion analysis application built on the [ISIC 2024 Challenge](https://www.kaggle.com/competitions/isic-2024-challenge/) dataset. Users can photograph a skin lesion and receive an AI-assisted malignancy assessment, helping them decide whether to seek a dermatologist consultation.

> **Disclaimer:** DermAI is not a substitute for professional medical diagnosis. Always consult a dermatologist for a definitive assessment.

---

## Architecture

```
Android App (Kotlin)
       │
       │ HTTP / SSE
       ▼
FastAPI Backend (api.py)
       │
       ├─► Gemini Flash API  — image validation + conversational AI
       ├─► MCP Server        — forwards image to the ViT model
       │       └─► Google Colab (Cloudflare tunnel) — ViT classifier
       └─► Firebase
               ├─ Storage   — lesion images
               └─ Firestore — session / chat history

Web Browser
       │
       │ HTTP / SSE
       ▼
Flask Backend (app.py)  — same pipeline, served as a web chat UI
```

---

## Features

- **Image validation** — Gemini checks the photo before classification: rejects non-lesion images, blurry shots, images taken from too far, and multi-lesion photos with a specific error message for each case
- **ViT classification** — Vision Transformer model trained on ISIC 2024 data, returns `Benign` / `Malignant` with a confidence score
- **Conversational AI** — Gemini Flash explains the result, provides ABCDE observations, and answers follow-up questions
- **Session persistence** — chat history and images saved to Firebase (Firestore + Storage)
- **Android app** — native Kotlin client with in-app macro camera (CameraX), gallery picker, and real-time streaming chat
- **Web client** — Flask-served chat UI for desktop use

---

## Project Structure

```
src/
├── backend/
│   ├── api.py                  # FastAPI backend (Android)
│   ├── app.py                  # Flask backend (web)
│   ├── mcp_server.py           # MCP subprocess — bridges backend ↔ Colab model
│   ├── requirements.txt        # Flask dependencies
│   ├── requirements_mobile.txt # FastAPI dependencies
│   └── templates/
│       └── index.html          # Web chat UI
└── android/
    └── app/src/main/
        ├── java/com/dermai/app/
        │   ├── ui/
        │   │   ├── MainActivity.kt      # Chat screen
        │   │   ├── CameraActivity.kt    # In-app macro camera (CameraX)
        │   │   ├── ChatAdapter.kt       # RecyclerView adapter
        │   │   ├── ChatViewModel.kt     # State management
        │   │   └── HistoryActivity.kt   # Past sessions
        │   ├── api/ApiService.kt        # SSE streaming client
        │   └── model/                   # Data classes
        └── res/                         # Layouts, drawables, themes
```

---

## Setup

### 1. Colab Model (ViT)

Open the training/inference notebook in Google Colab, run all cells, and expose the `/classify` endpoint via a Cloudflare tunnel. Copy the tunnel URL.

```bash
export COLAB_MODEL_URL="https://xxxx-xxxx.trycloudflare.com"
```

### 2. Firebase

1. Create a project at [Firebase Console](https://console.firebase.google.com)
2. Enable **Firestore** and **Storage**
3. Download the service account JSON → save as `src/backend/firebase_credentials.json`
4. Set your Storage bucket name:
```bash
export FIREBASE_STORAGE_BUCKET="your-project-id.appspot.com"
```

### 3. Gemini API Key

```bash
export GEMINI_API_KEY="your-api-key"
```

### 4. Web Backend

```bash
cd src/backend
pip install -r requirements.txt
python app.py
# → http://localhost:5000
```

### 5. Mobile Backend

```bash
cd src/backend
pip install -r requirements_mobile.txt
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

### 6. Android App

1. Open `src/android` in Android Studio
2. Set the backend IP in `app/build.gradle`:
   ```groovy
   buildConfigField "String", "API_BASE_URL", "\"http://<your-machine-ip>:8000\""
   ```
3. Add `google-services.json` (from Firebase Console) to `app/`
4. **Build → Rebuild Project**, then run on device

---

## Image Validation

Before classification, Gemini evaluates every uploaded image and returns one of:

| Result | Meaning |
|--------|---------|
| `OK` | Proceeds to ViT classification |
| `NOT_SKIN` | Image does not show a skin lesion |
| `TOO_FAR` | Lesion too small / distant |
| `MULTIPLE` | More than one lesion in frame |
| `BLURRY` | Out of focus or motion blur |
| `NOT_ASSESSABLE` | Other quality issue |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Android | Kotlin, CameraX, OkHttp, Glide, Firebase SDK |
| Mobile API | FastAPI, Uvicorn |
| Web API | Flask |
| AI | Google Gemini Flash (`gemini-2.5-flash`) |
| ML Model | Vision Transformer (ViT), ISIC 2024 dataset |
| Model serving | Google Colab + Cloudflare tunnel |
| Persistence | Firebase Firestore + Storage |
| Protocol | MCP (JSON-RPC 2.0 over stdio) |

---

## Dataset

[ISIC 2024 — Skin Cancer Detection with 3D-TBP](https://www.kaggle.com/competitions/isic-2024-challenge/)

Reference solution: [ISIC-Research/ISIC-2024-Challenge-Sample-Solution](https://github.com/ISIC-Research/ISIC-2024-Challenge-Sample-Solution)
