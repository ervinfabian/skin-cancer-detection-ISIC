// util/NetworkConfig.kt
// =====================
// Persists the backend server URL in SharedPreferences so the user can change it
// from the app without rebuilding. Falls back to the compile-time default from
// BuildConfig if no value has been saved yet.

package com.dermai.app.util

import android.content.Context
import com.dermai.app.BuildConfig

object NetworkConfig {
    private const val PREFS       = "network_config"
    private const val KEY_BASE_URL = "base_url"

    fun getBaseUrl(context: Context): String =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_BASE_URL, null)
            ?: BuildConfig.API_BASE_URL

    fun setBaseUrl(context: Context, url: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_BASE_URL, url.trimEnd('/'))
            .apply()
    }
}
