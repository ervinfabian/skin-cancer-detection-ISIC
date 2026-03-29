// ui/ChatAdapter.kt
// ==================
// RecyclerView adapter that renders chat messages.
// Two view types: USER (right-aligned) and ASSISTANT (left-aligned).
// Uses DiffUtil for efficient list updates during streaming.

package com.dermai.app.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.bumptech.glide.Glide
import com.dermai.app.R
import com.dermai.app.model.ChatMessage
import com.dermai.app.model.MessageRole

class ChatAdapter : ListAdapter<ChatMessage, RecyclerView.ViewHolder>(DiffCallback()) {

    companion object {
        private const val VIEW_TYPE_USER      = 0
        private const val VIEW_TYPE_ASSISTANT = 1
    }

    override fun getItemViewType(position: Int): Int =
        if (getItem(position).role == MessageRole.USER) VIEW_TYPE_USER else VIEW_TYPE_ASSISTANT

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): RecyclerView.ViewHolder {
        val inflater = LayoutInflater.from(parent.context)
        return when (viewType) {
            VIEW_TYPE_USER -> UserViewHolder(
                inflater.inflate(R.layout.item_message_user, parent, false)
            )
            else -> AssistantViewHolder(
                inflater.inflate(R.layout.item_message_assistant, parent, false)
            )
        }
    }

    override fun onBindViewHolder(holder: RecyclerView.ViewHolder, position: Int) {
        val message = getItem(position)
        when (holder) {
            is UserViewHolder      -> holder.bind(message)
            is AssistantViewHolder -> holder.bind(message)
        }
    }

    // ── ViewHolders ───────────────────────────────────────────────────────────

    class UserViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        private val tvText:    TextView  = view.findViewById(R.id.tv_message)
        private val ivImage:   ImageView = view.findViewById(R.id.iv_image)

        fun bind(message: ChatMessage) {
            tvText.text = message.text

            // Show image thumbnail if this message has an attached image
            if (message.imageUri != null) {
                ivImage.visibility = View.VISIBLE
                Glide.with(itemView.context)
                    .load(message.imageUri)
                    .centerCrop()
                    .into(ivImage)
            } else {
                ivImage.visibility = View.GONE
            }
        }
    }

    class AssistantViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        private val tvText: TextView = view.findViewById(R.id.tv_message)

        fun bind(message: ChatMessage) {
            // Show a blinking cursor if text is empty (streaming not started yet)
            tvText.text = if (message.text.isEmpty()) "▋" else message.text
        }
    }

    // ── DiffUtil — efficient list diffing during streaming updates ────────────

    class DiffCallback : DiffUtil.ItemCallback<ChatMessage>() {
        // Use timestamp as stable ID
        override fun areItemsTheSame(old: ChatMessage, new: ChatMessage) =
            old.timestamp == new.timestamp

        // During streaming, text changes → not same content
        override fun areContentsTheSame(old: ChatMessage, new: ChatMessage) =
            old.text == new.text && old.imageUri == new.imageUri
    }
}
