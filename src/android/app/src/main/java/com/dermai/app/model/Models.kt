// model/Models.kt
// ================
// Data classes used throughout the app.
// Kept in one file for simplicity — split as the app grows.

package com.dermai.app.model

import com.google.gson.annotations.SerializedName

// ── Chat message (shown in RecyclerView) ─────────────────────────────────────

enum class MessageRole { USER, ASSISTANT }

data class ChatMessage(
    val role:      MessageRole,
    var text:      String,          // var — assistant messages grow during streaming
    val imageUri:  String? = null,  // local URI of attached image (user messages only)
    val timestamp: Long = System.currentTimeMillis(),
)

// ── Classification result from MCP/PyTorch ───────────────────────────────────

data class Classification(
    val label:      String,
    val confidence: Float,
    @SerializedName("all_scores")
    val allScores:  Map<String, Float>,
)

// ── SSE event types received from FastAPI ────────────────────────────────────

// First SSE event from /analyze — contains session metadata
data class AnalyzeMetaEvent(
    @SerializedName("session_id")
    val sessionId:      String,
    @SerializedName("image_url")
    val imageUrl:       String?,
    val classification: Classification?,
)

// Subsequent SSE events — streamed tokens
data class TokenEvent(val token: String?)
data class ErrorEvent(val error: String?)

// ── Session (Firestore document) ──────────────────────────────────────────────

data class Session(
    @SerializedName("session_id")
    val sessionId:      String,
    @SerializedName("image_url")
    val imageUrl:       String?,
    val classification: Classification?,
    val messages:       List<Map<String, String>>,
    @SerializedName("created_at")
    val createdAt:      String?,
)

// ── API request bodies ────────────────────────────────────────────────────────

data class ChatRequest(
    @SerializedName("session_id")
    val sessionId: String,
    val message:   String,
    val history:   List<Map<String, String>>,   // [{role, text}]
)
