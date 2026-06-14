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
import android.text.InputType
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.bumptech.glide.Glide
import com.dermai.app.R
import com.dermai.app.api.ApiService
import com.dermai.app.databinding.ActivityMainBinding
import com.dermai.app.util.NetworkConfig
import com.google.android.gms.auth.api.signin.GoogleSignIn
import com.google.android.gms.auth.api.signin.GoogleSignInOptions
import com.google.android.material.snackbar.Snackbar
import com.google.firebase.auth.FirebaseAuth
import java.io.File
import kotlinx.coroutines.launch

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

        // Guard: if not signed in, go back to login screen
        if (FirebaseAuth.getInstance().currentUser == null) {
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        // Initialize ApiService with the stored URL before the ViewModel accesses it.
        ApiService.init(NetworkConfig.getBaseUrl(this))

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
R.id.action_new_chat -> {
            viewModel.startNewSession()
            clearPendingImage()
            true
        }
R.id.action_about -> {
            showAboutDialog()
            true
        }
R.id.action_sign_out -> {
            signOut()
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

    // ── Settings dialog ───────────────────────────────────────────────────────

    private fun showSettingsDialog() {
        val ctx = this
        val padding = (24 * resources.displayMetrics.density).toInt()

        val layout = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(padding * 2, padding, padding * 2, 0)
        }

        val backendInput = EditText(ctx).apply {
            hint = "http://192.168.x.x:8000"
            setText(NetworkConfig.getBaseUrl(ctx))
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine()
        }

        val modelInput = EditText(ctx).apply {
            hint = "https://xxxx.trycloudflare.com  (leave empty to keep)"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine()
        }

        layout.addView(TextView(ctx).apply { text = "Backend server URL" })
        layout.addView(backendInput)
        layout.addView(TextView(ctx).apply {
            text = "Colab model URL"
            setPadding(0, padding, 0, 0)
        })
        layout.addView(modelInput)

        AlertDialog.Builder(ctx)
            .setTitle("Network settings")
            .setView(layout)
            .setPositiveButton("Save") { _, _ ->
                val newBackend = backendInput.text.toString().trim()
                if (newBackend.isNotEmpty()) {
                    NetworkConfig.setBaseUrl(ctx, newBackend)
                    ApiService.instance.updateBaseUrl(newBackend)
                    showSnackbar("Backend URL saved")
                }
                val newModel = modelInput.text.toString().trim()
                if (newModel.isNotEmpty()) {
                    sendModelUrlUpdate(newModel)
                }
            }
            .setNegativeButton("Cancel", null)
            .setNeutralButton("Test connection") { _, _ -> testConnection() }
            .show()
    }

    private fun sendModelUrlUpdate(url: String) {
        lifecycleScope.launch {
            try {
                ApiService.instance.restApi.updateModelUrl(mapOf("url" to url))
                showSnackbar("Model URL updated")
            } catch (e: Exception) {
                showSnackbar("Model URL update failed: ${e.message}")
            }
        }
    }

    private fun showAboutDialog() {
        val view = layoutInflater.inflate(R.layout.dialog_about, null)
        AlertDialog.Builder(this)
            .setTitle("DermAI")
            .setView(view)
            .setPositiveButton("Close", null)
            .show()
    }

    private fun signOut() {
        // Clear chat state before sign-out so the next user starts with a clean slate
        viewModel.startNewSession()
        clearPendingImage()

        FirebaseAuth.getInstance().signOut()
        val gso = GoogleSignInOptions.Builder(GoogleSignInOptions.DEFAULT_SIGN_IN).build()
        GoogleSignIn.getClient(this, gso).signOut().addOnCompleteListener {
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
        }
    }

    private fun testConnection() {
        lifecycleScope.launch {
            try {
                val result = ApiService.instance.restApi.health()
                showSnackbar("Connected — ${result["status"]} (${result["model"]})")
            } catch (e: Exception) {
                showSnackbar("Connection failed: ${e.message}")
            }
        }
    }
}