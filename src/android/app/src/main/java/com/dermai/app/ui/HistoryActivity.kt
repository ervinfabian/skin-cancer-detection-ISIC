// ui/HistoryActivity.kt
// ======================
// Displays a list of past DermAI sessions fetched from FastAPI (/sessions).
// Each session shows: date, classification result, and a thumbnail.
// Tapping a session opens it in MainActivity (future: restore conversation).

package com.dermai.app.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.dermai.app.R
import com.dermai.app.api.ApiService
import com.dermai.app.databinding.ActivityHistoryBinding
import com.dermai.app.model.Session
import kotlinx.coroutines.launch

class HistoryActivity : AppCompatActivity() {

    private lateinit var binding: ActivityHistoryBinding
    private val api = ApiService.instance

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityHistoryBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setSupportActionBar(binding.toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        supportActionBar?.title = "Past Sessions"

        binding.recyclerHistory.layoutManager = LinearLayoutManager(this)

        loadSessions()
    }

    private fun loadSessions() {
        binding.progressHistory.visibility = View.VISIBLE
        lifecycleScope.launch {
            try {
                val sessions = api.restApi.listSessions()
                binding.progressHistory.visibility = View.GONE
                if (sessions.isEmpty()) {
                    binding.tvEmpty.visibility = View.VISIBLE
                } else {
                    binding.recyclerHistory.adapter = HistoryAdapter(sessions)
                }
            } catch (e: Exception) {
                binding.progressHistory.visibility = View.GONE
                binding.tvEmpty.text = "Could not load sessions: ${e.message}"
                binding.tvEmpty.visibility = View.VISIBLE
            }
        }
    }

    override fun onSupportNavigateUp(): Boolean { finish(); return true }
}

// ── Simple adapter for the sessions list ──────────────────────────────────────

class HistoryAdapter(private val sessions: List<Session>) :
    RecyclerView.Adapter<HistoryAdapter.SessionViewHolder>() {

    class SessionViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val tvDate:           TextView = view.findViewById(R.id.tv_date)
        val tvClassification: TextView = view.findViewById(R.id.tv_classification)
        val tvMessageCount:   TextView = view.findViewById(R.id.tv_message_count)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
        SessionViewHolder(
            LayoutInflater.from(parent.context)
                .inflate(R.layout.item_session, parent, false)
        )

    override fun getItemCount() = sessions.size

    override fun onBindViewHolder(holder: SessionViewHolder, position: Int) {
        val session = sessions[position]
        holder.tvDate.text = session.createdAt?.take(10) ?: "Unknown date"
        holder.tvClassification.text = session.classification?.let {
            "${it.label} · ${(it.confidence * 100).toInt()}%"
        } ?: "No image"
        holder.tvMessageCount.text = "${session.messages.size} messages"
    }
}
