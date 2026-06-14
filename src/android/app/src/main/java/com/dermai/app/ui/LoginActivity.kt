// ui/LoginActivity.kt
// ====================
// Entry point of the app. Shows a Google Sign-In button.
// On successful authentication, starts MainActivity and finishes itself.
// If the user is already signed in (token still valid), skips straight to MainActivity.

package com.dermai.app.ui

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import com.dermai.app.R
import com.dermai.app.api.ApiService
import com.dermai.app.util.NetworkConfig
import com.google.android.gms.auth.api.signin.GoogleSignIn
import com.google.android.gms.auth.api.signin.GoogleSignInClient
import com.google.android.gms.auth.api.signin.GoogleSignInOptions
import com.google.android.gms.common.SignInButton
import com.google.android.gms.common.api.ApiException
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.auth.GoogleAuthProvider

class LoginActivity : AppCompatActivity() {

    private lateinit var auth: FirebaseAuth
    private lateinit var googleSignInClient: GoogleSignInClient

    // Modern Activity Result API — replaces deprecated startActivityForResult/onActivityResult
    private val signInLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        val task = GoogleSignIn.getSignedInAccountFromIntent(result.data)
        try {
            val account = task.getResult(ApiException::class.java)
            firebaseAuthWithGoogle(account.idToken!!)
        } catch (e: ApiException) {
            setStatus("Sign-in failed: ${e.statusCode}")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        auth = FirebaseAuth.getInstance()

        // Already signed in — go straight to the chat screen
        if (auth.currentUser != null) {
            launchMain()
            return
        }

        setContentView(R.layout.activity_login)

        // Initialize ApiService early so it's ready when MainActivity starts
        ApiService.init(NetworkConfig.getBaseUrl(this))

        // Configure Google Sign-In — request ID token for Firebase Auth
        val gso = GoogleSignInOptions.Builder(GoogleSignInOptions.DEFAULT_SIGN_IN)
            .requestIdToken(getString(R.string.default_web_client_id))
            .requestEmail()
            .build()
        googleSignInClient = GoogleSignIn.getClient(this, gso)

        val btnSignIn = findViewById<SignInButton>(R.id.btn_google_sign_in)
        btnSignIn.setSize(SignInButton.SIZE_WIDE)
        btnSignIn.setOnClickListener { startGoogleSignIn() }
    }

    private fun startGoogleSignIn() {
        setStatus("Signing in…")
        signInLauncher.launch(googleSignInClient.signInIntent)
    }

    private fun firebaseAuthWithGoogle(idToken: String) {
        val credential = GoogleAuthProvider.getCredential(idToken, null)
        auth.signInWithCredential(credential)
            .addOnSuccessListener { launchMain() }
            .addOnFailureListener { e -> setStatus("Auth failed: ${e.message}") }
    }

    private fun launchMain() {
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }

    private fun setStatus(msg: String) {
        val tv = findViewById<TextView?>(R.id.tv_status) ?: return
        tv.text = msg
        tv.visibility = View.VISIBLE
    }
}
