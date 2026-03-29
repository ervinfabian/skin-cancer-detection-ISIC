// util/ImageUtils.kt
// ===================
// Utility for converting a content URI (from gallery/camera) into
// a real File on disk that OkHttp can read for multipart upload.

package com.dermai.app.util

import android.content.Context
import android.net.Uri
import java.io.File

object ImageUtils {

    /**
     * Copy a content URI into a temp JPEG file in the app cache directory.
     * Returns null if the URI cannot be read.
     *
     * Why needed: OkHttp's multipart upload requires a File, not a URI.
     * Content URIs (content://...) can't be used directly as file paths.
     */
    fun uriToTempFile(context: Context, uri: Uri): File? {
        return try {
            val inputStream = context.contentResolver.openInputStream(uri) ?: return null
            val tempFile = File(context.cacheDir, "upload_${System.currentTimeMillis()}.jpg")
            tempFile.outputStream().use { output -> inputStream.copyTo(output) }
            inputStream.close()
            tempFile
        } catch (e: Exception) {
            e.printStackTrace()
            null
        }
    }
}
