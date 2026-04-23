package com.dermai.app.ui

import com.dermai.app.R
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.net.Uri
import android.os.Bundle
import android.util.Log
import android.view.View
import android.widget.ImageButton
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.camera2.interop.Camera2CameraControl
import androidx.camera.camera2.interop.Camera2CameraInfo
import androidx.camera.camera2.interop.CaptureRequestOptions
import androidx.camera.camera2.interop.ExperimentalCamera2Interop
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import com.google.android.material.button.MaterialButton
import java.io.File
import java.util.concurrent.Executors

@ExperimentalCamera2Interop
class CameraActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_IMAGE_URI = "image_uri"
        private const val TAG = "CameraActivity"
    }

    private lateinit var previewView: PreviewView
    private lateinit var btnCapture: ImageButton
    private lateinit var btnMacro: MaterialButton
    private lateinit var tvMacroIndicator: TextView

    private var imageCapture: ImageCapture? = null
    private var camera2Control: Camera2CameraControl? = null
    private var minFocusDistance: Float = 10f  // fallback, overwritten after camera binds
    private var isMacroEnabled = true

    private val cameraExecutor = Executors.newSingleThreadExecutor()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_camera)

        previewView      = findViewById(R.id.previewView)
        btnCapture       = findViewById(R.id.btnCapture)
        btnMacro         = findViewById(R.id.btnMacro)
        tvMacroIndicator = findViewById(R.id.tvMacroIndicator)

        startCamera()
        updateMacroUI()

        btnMacro.setOnClickListener { toggleMacro() }
        btnCapture.setOnClickListener { takePhoto() }
    }

    private fun startCamera() {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener({
            val cameraProvider = cameraProviderFuture.get()
            bindCamera(cameraProvider)
        }, ContextCompat.getMainExecutor(this))
    }

    private fun bindCamera(cameraProvider: ProcessCameraProvider) {
        val selector = if (isMacroEnabled) findMacroSelector(cameraProvider)
                       else CameraSelector.DEFAULT_BACK_CAMERA

        val preview = Preview.Builder().build().also {
            it.setSurfaceProvider(previewView.surfaceProvider)
        }
        imageCapture = ImageCapture.Builder()
            .setCaptureMode(ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY)
            .build()

        try {
            cameraProvider.unbindAll()
            val cam = cameraProvider.bindToLifecycle(this, selector, preview, imageCapture)
            camera2Control = Camera2CameraControl.from(cam.cameraControl)

            minFocusDistance = Camera2CameraInfo.from(cam.cameraInfo)
                .getCameraCharacteristic(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE)
                ?: 10f

            if (isMacroEnabled) applyFocusMode()
        } catch (e: Exception) {
            Log.e(TAG, "Camera bind failed", e)
        }
    }

    // Use CameraManager to enumerate ALL physical cameras (including Samsung macro
    // cameras that CameraX hides because they lack BACKWARD_COMPATIBLE capability).
    // Pick the back camera with the highest LENS_INFO_MINIMUM_FOCUS_DISTANCE.
    private fun findMacroSelector(cameraProvider: ProcessCameraProvider): CameraSelector {
        val cameraManager = getSystemService(Context.CAMERA_SERVICE) as CameraManager

        var bestId: String? = null
        var bestMinFocus = -1f

        for (id in cameraManager.cameraIdList) {
            val chars = cameraManager.getCameraCharacteristics(id)
            val facing = chars.get(CameraCharacteristics.LENS_FACING) ?: continue
            if (facing != CameraCharacteristics.LENS_FACING_BACK) continue

            val minFocus = chars.get(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE) ?: 0f
            val fl = chars.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)?.firstOrNull() ?: 0f
            val res = chars.get(CameraCharacteristics.SENSOR_INFO_PIXEL_ARRAY_SIZE)
            Log.d(TAG, "Camera $id: minFocus=$minFocus fl=$fl res=$res")

            if (minFocus > bestMinFocus) {
                bestMinFocus = minFocus
                bestId = id
            }
        }

        Log.d(TAG, "Selected macro camera ID: $bestId (minFocus=$bestMinFocus)")

        if (bestId == null) return CameraSelector.DEFAULT_BACK_CAMERA

        return try {
            CameraSelector.Builder()
                .addCameraFilter { list ->
                    val filtered = list.filter { Camera2CameraInfo.from(it).cameraId == bestId }
                    filtered.ifEmpty { list }
                }
                .build()
        } catch (e: Exception) {
            Log.w(TAG, "Macro selector failed, falling back: ${e.message}")
            CameraSelector.DEFAULT_BACK_CAMERA
        }
    }

    private fun toggleMacro() {
        isMacroEnabled = !isMacroEnabled
        updateMacroUI()
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener({
            bindCamera(cameraProviderFuture.get())
        }, ContextCompat.getMainExecutor(this))
    }

    private fun applyFocusMode() {
        val c2 = camera2Control ?: return
        val options = if (isMacroEnabled) {
            CaptureRequestOptions.Builder()
                .setCaptureRequestOption(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_OFF)
                .setCaptureRequestOption(CaptureRequest.LENS_FOCUS_DISTANCE, minFocusDistance)
                .build()
        } else {
            CaptureRequestOptions.Builder()
                .setCaptureRequestOption(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
                .build()
        }
        c2.setCaptureRequestOptions(options)
    }

    private fun updateMacroUI() {
        if (isMacroEnabled) {
            btnMacro.setTextColor(Color.BLACK)
            btnMacro.backgroundTintList = ContextCompat.getColorStateList(this, android.R.color.white)
            tvMacroIndicator.visibility = View.VISIBLE
        } else {
            btnMacro.setTextColor(Color.WHITE)
            btnMacro.backgroundTintList = null
            tvMacroIndicator.visibility = View.GONE
        }
    }

    private fun takePhoto() {
        val capture = imageCapture ?: return
        btnCapture.isEnabled = false

        val photoFile = File(cacheDir, "dermai_capture_${System.currentTimeMillis()}.jpg")
        val outputOptions = ImageCapture.OutputFileOptions.Builder(photoFile).build()

        capture.takePicture(outputOptions, ContextCompat.getMainExecutor(this),
            object : ImageCapture.OnImageSavedCallback {
                override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                    val result = Intent().putExtra(EXTRA_IMAGE_URI, Uri.fromFile(photoFile).toString())
                    setResult(Activity.RESULT_OK, result)
                    finish()
                }
                override fun onError(exc: ImageCaptureException) {
                    Log.e(TAG, "Photo capture failed", exc)
                    btnCapture.isEnabled = true
                }
            }
        )
    }

    override fun onDestroy() {
        super.onDestroy()
        cameraExecutor.shutdown()
    }
}
