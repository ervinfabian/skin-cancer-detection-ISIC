// ui/ChatViewModel.kt
// ====================
// Holds all UI state for the chat screen. Survives configuration changes
// (screen rotation) because it extends ViewModel.
//
// Exposes LiveData observed by MainActivity — no direct UI refs here.

package com.dermai.app.ui

import android.content.Context
import android.net.Uri
import android.util.Log
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.dermai.app.api.ApiService
import com.dermai.app.api.StreamEvent
import com.dermai.app.model.ChatMessage
import com.dermai.app.model.Classification
import com.dermai.app.model.MessageRole
import com.dermai.app.util.ImageUtils
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.launch
import java.util.UUID

class ChatViewModel : ViewModel() {

    companion object { private const val TAG = "ChatViewModel" }

    private val api = ApiService.instance

    // ── Observed state ────────────────────────────────────────────────────────

    // All chat messages (drives the RecyclerView)
    private val _messages = MutableLiveData<List<ChatMessage>>(emptyList())
    val messages: LiveData<List<ChatMessage>> = _messages

    // True while waiting for/streaming a response — disables input
    private val _isStreaming = MutableLiveData(false)
    val isStreaming: LiveData<Boolean> = _isStreaming

    // Classification badge shown after image analysis
    private val _classification = MutableLiveData<Classification?>(null)
    val classification: LiveData<Classification?> = _classification

    // Firebase image URL of the last uploaded image
    private val _imageUrl = MutableLiveData<String?>(null)
    val imageUrl: LiveData<String?> = _imageUrl

    // Error snackbar messages
    private val _error = MutableLiveData<String?>(null)
    val error: LiveData<String?> = _error

    // ── Internal state ────────────────────────────────────────────────────────

    var sessionId: String = UUID.randomUUID().toString()   // current session
    private val messageList = mutableListOf<ChatMessage>() // backing list for _messages

    // ── Sending messages ──────────────────────────────────────────────────────

    /**
     * Send a message with an optional image attachment.
     * If imageUri is provided, calls /analyze (image + text).
     * Otherwise calls /chat (text only).
     *
     * @param context  needed to copy image to cache for upload
     * @param text     user's text message
     * @param imageUri content URI of the selected/captured image (nullable)
     */
    fun sendMessage(context: Context, text: String, imageUri: Uri? = null) {
        if (_isStreaming.value == true) return

        val userText = text.ifBlank { if (imageUri != null) "Please analyze this skin lesion." else return }

        // Add user message to chat
        val userMessage = ChatMessage(
            role     = MessageRole.USER,
            text     = userText,
            imageUri = imageUri?.toString(),
        )
        appendMessage(userMessage)

        // Add empty assistant message that will be filled during streaming
        val assistantMessage = ChatMessage(role = MessageRole.ASSISTANT, text = "")
        appendMessage(assistantMessage)

        _isStreaming.value = true

        viewModelScope.launch {
            val flow = if (imageUri != null) {
                // Copy image to temp file for multipart upload
                val tempFile = ImageUtils.uriToTempFile(context, imageUri)
                if (tempFile == null) {
                    _error.value = "Could not read image file."
                    _isStreaming.value = false
                    return@launch
                }
                api.analyzeImage(tempFile, userText, sessionId)
            } else {
                api.sendChatMessage(sessionId, userText, buildHistory())
            }

            flow
                .catch { e ->
                    Log.e(TAG, "Stream error", e)
                    _error.value = "Connection failed: ${e.message}"
                    finishStreaming()
                }
                .collect { event ->
                    when (event) {
                        is StreamEvent.Meta -> {
                            // Store session context from first /analyze event
                            sessionId = event.data.sessionId
                            _classification.postValue(event.data.classification)
                            _imageUrl.postValue(event.data.imageUrl)
                        }
                        is StreamEvent.Token -> {
                            // Append token to the last assistant message
                            updateLastAssistantMessage(event.text)
                        }
                        is StreamEvent.Error -> {
                            updateLastAssistantMessage("\n[Error: ${event.message}]")
                            finishStreaming()
                        }
                        is StreamEvent.Done -> {
                            finishStreaming()
                        }
                    }
                }
        }
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    private fun appendMessage(message: ChatMessage) {
        messageList.add(message)
        _messages.postValue(messageList.toList())
    }

    private fun updateLastAssistantMessage(newToken: String) {
        val lastIndex = messageList.indexOfLast { it.role == MessageRole.ASSISTANT }
        if (lastIndex == -1) return
        messageList[lastIndex] = messageList[lastIndex].copy(
            text = messageList[lastIndex].text + newToken
        )
        _messages.postValue(messageList.toList())
    }

    private fun finishStreaming() {
        _isStreaming.postValue(false)
    }

    /**
     * Build the history list expected by /chat endpoint.
     * Excludes the last (empty) assistant message — it's still being filled.
     */
    private fun buildHistory(): List<Map<String, String>> {
        return messageList
            .dropLast(1)          // exclude the streaming placeholder
            .filter { it.text.isNotBlank() }
            .map { mapOf("role" to it.role.name.lowercase(), "text" to it.text) }
    }

    fun clearError() { _error.value = null }

    fun startNewSession() {
        sessionId = UUID.randomUUID().toString()
        messageList.clear()
        _messages.value = emptyList()
        _classification.value = null
        _imageUrl.value = null
    }
}
