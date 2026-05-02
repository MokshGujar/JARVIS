package com.jarvis.companion

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.io.File

private enum class SensitiveTarget {
    WIFI_BACKEND,
    ETHERNET_BACKEND,
    PHONE_BRIDGE_TOKEN,
}

class MainActivity : ComponentActivity() {
    private lateinit var prefs: JarvisPreferences
    private lateinit var eventLogger: AppEventLogger

    private var wifiBackendUrl by mutableStateOf("")
    private var ethernetBackendUrl by mutableStateOf("")
    private var deviceId by mutableStateOf("")
    private var authToken by mutableStateOf("")
    private var privacyPin by mutableStateOf("")
    private var privacyPinSet by mutableStateOf(false)
    private var privacyPinSetupDialogVisible by mutableStateOf(false)
    private var voiceEnabled by mutableStateOf(true)
    private var backgroundVoiceEnabled by mutableStateOf(false)
    private var trustedVoiceEnabled by mutableStateOf(false)
    private var trustedVoiceprintEnrolled by mutableStateOf(false)
    private var voiceprintEnrollmentDialogVisible by mutableStateOf(false)
    private var voiceprintEnrollmentRecording by mutableStateOf(false)
    private var statusMessage by mutableStateOf("")
    private var notificationPermissionGranted by mutableStateOf(false)
    private var contactsPermissionGranted by mutableStateOf(false)
    private var callPhonePermissionGranted by mutableStateOf(false)
    private var answerCallPermissionGranted by mutableStateOf(false)
    private var microphonePermissionGranted by mutableStateOf(false)
    private var isTesting by mutableStateOf(false)
    private var activeVoiceprintRecording: CommandAudioRecorder.LiveRecording? = null

    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        notificationPermissionGranted = granted
        statusMessage = if (granted) {
            getString(R.string.notification_permission_granted)
        } else {
            getString(R.string.notification_permission_denied)
        }
    }

    private val contactsPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        contactsPermissionGranted = granted
        statusMessage = if (granted) {
            getString(R.string.contacts_permission_granted)
        } else {
            getString(R.string.contacts_permission_denied)
        }
    }

    private val answerCallPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        answerCallPermissionGranted = granted
        statusMessage = if (granted) {
            "Phone answer permission granted"
        } else {
            "Phone answer permission denied"
        }
    }

    private val callPhonePermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        callPhonePermissionGranted = granted
        statusMessage = if (granted) {
            "Phone call permission granted"
        } else {
            "Phone call permission denied"
        }
    }

    private val microphonePermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        microphonePermissionGranted = granted
        statusMessage = if (granted) {
            "Microphone permission granted"
        } else {
            "Microphone permission denied"
        }
        syncBackgroundVoiceService()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        prefs = JarvisPreferences(this)
        eventLogger = AppEventLogger(this)
        loadFromPreferences()
        refreshPermissionState()
        if (!privacyPinSet) {
            privacyPinSetupDialogVisible = true
        }
        if (!trustedVoiceprintEnrolled) {
            voiceprintEnrollmentDialogVisible = true
        }

        setContent {
            CompanionTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    CompanionScreen(
                        wifiBackendUrl = wifiBackendUrl,
                        onWifiBackendUrlChange = {
                            wifiBackendUrl = it
                            persistCurrentSettings()
                        },
                        ethernetBackendUrl = ethernetBackendUrl,
                        onEthernetBackendUrlChange = {
                            ethernetBackendUrl = it
                            persistCurrentSettings()
                        },
                        deviceId = deviceId,
                        onDeviceIdChange = {
                            deviceId = it
                            persistCurrentSettings()
                        },
                        authToken = authToken,
                        onAuthTokenChange = {
                            authToken = it
                            persistCurrentSettings()
                        },
                        privacyPin = privacyPin,
                        privacyPinSet = privacyPinSet,
                        privacyPinSetupDialogVisible = privacyPinSetupDialogVisible,
                        onSetInitialPrivacyPin = { setInitialPrivacyPin(it) },
                        voiceEnabled = voiceEnabled,
                        onVoiceEnabledChange = {
                            voiceEnabled = it
                            persistCurrentSettings()
                        },
                        backgroundVoiceEnabled = backgroundVoiceEnabled,
                        onBackgroundVoiceEnabledChange = { enabled ->
                            backgroundVoiceEnabled = enabled
                            persistCurrentSettings()
                            syncBackgroundVoiceService()
                        },
                        trustedVoiceEnabled = trustedVoiceEnabled,
                        onTrustedVoiceEnabledChange = {
                            trustedVoiceEnabled = it
                            persistCurrentSettings()
                            syncBackgroundVoiceService()
                        },
                        trustedVoiceprintEnrolled = trustedVoiceprintEnrolled,
                        onEnrollTrustedVoiceprint = { enrollTrustedVoiceprint() },
                        voiceprintEnrollmentDialogVisible = voiceprintEnrollmentDialogVisible,
                        voiceprintEnrollmentRecording = voiceprintEnrollmentRecording,
                        onStartVoiceprintEnrollmentRecording = { startVoiceprintEnrollmentRecording() },
                        onStopVoiceprintEnrollmentRecording = { stopVoiceprintEnrollmentRecording() },
                        onDismissVoiceprintEnrollment = { dismissVoiceprintEnrollment() },
                        statusMessage = statusMessage,
                        isTesting = isTesting,
                        notificationPermissionGranted = notificationPermissionGranted,
                        contactsPermissionGranted = contactsPermissionGranted,
                        answerCallPermissionGranted = answerCallPermissionGranted,
                        microphonePermissionGranted = microphonePermissionGranted,
                        onSave = { saveSettings() },
                        onRunTest = { runManualTest() },
                        onOpenNotificationAccess = { openNotificationAccess() },
                        onRequestNotificationPermission = { requestNotificationPermissionIfNeeded(forceRequest = true) },
                        onRequestContactsPermission = { requestContactsPermissionIfNeeded(forceRequest = true) },
                        onRequestAnswerCallPermission = { requestAnswerCallPermissionIfNeeded(forceRequest = true) },
                        onRequestMicrophonePermission = { requestMicrophonePermissionIfNeeded(forceRequest = true) },
                        onOpenBackend = { openBackendUrl() },
                    )
                }
            }
        }

        requestNotificationPermissionIfNeeded(forceRequest = false)
        requestContactsPermissionIfNeeded(forceRequest = false)
        requestCallPhonePermissionIfNeeded(forceRequest = false)
        requestAnswerCallPermissionIfNeeded(forceRequest = false)
        requestMicrophonePermissionIfNeeded(forceRequest = false)
        syncBackgroundVoiceService()
        refreshVoiceEnrollmentStatus()
    }

    override fun onResume() {
        super.onResume()
        refreshPermissionState()
        refreshVoiceEnrollmentStatus()
    }

    override fun onPause() {
        persistCurrentSettings()
        super.onPause()
    }

    override fun onDestroy() {
        deleteTrustedVoiceprintSample()
        super.onDestroy()
    }

    private fun loadFromPreferences() {
        wifiBackendUrl = prefs.getWifiBackendUrl()
        ethernetBackendUrl = prefs.getEthernetBackendUrl()
        deviceId = prefs.getDeviceId()
        authToken = prefs.getAuthToken()
        privacyPin = prefs.getPrivacyPin()
        privacyPinSet = prefs.isPrivacyPinSet()
        voiceEnabled = prefs.isVoiceEnabled()
        backgroundVoiceEnabled = prefs.isBackgroundVoiceEnabled()
        trustedVoiceEnabled = prefs.isTrustedVoiceEnabled()
        trustedVoiceprintEnrolled = false
        deleteTrustedVoiceprintSample()
        statusMessage = getString(R.string.status_default)
    }

    private fun saveSettings() {
        persistCurrentSettings()
        eventLogger.log("Settings saved")
        statusMessage = getString(R.string.saved_message)
        syncBackgroundVoiceService()
    }

    private fun persistCurrentSettings() {
        prefs.setWifiBackendUrl(wifiBackendUrl)
        prefs.setEthernetBackendUrl(ethernetBackendUrl)
        prefs.setBackendUrl(combinedBackendUrls())
        prefs.setDeviceId(deviceId)
        prefs.setAuthToken(authToken)
        prefs.setVoiceEnabled(voiceEnabled)
        prefs.setBackgroundVoiceEnabled(backgroundVoiceEnabled)
        prefs.setTrustedVoiceEnabled(trustedVoiceEnabled)
    }

    private fun enrollTrustedVoiceprint() {
        voiceprintEnrollmentDialogVisible = true
    }

    private fun startVoiceprintEnrollmentRecording() {
        if (!microphonePermissionGranted) {
            requestMicrophonePermissionIfNeeded(forceRequest = true)
            statusMessage = "Allow microphone access, then start voice enrollment again."
            return
        }
        if (voiceprintEnrollmentRecording) {
            return
        }

        statusMessage = "Starting voice enrollment recording..."
        voiceprintEnrollmentRecording = true
        if (backgroundVoiceEnabled) {
            BackgroundVoiceService.stop(applicationContext)
        }

        Thread {
            if (backgroundVoiceEnabled) {
                Thread.sleep(300L)
            }

            val result = CommandAudioRecorder.startLiveRecording(applicationContext)
            runOnUiThread {
                result.onSuccess { recording ->
                    activeVoiceprintRecording = recording
                    statusMessage = "Recording your voice sample. Speak naturally, then tap Stop and upload."
                }.onFailure { error ->
                    voiceprintEnrollmentRecording = false
                    activeVoiceprintRecording = null
                    statusMessage = "Voice enrollment recording failed: ${error.message ?: getString(R.string.unknown_error)}"
                    syncBackgroundVoiceService()
                }
            }
        }.start()
    }

    private fun stopVoiceprintEnrollmentRecording() {
        val recording = activeVoiceprintRecording
        if (recording == null) {
            statusMessage = "Voiceprint recorder is still starting. Try Stop again in a moment."
            return
        }

        activeVoiceprintRecording = null
        voiceprintEnrollmentRecording = false
        statusMessage = "Uploading your voice sample to Jarvis..."

        Thread {
            val result = recording.stopAndCapture()
            runOnUiThread {
                result.onSuccess { sample ->
                    Thread {
                        val api = JarvisApiClient()
                        runCatching {
                            api.enrollVoiceSample(
                                baseUrl = combinedBackendUrls(),
                                authToken = authToken,
                                audioBase64 = WavEncoding.encodeClipAsBase64(sample),
                                clientType = "android",
                                deviceId = prefs.getDeviceId(),
                                replaceExisting = !trustedVoiceprintEnrolled,
                            )
                        }.onSuccess { enroll ->
                            runOnUiThread {
                                trustedVoiceprintEnrolled = enroll.enrolled
                                if (enroll.sampleAccepted) {
                                    trustedVoiceEnabled = true
                                }
                                if (enroll.enrolled) {
                                    voiceprintEnrollmentDialogVisible = false
                                    persistCurrentSettings()
                                    eventLogger.log("Backend voice enrollment complete: ${enroll.acceptedSamples}/${enroll.requiredSamples}")
                                    statusMessage = "Voice enrollment complete on the Jarvis backend."
                                } else {
                                    eventLogger.log("Backend voice sample accepted: ${enroll.acceptedSamples}/${enroll.requiredSamples}")
                                    statusMessage = if (enroll.sampleAccepted) {
                                        "Voice sample accepted. ${enroll.acceptedSamples}/${enroll.requiredSamples} samples stored on the backend."
                                    } else {
                                        "Voice sample rejected: ${enroll.sampleReason.ifBlank { getString(R.string.unknown_error) }}"
                                    }
                                }
                                syncBackgroundVoiceService()
                                refreshVoiceEnrollmentStatus()
                            }
                        }.onFailure { error ->
                            runOnUiThread {
                                statusMessage = "Voice enrollment failed: ${error.message ?: getString(R.string.unknown_error)}"
                                syncBackgroundVoiceService()
                            }
                        }
                    }.start()
                }.onFailure { error ->
                    statusMessage = "Voice enrollment failed: ${error.message ?: getString(R.string.unknown_error)}"
                    syncBackgroundVoiceService()
                }
            }
        }.start()
    }

    private fun dismissVoiceprintEnrollment() {
        activeVoiceprintRecording?.cancel()
        activeVoiceprintRecording = null
        voiceprintEnrollmentRecording = false
        voiceprintEnrollmentDialogVisible = false
        syncBackgroundVoiceService()
    }

    private fun clearTrustedVoiceprint() {
        statusMessage = "Voice identity is managed by the Jarvis backend."
        syncBackgroundVoiceService()
    }

    private fun deleteTrustedVoiceprintSample() {
        runCatching {
            val sampleFile = voiceprintSampleFile()
            if (sampleFile.exists()) {
                sampleFile.delete()
            }
        }.onFailure {
            eventLogger.log("Voiceprint sample cleanup failed: ${it.message}")
        }
    }

    private fun voiceprintSampleFile(): File {
        return File(filesDir, "trusted_voiceprint_sample.wav")
    }

    private fun refreshVoiceEnrollmentStatus() {
        val baseUrl = combinedBackendUrls()
        if (baseUrl.isBlank()) {
            return
        }

        CoroutineScope(Dispatchers.IO).launch {
            val api = JarvisApiClient()
            runCatching {
                api.getVoiceStatus(
                    baseUrl = baseUrl,
                    authToken = authToken,
                )
            }.onSuccess { status ->
                runOnUiThread {
                    trustedVoiceprintEnrolled = status.profileEnrolled
                    if (!status.profileEnrolled && !voiceprintEnrollmentRecording) {
                        voiceprintEnrollmentDialogVisible = true
                    }
                    if (status.profileEnrolled) {
                        statusMessage = "Backend voice profile is enrolled for ${status.displayName.ifBlank { "Jarvis" }}."
                    }
                }
            }
        }
    }

    private fun setInitialPrivacyPin(pin: String) {
        if (privacyPinSet) {
            statusMessage = "Privacy PIN is already set and locked."
            return
        }

        if (prefs.setInitialPrivacyPin(pin)) {
            privacyPin = pin.filter(Char::isDigit).take(4)
            privacyPinSet = true
            privacyPinSetupDialogVisible = false
            statusMessage = "Privacy PIN set. It is locked for this device."
        } else {
            statusMessage = "Enter a 4-digit PIN to lock sensitive settings."
        }
    }

    private fun openNotificationAccess() {
        startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
    }

    private fun openBackendUrl() {
        val normalized = combinedBackendUrls()
        if (normalized.isBlank()) {
            statusMessage = getString(R.string.backend_open_missing)
            return
        }

        statusMessage = "Looking for a reachable backend..."
        CoroutineScope(Dispatchers.IO).launch {
            val api = JarvisApiClient()
            runCatching {
                val reachableBaseUrl = api.resolveReachableBaseUrl(
                    baseUrl = normalized,
                    authToken = authToken,
                )
                if (reachableBaseUrl.endsWith("/app", ignoreCase = true) || reachableBaseUrl.endsWith("/app/", ignoreCase = true)) {
                    reachableBaseUrl
                } else {
                    "$reachableBaseUrl/app/"
                }
            }.onSuccess { targetUrl ->
                runOnUiThread {
                    runCatching {
                        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(targetUrl)))
                        statusMessage = "Opening backend..."
                    }.onFailure { error ->
                        statusMessage = "Could not open backend: ${error.message ?: getString(R.string.unknown_error)}"
                    }
                }
            }.onFailure { error ->
                runOnUiThread {
                    statusMessage = "Could not reach backend: ${error.message ?: getString(R.string.unknown_error)}"
                }
            }
        }
    }

    private fun combinedBackendUrls(): String {
        return listOf(
            JarvisPreferences.normalizeBackendUrl(wifiBackendUrl),
            JarvisPreferences.normalizeBackendUrl(ethernetBackendUrl),
        ).filter { it.isNotBlank() }.joinToString("\n")
    }

    private fun runManualTest() {
        saveSettings()
        isTesting = true
        eventLogger.log("Manual test started")
        statusMessage = getString(R.string.test_running)

        CoroutineScope(Dispatchers.IO).launch {
            val coordinator = IncomingCallCoordinator(applicationContext)
            runCatching {
                coordinator.processIncomingCall(
                    phoneNumber = "+919876543210",
                    callerNameHint = "Test Caller",
                    source = "manual_test",
                    callDirection = "incoming",
                )
            }.onSuccess {
                eventLogger.log("Manual test completed")
                runOnUiThread {
                    isTesting = false
                    statusMessage = getString(R.string.test_success)
                }
            }.onFailure { error ->
                eventLogger.log("Manual test failed: ${error.message}")
                runOnUiThread {
                    isTesting = false
                    statusMessage = getString(
                        R.string.test_failed,
                        error.message ?: getString(R.string.unknown_error)
                    )
                }
            }
        }
    }

    private fun refreshPermissionState() {
        notificationPermissionGranted =
            Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
                ContextCompat.checkSelfPermission(
                    this,
                    Manifest.permission.POST_NOTIFICATIONS
                ) == PackageManager.PERMISSION_GRANTED

        contactsPermissionGranted =
            ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.READ_CONTACTS
            ) == PackageManager.PERMISSION_GRANTED

        callPhonePermissionGranted =
            ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.CALL_PHONE
            ) == PackageManager.PERMISSION_GRANTED

        answerCallPermissionGranted =
            Build.VERSION.SDK_INT < Build.VERSION_CODES.O ||
                ContextCompat.checkSelfPermission(
                    this,
                    Manifest.permission.ANSWER_PHONE_CALLS
                ) == PackageManager.PERMISSION_GRANTED

        microphonePermissionGranted =
            ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.RECORD_AUDIO
            ) == PackageManager.PERMISSION_GRANTED
    }

    private fun requestNotificationPermissionIfNeeded(forceRequest: Boolean) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            notificationPermissionGranted = true
            return
        }

        refreshPermissionState()
        if (notificationPermissionGranted) return

        if (forceRequest) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            return
        }

        ActivityCompat.requestPermissions(
            this,
            arrayOf(Manifest.permission.POST_NOTIFICATIONS),
            100
        )
    }

    private fun requestContactsPermissionIfNeeded(forceRequest: Boolean) {
        refreshPermissionState()
        if (contactsPermissionGranted) return

        if (forceRequest) {
            contactsPermissionLauncher.launch(Manifest.permission.READ_CONTACTS)
            return
        }

        ActivityCompat.requestPermissions(
            this,
            arrayOf(Manifest.permission.READ_CONTACTS),
            101
        )
    }

    private fun requestAnswerCallPermissionIfNeeded(forceRequest: Boolean) {
        refreshPermissionState()
        if (answerCallPermissionGranted || Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return

        if (forceRequest) {
            answerCallPermissionLauncher.launch(Manifest.permission.ANSWER_PHONE_CALLS)
            return
        }

        ActivityCompat.requestPermissions(
            this,
            arrayOf(Manifest.permission.ANSWER_PHONE_CALLS),
            102
        )
    }

    private fun requestCallPhonePermissionIfNeeded(forceRequest: Boolean) {
        refreshPermissionState()
        if (callPhonePermissionGranted) return

        if (forceRequest) {
            callPhonePermissionLauncher.launch(Manifest.permission.CALL_PHONE)
            return
        }

        ActivityCompat.requestPermissions(
            this,
            arrayOf(Manifest.permission.CALL_PHONE),
            104
        )
    }

    private fun requestMicrophonePermissionIfNeeded(forceRequest: Boolean) {
        refreshPermissionState()
        if (microphonePermissionGranted) return

        if (forceRequest) {
            microphonePermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
            return
        }

        ActivityCompat.requestPermissions(
            this,
            arrayOf(Manifest.permission.RECORD_AUDIO),
            103
        )
    }

    private fun syncBackgroundVoiceService() {
        if (!::prefs.isInitialized) return
        refreshPermissionState()

        if (backgroundVoiceEnabled && !microphonePermissionGranted) {
            requestMicrophonePermissionIfNeeded(forceRequest = true)
            return
        }

        prefs.setBackgroundVoiceEnabled(backgroundVoiceEnabled)

        if (backgroundVoiceEnabled && microphonePermissionGranted) {
            BackgroundVoiceService.start(applicationContext)
            statusMessage = "Background voice listening is active."
        } else {
            BackgroundVoiceService.stop(applicationContext)
        }
    }
}

@Composable
private fun CompanionScreen(
    wifiBackendUrl: String,
    onWifiBackendUrlChange: (String) -> Unit,
    ethernetBackendUrl: String,
    onEthernetBackendUrlChange: (String) -> Unit,
    deviceId: String,
    onDeviceIdChange: (String) -> Unit,
    authToken: String,
    onAuthTokenChange: (String) -> Unit,
    privacyPin: String,
    privacyPinSet: Boolean,
    privacyPinSetupDialogVisible: Boolean,
    onSetInitialPrivacyPin: (String) -> Unit,
    voiceEnabled: Boolean,
    onVoiceEnabledChange: (Boolean) -> Unit,
    backgroundVoiceEnabled: Boolean,
    onBackgroundVoiceEnabledChange: (Boolean) -> Unit,
    trustedVoiceEnabled: Boolean,
    onTrustedVoiceEnabledChange: (Boolean) -> Unit,
    trustedVoiceprintEnrolled: Boolean,
    onEnrollTrustedVoiceprint: () -> Unit,
    voiceprintEnrollmentDialogVisible: Boolean,
    voiceprintEnrollmentRecording: Boolean,
    onStartVoiceprintEnrollmentRecording: () -> Unit,
    onStopVoiceprintEnrollmentRecording: () -> Unit,
    onDismissVoiceprintEnrollment: () -> Unit,
    statusMessage: String,
    isTesting: Boolean,
    notificationPermissionGranted: Boolean,
    contactsPermissionGranted: Boolean,
    answerCallPermissionGranted: Boolean,
    microphonePermissionGranted: Boolean,
    onSave: () -> Unit,
    onRunTest: () -> Unit,
    onOpenNotificationAccess: () -> Unit,
    onRequestNotificationPermission: () -> Unit,
    onRequestContactsPermission: () -> Unit,
    onRequestAnswerCallPermission: () -> Unit,
    onRequestMicrophonePermission: () -> Unit,
    onOpenBackend: () -> Unit,
) {
    val uriHandler = LocalUriHandler.current
    var wifiRevealed by rememberSaveable { mutableStateOf(false) }
    var ethernetRevealed by rememberSaveable { mutableStateOf(false) }
    var tokenRevealed by rememberSaveable { mutableStateOf(false) }
    var pendingSensitiveTarget by rememberSaveable { mutableStateOf<SensitiveTarget?>(null) }
    var pinAttempt by rememberSaveable { mutableStateOf("") }
    var pendingSetupPin by rememberSaveable { mutableStateOf("") }
    var voiceprintPinDialogVisible by rememberSaveable { mutableStateOf(false) }
    var voiceprintPinAttempt by rememberSaveable { mutableStateOf("") }
    var voiceprintPinError by rememberSaveable { mutableStateOf(false) }

    fun requestSensitiveReveal(target: SensitiveTarget) {
        pendingSensitiveTarget = target
        pinAttempt = ""
    }

    fun hideSensitiveValue(target: SensitiveTarget) {
        when (target) {
            SensitiveTarget.WIFI_BACKEND -> wifiRevealed = false
            SensitiveTarget.ETHERNET_BACKEND -> ethernetRevealed = false
            SensitiveTarget.PHONE_BRIDGE_TOKEN -> tokenRevealed = false
        }
    }

    fun unlockSensitiveValue(target: SensitiveTarget) {
        when (target) {
            SensitiveTarget.WIFI_BACKEND -> wifiRevealed = true
            SensitiveTarget.ETHERNET_BACKEND -> ethernetRevealed = true
            SensitiveTarget.PHONE_BRIDGE_TOKEN -> tokenRevealed = true
        }
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .background(
                brush = Brush.verticalGradient(
                    colors = listOf(Color(0xFF07111F), Color(0xFF0D172A), Color(0xFF111B2F))
                )
            ),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        item {
            HeroCard()
        }

        item {
            SectionCard(
                title = "Connection",
                subtitle = "Point the companion at your Jarvis backend and keep the device identity stable."
            ) {
                AppTextField(
                    label = "Wi-Fi backend URL",
                    value = wifiBackendUrl,
                    onValueChange = onWifiBackendUrlChange,
                    placeholder = "http://192.168.1.20:8000",
                    keyboardType = KeyboardType.Uri,
                    obscured = true,
                    revealed = wifiRevealed,
                    onRevealToggleRequest = {
                        if (wifiRevealed) hideSensitiveValue(SensitiveTarget.WIFI_BACKEND)
                        else requestSensitiveReveal(SensitiveTarget.WIFI_BACKEND)
                    }
                )
                Spacer(modifier = Modifier.height(12.dp))
                AppTextField(
                    label = "Ethernet backend URL",
                    value = ethernetBackendUrl,
                    onValueChange = onEthernetBackendUrlChange,
                    placeholder = "http://192.168.31.253:8000",
                    keyboardType = KeyboardType.Uri,
                    obscured = true,
                    revealed = ethernetRevealed,
                    onRevealToggleRequest = {
                        if (ethernetRevealed) hideSensitiveValue(SensitiveTarget.ETHERNET_BACKEND)
                        else requestSensitiveReveal(SensitiveTarget.ETHERNET_BACKEND)
                    }
                )
                Spacer(modifier = Modifier.height(12.dp))
                AppTextField(
                    label = "Device ID",
                    value = deviceId,
                    onValueChange = onDeviceIdChange,
                    placeholder = "pixel-8"
                )
                Spacer(modifier = Modifier.height(12.dp))
                AppTextField(
                    label = "Phone bridge token",
                    value = authToken,
                    onValueChange = onAuthTokenChange,
                    placeholder = "Shared secret from backend",
                    obscured = true,
                    revealed = tokenRevealed,
                    onRevealToggleRequest = {
                        if (tokenRevealed) hideSensitiveValue(SensitiveTarget.PHONE_BRIDGE_TOKEN)
                        else requestSensitiveReveal(SensitiveTarget.PHONE_BRIDGE_TOKEN)
                    }
                )
                Spacer(modifier = Modifier.height(16.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Button(
                        onClick = onSave,
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("Save")
                    }
                    OutlinedButton(
                        onClick = onOpenBackend,
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("Open backend")
                    }
                }
            }
        }

        item {
            SectionCard(
                title = "Security",
                subtitle = "Sensitive connection details stay hidden behind your one-time PIN."
            ) {
                Text(
                    text = if (privacyPinSet) {
                        "Privacy PIN is set and locked. It cannot be changed from this screen."
                    } else {
                        "Set a 4-digit PIN once before sensitive values can be revealed."
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }

        item {
            SectionCard(
                title = "Permissions",
                subtitle = "Give the companion just the access it needs for caller lookup and alerts."
            ) {
                PermissionRow(
                    title = "Notifications",
                    description = "Required for incoming call alerts and spoken result playback.",
                    granted = notificationPermissionGranted,
                    buttonLabel = if (notificationPermissionGranted) "Granted" else "Allow",
                    onClick = onRequestNotificationPermission
                )
                HorizontalDivider(
                    modifier = Modifier.padding(vertical = 12.dp),
                    color = MaterialTheme.colorScheme.outline.copy(alpha = 0.35f)
                )
                PermissionRow(
                    title = "Contacts",
                    description = "Lets Jarvis match saved contacts before using public lookup.",
                    granted = contactsPermissionGranted,
                    buttonLabel = if (contactsPermissionGranted) "Granted" else "Allow",
                    onClick = onRequestContactsPermission
                )
                HorizontalDivider(
                    modifier = Modifier.padding(vertical = 12.dp),
                    color = MaterialTheme.colorScheme.outline.copy(alpha = 0.35f)
                )
                PermissionRow(
                    title = "Answer calls",
                    description = "Lets Jarvis answer an incoming call when you tell it to pick up.",
                    granted = answerCallPermissionGranted,
                    buttonLabel = if (answerCallPermissionGranted) "Granted" else "Allow",
                    onClick = onRequestAnswerCallPermission
                )
                HorizontalDivider(
                    modifier = Modifier.padding(vertical = 12.dp),
                    color = MaterialTheme.colorScheme.outline.copy(alpha = 0.35f)
                )
                PermissionRow(
                    title = "Microphone",
                    description = "Required for native background voice listening in the companion app.",
                    granted = microphonePermissionGranted,
                    buttonLabel = if (microphonePermissionGranted) "Granted" else "Allow",
                    onClick = onRequestMicrophonePermission
                )
                Spacer(modifier = Modifier.height(12.dp))
                OutlinedButton(
                    onClick = onOpenNotificationAccess,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("Open notification access")
                }
            }
        }

        item {
            SectionCard(
                title = "Behavior",
                subtitle = "Control how the companion speaks and secures native voice commands."
            ) {
                ToggleRow(
                    title = "Speak caller result aloud",
                    description = "Play Jarvis-generated audio when an incoming number is classified.",
                    checked = voiceEnabled,
                    onCheckedChange = onVoiceEnabledChange
                )
                HorizontalDivider(
                    modifier = Modifier.padding(vertical = 12.dp),
                    color = MaterialTheme.colorScheme.outline.copy(alpha = 0.35f)
                )
                ToggleRow(
                    title = "Background voice listening",
                    description = "Runs a native foreground mic service so Jarvis can hear phone-control commands even when the browser is in background.",
                    checked = backgroundVoiceEnabled,
                    onCheckedChange = onBackgroundVoiceEnabledChange
                )
                HorizontalDivider(
                    modifier = Modifier.padding(vertical = 12.dp),
                    color = MaterialTheme.colorScheme.outline.copy(alpha = 0.35f)
                )
                ToggleRow(
                    title = "Trusted voice / backend profile",
                    description = "Require backend speaker verification before Jarvis accepts background phone voice commands.",
                    checked = trustedVoiceEnabled,
                    onCheckedChange = onTrustedVoiceEnabledChange
                )
                if (trustedVoiceEnabled) {
                    Spacer(modifier = Modifier.height(12.dp))
                    Text(
                        text = if (trustedVoiceprintEnrolled) {
                            "Voiceprint enrolled. Enter your PIN before replacing it."
                        } else {
                            "No backend voice profile is enrolled yet. Jarvis will not accept trusted background voice commands until you enroll one."
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Button(
                        onClick = {
                            if (trustedVoiceprintEnrolled) {
                                voiceprintPinDialogVisible = true
                                voiceprintPinAttempt = ""
                                voiceprintPinError = false
                            } else {
                                onEnrollTrustedVoiceprint()
                            }
                        },
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text(if (trustedVoiceprintEnrolled) "Re-enroll voice" else "Enroll voice")
                    }
                    HorizontalDivider(
                        modifier = Modifier.padding(vertical = 12.dp),
                        color = MaterialTheme.colorScheme.outline.copy(alpha = 0.35f)
                    )
                } else {
                    HorizontalDivider(
                        modifier = Modifier.padding(vertical = 12.dp),
                        color = MaterialTheme.colorScheme.outline.copy(alpha = 0.35f)
                    )
                }
                Text(
                    text = "Caller identity uses saved contacts first, local phone-number metadata second, then the Jarvis backend provider chain.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }

        item {
            SectionCard(
                title = "Actions",
                subtitle = "Run a safe manual check to verify alerts, speech, and backend connectivity."
            ) {
                Button(
                    onClick = onRunTest,
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !isTesting
                ) {
                    Text(if (isTesting) "Running test..." else "Run notification and voice test")
                }
                Spacer(modifier = Modifier.height(10.dp))
                Text(
                    text = "The manual test uses a sample caller number and should trigger the same pipeline as a real incoming call.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }

        item {
            SectionCard(
                title = "Docs",
                subtitle = "Need to revisit setup? The companion README still has the backend contract and Android setup notes."
            ) {
                OutlinedButton(
                    onClick = {
                        uriHandler.openUri("https://developer.android.com/develop")
                    },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("Open Android docs")
                }
            }
        }

        item {
            StatusFooter(statusMessage = statusMessage)
        }
    }

    if (privacyPinSetupDialogVisible) {
        AlertDialog(
            onDismissRequest = {},
            title = {
                Text("Set privacy PIN")
            },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(
                        text = "Create a 4-digit PIN once. After it is set, it cannot be changed from this app screen.",
                        style = MaterialTheme.typography.bodyMedium
                    )
                    AppTextField(
                        label = "New PIN",
                        value = pendingSetupPin,
                        onValueChange = { pendingSetupPin = it.filter(Char::isDigit).take(4) },
                        placeholder = "4 digits",
                        keyboardType = KeyboardType.NumberPassword,
                        obscured = true,
                        allowReveal = false
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        onSetInitialPrivacyPin(pendingSetupPin)
                        pendingSetupPin = ""
                    },
                    enabled = pendingSetupPin.length == 4
                ) {
                    Text("Lock PIN")
                }
            }
        )
    }

    if (voiceprintPinDialogVisible) {
        AlertDialog(
            onDismissRequest = {
                voiceprintPinDialogVisible = false
                voiceprintPinAttempt = ""
                voiceprintPinError = false
            },
            title = {
                Text("Confirm re-enrollment")
            },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(
                        text = "Enter your privacy PIN before replacing the saved backend voice enrollment.",
                        style = MaterialTheme.typography.bodyMedium
                    )
                    AppTextField(
                        label = "PIN",
                        value = voiceprintPinAttempt,
                        onValueChange = {
                            voiceprintPinAttempt = it.filter(Char::isDigit).take(4)
                            voiceprintPinError = false
                        },
                        placeholder = "0000",
                        keyboardType = KeyboardType.NumberPassword,
                        obscured = true,
                        allowReveal = false
                    )
                    if (voiceprintPinError) {
                        Text(
                            text = "Incorrect PIN.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.tertiary
                        )
                    }
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        if (voiceprintPinAttempt == privacyPin && voiceprintPinAttempt.length == 4) {
                            voiceprintPinDialogVisible = false
                            voiceprintPinAttempt = ""
                            voiceprintPinError = false
                            onEnrollTrustedVoiceprint()
                        } else {
                            voiceprintPinError = true
                        }
                    },
                    enabled = voiceprintPinAttempt.length == 4
                ) {
                    Text("Continue")
                }
            },
            dismissButton = {
                TextButton(
                    onClick = {
                        voiceprintPinDialogVisible = false
                        voiceprintPinAttempt = ""
                        voiceprintPinError = false
                    }
                ) {
                    Text("Cancel")
                }
            }
        )
    }

    if (voiceprintEnrollmentDialogVisible) {
        AlertDialog(
            onDismissRequest = onDismissVoiceprintEnrollment,
            title = {
                Text(if (trustedVoiceprintEnrolled) "Re-enroll your voice" else "Enroll your voice")
            },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(
                        text = if (voiceprintEnrollmentRecording) {
                            "Recording now. Speak naturally for a few seconds, then stop and upload."
                        } else {
                            "Jarvis will store your enrollment samples on the backend and use them for centralized speaker verification."
                        },
                        style = MaterialTheme.typography.bodyMedium
                    )
                    Text(
                        text = if (microphonePermissionGranted) {
                            "Use a quiet room and say a few normal Jarvis commands at your usual distance from the phone."
                        } else {
                            "Microphone permission is needed before recording."
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        if (microphonePermissionGranted) {
                            if (voiceprintEnrollmentRecording) {
                                onStopVoiceprintEnrollmentRecording()
                            } else {
                                onStartVoiceprintEnrollmentRecording()
                            }
                        } else {
                            onRequestMicrophonePermission()
                        }
                    }
                ) {
                    Text(
                        when {
                            !microphonePermissionGranted -> "Allow mic"
                            voiceprintEnrollmentRecording -> "Stop and save"
                            else -> "Start recording"
                        }
                    )
                }
            },
            dismissButton = {
                TextButton(onClick = onDismissVoiceprintEnrollment) {
                    Text(if (voiceprintEnrollmentRecording) "Cancel recording" else "Later")
                }
            }
        )
    }

    if (pendingSensitiveTarget != null) {
        AlertDialog(
            onDismissRequest = {
                pendingSensitiveTarget = null
                pinAttempt = ""
            },
            title = {
                Text("Enter 4-digit PIN")
            },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(
                        text = "Enter your privacy PIN to reveal this value.",
                        style = MaterialTheme.typography.bodyMedium
                    )
                    AppTextField(
                        label = "PIN",
                        value = pinAttempt,
                        onValueChange = { pinAttempt = it.filter(Char::isDigit).take(4) },
                        placeholder = "0000",
                        keyboardType = KeyboardType.NumberPassword,
                        obscured = true,
                        allowReveal = false
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        val target = pendingSensitiveTarget ?: return@TextButton
                        if (pinAttempt == privacyPin && pinAttempt.length == 4) {
                            unlockSensitiveValue(target)
                            pendingSensitiveTarget = null
                            pinAttempt = ""
                        }
                    },
                    enabled = pinAttempt.length == 4
                ) {
                    Text("Unlock")
                }
            },
            dismissButton = {
                TextButton(
                    onClick = {
                        pendingSensitiveTarget = null
                        pinAttempt = ""
                    }
                ) {
                    Text("Cancel")
                }
            }
        )
    }
}

@Composable
private fun HeroCard() {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color.Transparent),
        shape = RoundedCornerShape(28.dp)
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(
                    brush = Brush.linearGradient(
                        colors = listOf(Color(0xFF1A5CFF), Color(0xFF13A5B3), Color(0xFF0DDF8C))
                    )
                )
                .padding(24.dp)
        ) {
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(10.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text(
                    text = "JARVIS",
                    style = MaterialTheme.typography.headlineMedium,
                    fontWeight = FontWeight.Bold,
                    fontFamily = FontFamily.Monospace,
                    letterSpacing = 6.sp,
                    color = Color.White,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        }
    }
}

@Composable
private fun StatusFooter(statusMessage: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 6.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(
            modifier = Modifier
                .size(10.dp)
                .background(MaterialTheme.colorScheme.secondary, CircleShape)
        )
        Spacer(modifier = Modifier.width(10.dp))
        Text(
            text = statusMessage,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onBackground,
            maxLines = 3,
            overflow = TextOverflow.Ellipsis
        )
    }
}

@Composable
private fun SectionCard(
    title: String,
    subtitle: String,
    content: @Composable () -> Unit
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.88f)
        ),
        shape = RoundedCornerShape(24.dp)
    ) {
        Column(
            modifier = Modifier.padding(20.dp)
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold
            )
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = subtitle,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(modifier = Modifier.height(18.dp))
            content()
        }
    }
}

@Composable
private fun AppTextField(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    keyboardType: KeyboardType = KeyboardType.Text,
    obscured: Boolean = false,
    revealed: Boolean = false,
    onRevealToggleRequest: (() -> Unit)? = null,
    allowReveal: Boolean = true,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text(label) },
        placeholder = { Text(placeholder) },
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = keyboardType),
        shape = RoundedCornerShape(18.dp),
        visualTransformation = if (obscured && !revealed) PasswordVisualTransformation() else VisualTransformation.None,
        trailingIcon = if (obscured && allowReveal && onRevealToggleRequest != null) {
            {
                Text(
                    text = if (revealed) "Hide" else "Show",
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.clickable { onRevealToggleRequest() }
                )
            }
        } else {
            null
        }
    )
}

@Composable
private fun ToggleRow(
    title: String,
    description: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Medium
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = description,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        Spacer(modifier = Modifier.width(12.dp))
        Switch(checked = checked, onCheckedChange = onCheckedChange)
    }
}

@Composable
private fun PermissionRow(
    title: String,
    description: String,
    granted: Boolean,
    buttonLabel: String,
    onClick: () -> Unit
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Medium
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = description,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        Spacer(modifier = Modifier.width(12.dp))
        OutlinedButton(onClick = onClick, enabled = !granted) {
            Text(buttonLabel)
        }
    }
}

@Composable
private fun CompanionTheme(content: @Composable () -> Unit) {
    val colors = darkColorScheme(
        primary = Color(0xFF5CA4FF),
        secondary = Color(0xFF3AD2A0),
        tertiary = Color(0xFFFFC857),
        background = Color(0xFF09111E),
        surface = Color(0xFF122033),
        surfaceVariant = Color(0xFF1A2B42),
        onPrimary = Color.White,
        onSecondary = Color(0xFF03251A),
        onBackground = Color(0xFFEAF2FF),
        onSurface = Color(0xFFEAF2FF),
        onSurfaceVariant = Color(0xFFACC0DA),
        outline = Color(0xFF4F6785)
    )

    MaterialTheme(
        colorScheme = colors,
        typography = MaterialTheme.typography,
        content = content
    )
}
