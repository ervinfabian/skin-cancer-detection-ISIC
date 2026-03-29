// api/ApiService.kt
// ==================
// Handles all network communication with the FastAPI backend.
//
// Two patterns used:
//   1. OkHttp raw streaming — for SSE endpoints (/analyze, /chat)
//      SSE (Server-Sent Events) delivers tokens one-by-one as they arrive from Gemini.
//   2. Retrofit — for simple REST calls (/history, /sessions, /health)

package com.dermai.app.api

import android.util.Log
import com.dermai.app.BuildConfig
import com.dermai.app.model.*
import com.google.gson.Gson
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.asRequestBody
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.GET
import retrofit2.http.Path
import retrofit2.http.Query
import java.io.File
import java.util.concurrent.TimeUnit

// ── Retrofit interface (REST endpoints only) ──────────────────────────────────

interface DermApiRest {
    @GET("history/{session_id}")
    suspend fun getSession(@Path("session_id") sessionId: String): Session

    @GET("sessions")
    suspend fun listSessions(@Query("limit") limit: Int = 20): List<Session>

    @GET("health")
    suspend fun health(): Map<String, String>
}

// ── Sealed result type for SSE stream events ──────────────────────────────────

sealed class StreamEvent {
    data class Meta(val data: AnalyzeMetaEvent) : StreamEvent()   // first event from /analyze
    data class Token(val text: String)          : StreamEvent()   // streamed Gemini token
    data class Error(val message: String)       : StreamEvent()   // error from server
    object Done                                 : StreamEvent()   // stream finished
}

// ── Main API service class ────────────────────────────────────────────────────

class ApiService {

    companion object {
        private const val TAG = "ApiService"

        // Singleton instance
        val instance: ApiService by lazy { ApiService() }
    }

    private val gson = Gson()

    // OkHttp client with long read timeout (SSE streams can be slow)
    private val okHttpClient = OkHttpClient.Builder()
        .readTimeout(120, TimeUnit.SECONDS)
        .connectTimeout(15, TimeUnit.SECONDS)
        .build()

    // Retrofit client for non-streaming REST calls
    private val retrofit = Retrofit.Builder()
        .baseUrl(BuildConfig.API_BASE_URL + "/")
        .client(okHttpClient)
        .addConverterFactory(GsonConverterFactory.create())
        .build()

    val restApi: DermApiRest = retrofit.create(DermApiRest::class.java)

    // ── /analyze — image upload + SSE stream ─────────────────────────────────

    /**
     * Upload an image to the FastAPI /analyze endpoint and stream back events.
     *
     * Emits:
     *   StreamEvent.Meta   — first event (session_id, image_url, classification)
     *   StreamEvent.Token  — each Gemini token as it arrives
     *   StreamEvent.Error  — if something goes wrong
     *   StreamEvent.Done   — when stream ends
     *
     * Usage (in ViewModel):
     *   apiService.analyzeImage(imageFile, "Please analyze this lesion")
     *     .collect { event -> when(event) { ... } }
     */
    fun analyzeImage(imageFile: File, message: String, sessionId: String = ""): Flow<StreamEvent> =
        callbackFlow {
            val requestBody = MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart(
                    "image", imageFile.name,
                    imageFile.asRequestBody("image/jpeg".toMediaType())
                )
                .addFormDataPart("message", message)
                .addFormDataPart("session_id", sessionId)
                .build()

            val request = Request.Builder()
                .url("${BuildConfig.API_BASE_URL}/analyze")
                .post(requestBody)
                .build()

            val call = okHttpClient.newCall(request)
            var isFirstEvent = true   // first SSE event = metadata, rest = tokens

            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: java.io.IOException) {
                    trySend(StreamEvent.Error("Network error: ${e.message}"))
                    close()
                }

                override fun onResponse(call: Call, response: Response) {
                    response.body?.source()?.use { source ->
                        try {
                            while (!source.exhausted()) {
                                val line = source.readUtf8Line() ?: break

                                // SSE lines start with "data: "
                                if (!line.startsWith("data: ")) continue
                                val payload = line.removePrefix("data: ").trim()

                                if (payload == "[DONE]") {
                                    trySend(StreamEvent.Done)
                                    break
                                }

                                // Parse JSON payload
                                val json = gson.fromJson(payload, Map::class.java)

                                when {
                                    // First event has session_id field
                                    isFirstEvent && json.containsKey("session_id") -> {
                                        val meta = gson.fromJson(payload, AnalyzeMetaEvent::class.java)
                                        trySend(StreamEvent.Meta(meta))
                                        isFirstEvent = false
                                    }
                                    json.containsKey("token") -> {
                                        val token = json["token"] as? String ?: ""
                                        if (token.isNotEmpty()) trySend(StreamEvent.Token(token))
                                    }
                                    json.containsKey("error") -> {
                                        trySend(StreamEvent.Error(json["error"] as? String ?: "Unknown error"))
                                    }
                                }
                            }
                        } catch (e: Exception) {
                            Log.e(TAG, "SSE parse error", e)
                            trySend(StreamEvent.Error("Stream error: ${e.message}"))
                        } finally {
                            close()
                        }
                    }
                }
            })

            // Cancel the OkHttp call if the Flow collector is cancelled
            awaitClose { call.cancel() }
        }

    // ── /chat — text follow-up + SSE stream ──────────────────────────────────

    /**
     * Send a follow-up text message and stream Gemini's response.
     * Same SSE pattern as analyzeImage, but only emits Token/Error/Done events.
     */
    fun sendChatMessage(
        sessionId: String,
        message:   String,
        history:   List<Map<String, String>>,
    ): Flow<StreamEvent> = callbackFlow {
        val body = gson.toJson(mapOf(
            "session_id" to sessionId,
            "message"    to message,
            "history"    to history,
        ))

        val request = Request.Builder()
            .url("${BuildConfig.API_BASE_URL}/chat")
            .post(RequestBody.create("application/json".toMediaType(), body))
            .build()

        val call = okHttpClient.newCall(request)

        call.enqueue(object : Callback {
            override fun onFailure(call: Call, e: java.io.IOException) {
                trySend(StreamEvent.Error("Network error: ${e.message}"))
                close()
            }

            override fun onResponse(call: Call, response: Response) {
                response.body?.source()?.use { source ->
                    try {
                        while (!source.exhausted()) {
                            val line = source.readUtf8Line() ?: break
                            if (!line.startsWith("data: ")) continue
                            val payload = line.removePrefix("data: ").trim()

                            if (payload == "[DONE]") { trySend(StreamEvent.Done); break }

                            val json = gson.fromJson(payload, Map::class.java)
                            when {
                                json.containsKey("token") -> {
                                    val token = json["token"] as? String ?: ""
                                    if (token.isNotEmpty()) trySend(StreamEvent.Token(token))
                                }
                                json.containsKey("error") ->
                                    trySend(StreamEvent.Error(json["error"] as? String ?: "Error"))
                            }
                        }
                    } catch (e: Exception) {
                        trySend(StreamEvent.Error("Stream error: ${e.message}"))
                    } finally {
                        close()
                    }
                }
            }
        })

        awaitClose { call.cancel() }
    }
}
