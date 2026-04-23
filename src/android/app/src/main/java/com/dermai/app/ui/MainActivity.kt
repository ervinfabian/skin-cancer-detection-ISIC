// ui/MainActivity.kt
// ===================
// Single Activity for the DermAI chat screen.
// Handles:
//   - Camera capture (via FileProvider)
//   - Gallery image picker
//   - Observing ChatViewModel LiveData → updating UI
//   - Sending messages with optional image

package com.dermai.app.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import android.view.View
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.LinearLayoutManager
import com.bumptech.glide.Glide
import com.dermai.app.R
import com.dermai.app.databinding.ActivityMainBinding
import com.google.android.material.snackbar.Snackbar
import java.io.File

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val viewModel: ChatViewModel by viewModels()
    private lateinit var chatAdapter: ChatAdapter

    // URI of the image selected from gallery or camera (pending send)
    private var pendingImageUri: Uri? = null

    // ── Activity result launchers ─────────────────────────────────────────────

    // Camera capture (custom CameraActivity)
    private val cameraLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            val uriString = result.data?.getStringExtra(CameraActivity.EXTRA_IMAGE_URI)
            if (uriString != null) setPendingImage(Uri.parse(uriString))
        }
    }

    // Gallery picker
    private val galleryLauncher = registerForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri ->
        if (uri != null) setPendingImage(uri)
    }

    // Camera permission
    private val cameraPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) launchCamera() else showSnackbar("Camera permission required")
    }

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setSupportActionBar(binding.toolbar)
        supportActionBar?.title = ""

        setupRecyclerView()
        setupInputArea()
        observeViewModel()
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.menu_main, menu)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean = when (item.itemId) {
        R.id.action_history -> {
            startActivity(Intent(this, HistoryActivity::class.java))
            true
        }
        R.id.action_new_chat -> {
            viewModel.startNewSession()
            clearPendingImage()
            true
        }
        else -> super.onOptionsItemSelected(item)
    }

    // ── Setup ─────────────────────────────────────────────────────────────────

    private fun setupRecyclerView() {
        chatAdapter = ChatAdapter()
        binding.recyclerChat.apply {
            adapter = chatAdapter
            layoutManager = LinearLayoutManager(this@MainActivity).apply {
                stackFromEnd = true
            }
        }
    }

    private fun setupInputArea() {
        // Set hint color programmatically (hintTextColor attr not available on all API levels)
        binding.etMessage.setHintTextColor(getColor(R.color.text_dim))

        // Camera button
        binding.btnCamera.setOnClickListener {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED
            ) launchCamera()
            else cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
        }

        // Gallery button
        binding.btnGallery.setOnClickListener {
            galleryLauncher.launch("image/*")
        }

        // Remove pending image
        binding.btnRemoveImage.setOnClickListener { clearPendingImage() }

        // Send button
        binding.btnSend.setOnClickListener {
            val text = binding.etMessage.text.toString().trim()
            if (text.isEmpty() && pendingImageUri == null) return@setOnClickListener

            viewModel.sendMessage(this, text, pendingImageUri)
            binding.etMessage.text?.clear()
            clearPendingImage()
        }
    }

    private fun observeViewModel() {
        // Messages → update RecyclerView
        viewModel.messages.observe(this) { messages ->
            chatAdapter.submitList(messages.toList())
            if (messages.isNotEmpty()) {
                binding.recyclerChat.scrollToPosition(messages.size - 1)
            }
        }

        // Streaming state → toggle send button + progress bar
        viewModel.isStreaming.observe(this) { streaming ->
            binding.btnSend.isEnabled = !streaming
            binding.progressStreaming.visibility = if (streaming) View.VISIBLE else View.GONE
        }

        // Classification result → show badge
        viewModel.classification.observe(this) { classification ->
            if (classification != null) {
                binding.classificationBadge.visibility = View.VISIBLE
                val pct = (classification.confidence * 100).toInt()
                binding.tvClassification.text = "${classification.label} · $pct%"
                val color = if (classification.label.lowercase().contains("malign"))
                    getColor(R.color.malignant) else getColor(R.color.benign)
                binding.classificationBadge.setBackgroundColor(color)
            } else {
                binding.classificationBadge.visibility = View.GONE
            }
        }

        // Errors → Snackbar
        viewModel.error.observe(this) { error ->
            if (error != null) {
                showSnackbar(error)
                viewModel.clearError()
            }
        }
    }

    // ── Image helpers ─────────────────────────────────────────────────────────

    @androidx.camera.camera2.interop.ExperimentalCamera2Interop
    private fun launchCamera() {
        cameraLauncher.launch(Intent(this, CameraActivity::class.java))
    }

    private fun setPendingImage(uri: Uri) {
        pendingImageUri = uri
        binding.imagePreviewContainer.visibility = View.VISIBLE
        Glide.with(this).load(uri).centerCrop().into(binding.ivImagePreview)
    }

    private fun clearPendingImage() {
        pendingImageUri = null
        binding.imagePreviewContainer.visibility = View.GONE
        binding.ivImagePreview.setImageDrawable(null)
    }

    private fun showSnackbar(message: String) {
        Snackbar.make(binding.root, message, Snackbar.LENGTH_LONG).show()
    }
}