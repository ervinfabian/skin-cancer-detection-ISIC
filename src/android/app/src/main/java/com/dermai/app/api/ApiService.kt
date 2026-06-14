// api/ApiService.kt
// ==================
// Handles all network communication with the FastAPI backend.
//
// Two patterns:
//   1. OkHttp raw streaming  — SSE endpoints (/analyze, /chat), long read timeout
//   2. Retrofit              — REST calls (/history, /sessions, /health, /model-url)
//                              with automatic retry on transient network errors
//
// Initialization:
//   Call ApiService.init(baseUrl) once before any access (e.g. in Application.onCreate
//   or at the top of MainActivity.onCreate). After that, use ApiService.instance.
//   Call ApiService.instance.updateBaseUrl(url) to change the server URL at runtime.

package com.dermai.app.api

import android.util.Log
import com.dermai.app.BuildConfig
import com.dermai.app.model.*
import com.google.gson.Gson
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import com.google.android.gms.tasks.Tasks
import com.google.firebase.auth.FirebaseAuth
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.asRequestBody
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.*
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

// ── Retrofit interface (REST endpoints only) ──────────────────────────────────

interface DermApiRest {
    @GET("history/{session_id}")
    suspend fun getSession(@Path("session_id") sessionId: String): Session

    @GET("sessions")
    suspend fun listSessions(@Query("limit") limit: Int = 20): List<Session>

    @GET("health")
    suspend fun health(): Map<String, String>

    @PUT("model-url")
    suspend fun updateModelUrl(@Body body: Map<String, String>): Map<String, String>
}

// ── SSE stream event types ────────────────────────────────────────────────────

sealed class StreamEvent {
    data class Meta(val data: AnalyzeMetaEvent) : StreamEvent()
    data class Token(val text: String)          : StreamEvent()
    data class Error(val message: String)       : StreamEvent()
    object Done                                 : StreamEvent()
}

// ── Auth interceptor — attaches Firebase ID token to every request ────────────
// Runs on an OkHttp background thread — safe to block with runBlocking.
// Uses the coroutine .await() extension (kotlinx-coroutines-play-services)
// instead of the deprecated Tasks.await().

private class AuthInterceptor : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val user = FirebaseAuth.getInstance().currentUser
            ?: return chain.proceed(chain.request())

        val token = try {
            Tasks.await(user.getIdToken(false)).token
        } catch (e: Exception) {
            null
        } ?: return chain.proceed(chain.request())

        return chain.proceed(
            chain.request().newBuilder()
                .addHeader("Authorization", "Bearer $token")
                .build()
        )
    }
}

// ── Retry interceptor — REST calls only, not used on SSE streams ──────────────
// Retries up to maxRetries times on IOException or server errors (5xx).
// Each retry waits exponentially longer (500 ms, 1 s, 2 s, …, capped at 8 s).

private class RetryInterceptor(private val maxRetries: Int = 3) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        var attempt = 0
        var lastException: IOException? = null
        while (attempt <= maxRetries) {
            try {
                val response = chain.proceed(chain.request())
                if (response.isSuccessful || attempt >= maxRetries) return response
                response.close()
            } catch (e: IOException) {
                lastException = e
                if (attempt >= maxRetries) throw e
            }
            attempt++
            Thread.sleep((500L shl attempt.coerceAtMost(4)).coerceAtMost(8_000L))
        }
        throw lastException ?: IOException("Max retries exceeded")
    }
}

// ── ApiService ────────────────────────────────────────────────────────────────

class ApiService private constructor(initialUrl: String) {

    companion object {
        private const val TAG = "ApiService"

        @Volatile private var _instance: ApiService? = null

        val instance: ApiService
            get() = _instance
                ?: error("ApiService not initialized — call ApiService.init(url) first")

        // Call once before first access (MainActivity.onCreate or Application.onCreate).
        // Subsequent calls are no-ops; use updateBaseUrl() to change the URL later.
        fun init(baseUrl: String): ApiService =
            _instance ?: synchronized(this) {
                _instance ?: ApiService(baseUrl).also { _instance = it }
            }
    }

    @Volatile var baseUrl: String = initialUrl.trimEnd('/')
        private set

    private val gson = Gson()

    private val authInterceptor = AuthInterceptor()

    // Long-timeout client for SSE streams — auth + no retry (handled at flow level)
    private val sseClient = OkHttpClient.Builder()
        .readTimeout(120, TimeUnit.SECONDS)
        .connectTimeout(15, TimeUnit.SECONDS)
        .addInterceptor(authInterceptor)
        .build()

    // Short-timeout client for REST calls — auth + automatic retry on failure
    private val restOkHttp = OkHttpClient.Builder()
        .readTimeout(30, TimeUnit.SECONDS)
        .connectTimeout(15, TimeUnit.SECONDS)
        .addInterceptor(authInterceptor)
        .addInterceptor(RetryInterceptor(maxRetries = 3))
        .build()

    @Volatile var restApi: DermApiRest = buildRetrofit()
        private set

    private fun buildRetrofit(): DermApiRest =
        Retrofit.Builder()
            .baseUrl("$baseUrl/")
            .client(restOkHttp)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(DermApiRest::class.java)

    // Update the server base URL at runtime (e.g. from the settings dialog).
    // Rebuilds the Retrofit client; ongoing SSE streams use the new URL on their next request.
    fun updateBaseUrl(newUrl: String) {
        baseUrl = newUrl.trimEnd('/')
        restApi = buildRetrofit()
    }

    // ── /analyze — image upload + SSE stream ─────────────────────────────────
    // On network failure the flow throws IOException so callers can use retryWhen.

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
                .url("$baseUrl/analyze")
                .post(requestBody)
                .build()

            val call = sseClient.newCall(request)
            var isFirstEvent = true

            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    close(e)   // throws so retryWhen can catch it
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
                                    isFirstEvent && json.containsKey("session_id") -> {
                                        val meta = gson.fromJson(payload, AnalyzeMetaEvent::class.java)
                                        trySend(StreamEvent.Meta(meta))
                                        isFirstEvent = false
                                    }
                                    json.containsKey("token") -> {
                                        val token = json["token"] as? String ?: ""
                                        if (token.isNotEmpty()) trySend(StreamEvent.Token(token))
                                    }
                                    json.containsKey("error") ->
                                        trySend(StreamEvent.Error(json["error"] as? String ?: "Unknown error"))
                                }
                            }
                        } catch (e: Exception) {
                            Log.e(TAG, "SSE parse error", e)
                            close(e)
                        } finally {
                            close()
                        }
                    }
                }
            })

            awaitClose { call.cancel() }
        }

    // ── /chat — follow-up text + SSE stream ──────────────────────────────────

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
            .url("$baseUrl/chat")
            .post(RequestBody.create("application/json".toMediaType(), body))
            .build()

        val call = sseClient.newCall(request)

        call.enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                close(e)
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
                        close(e)
                    } finally {
                        close()
                    }
                }
            }
        })

        awaitClose { call.cancel() }
    }
}
