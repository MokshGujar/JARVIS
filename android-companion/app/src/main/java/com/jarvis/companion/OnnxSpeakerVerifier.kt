package com.jarvis.companion

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.core.content.ContextCompat
import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.nio.FloatBuffer
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

object OnnxSpeakerVerifier {
    const val SAMPLE_RATE = 16_000
    const val MODEL_ASSET_NAME = "speaker_verify.onnx"

    private const val RECORD_MS = 4_500
    private const val MODEL_SAMPLE_COUNT = SAMPLE_RATE * RECORD_MS / 1000
    private const val MIN_FEATURE_SIZE = 32
    private const val SERIALIZATION_PREFIX = "onnx-v1:"

    data class VoiceprintSample(
        val features: List<FloatArray>,
        val samples: FloatArray,
    )

    class LiveRecording internal constructor(
        private val context: Context,
        private val recorder: AudioRecord,
        private val keepRecording: AtomicBoolean,
        private val readThread: Thread,
        private val sampleLock: Any,
        private val samples: MutableList<Float>,
    ) {
        fun stopAndExtract(): Result<VoiceprintSample> {
            keepRecording.set(false)
            runCatching { recorder.stop() }
            runCatching { readThread.join(1_500L) }
            runCatching { recorder.release() }

            val captured = synchronized(sampleLock) {
                samples.toFloatArray()
            }

            return runCatching {
                if (captured.size < SAMPLE_RATE) {
                    throw IllegalStateException("Voice sample was too short.")
                }
                VoiceprintSample(
                    features = listOf(extractEmbedding(context, prepareModelSamples(captured))),
                    samples = captured,
                )
            }
        }

        fun cancel() {
            keepRecording.set(false)
            runCatching { recorder.stop() }
            runCatching { readThread.join(1_500L) }
            runCatching { recorder.release() }
        }
    }

    fun isModelAvailable(context: Context): Boolean {
        return runCatching {
            context.assets.open(MODEL_ASSET_NAME).use { true }
        }.getOrDefault(false)
    }

    fun startLiveRecording(context: Context): Result<LiveRecording> {
        val appContext = context.applicationContext
        if (!isModelAvailable(appContext)) {
            return Result.failure(IllegalStateException("speaker_verify.onnx is missing. Add it to app/src/main/assets and re-enroll your voice."))
        }
        if (ContextCompat.checkSelfPermission(appContext, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            return Result.failure(SecurityException("Microphone permission is not granted."))
        }

        val minBuffer = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )
        if (minBuffer <= 0) {
            return Result.failure(IllegalStateException("Could not prepare microphone recorder."))
        }

        return runCatching {
            val readBuffer = ShortArray(max(minBuffer / 2, 1024))
            val recorder = buildRecorder(minBuffer, readBuffer.size * 2)
            if (recorder.state != AudioRecord.STATE_INITIALIZED) {
                recorder.release()
                throw IllegalStateException("Microphone recorder was not initialized.")
            }

            val keepRecording = AtomicBoolean(true)
            val sampleLock = Any()
            val samples = mutableListOf<Float>()
            recorder.startRecording()

            val readThread = Thread {
                while (keepRecording.get()) {
                    val read = recorder.read(readBuffer, 0, readBuffer.size)
                    if (read > 0) {
                        synchronized(sampleLock) {
                            for (i in 0 until read) {
                                samples += readBuffer[i] / 32768f
                            }
                        }
                    }
                }
            }.apply {
                name = "JarvisOnnxSpeakerEnrollment"
                start()
            }

            LiveRecording(
                context = appContext,
                recorder = recorder,
                keepRecording = keepRecording,
                readThread = readThread,
                sampleLock = sampleLock,
                samples = samples,
            )
        }
    }

    fun recordAndExtractFeatureSet(context: Context): Result<List<FloatArray>> {
        val appContext = context.applicationContext
        if (!isModelAvailable(appContext)) {
            return Result.failure(IllegalStateException("speaker_verify.onnx is missing."))
        }
        if (ContextCompat.checkSelfPermission(appContext, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            return Result.failure(SecurityException("Microphone permission is not granted."))
        }

        val minBuffer = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )
        if (minBuffer <= 0) {
            return Result.failure(IllegalStateException("Could not prepare microphone recorder."))
        }

        val targetSamples = MODEL_SAMPLE_COUNT
        val readBuffer = ShortArray(max(minBuffer / 2, 1024))
        val samples = FloatArray(targetSamples)
        var offset = 0
        var recorder: AudioRecord? = null

        return runCatching {
            recorder = buildRecorder(minBuffer, readBuffer.size * 2)
            recorder?.startRecording()

            val deadline = System.currentTimeMillis() + RECORD_MS + 900L
            while (offset < targetSamples && System.currentTimeMillis() < deadline) {
                val read = recorder?.read(readBuffer, 0, min(readBuffer.size, targetSamples - offset)) ?: 0
                if (read > 0) {
                    for (i in 0 until read) {
                        samples[offset + i] = readBuffer[i] / 32768f
                    }
                    offset += read
                }
            }

            if (offset < SAMPLE_RATE) {
                throw IllegalStateException("Voice sample was too short.")
            }

            listOf(extractEmbedding(appContext, prepareModelSamples(samples.copyOf(offset))))
        }.also {
            runCatching { recorder?.stop() }
            runCatching { recorder?.release() }
        }
    }

    fun maxSimilarity(enrolled: List<FloatArray>, current: List<FloatArray>): Float {
        if (enrolled.isEmpty() || current.isEmpty()) return 0f
        var best = 0f
        for (enrolledFeature in enrolled) {
            for (currentFeature in current) {
                best = max(best, cosine(enrolledFeature, currentFeature))
            }
        }
        return best
    }

    fun serializeFeatureSet(features: List<FloatArray>): String {
        return SERIALIZATION_PREFIX + features.joinToString(";") { feature ->
            feature.joinToString(",") { "%.6f".format(Locale.US, it) }
        }
    }

    fun parseFeatureSet(serialized: String): List<FloatArray> {
        val trimmed = serialized.trim()
        if (!trimmed.startsWith(SERIALIZATION_PREFIX)) {
            return emptyList()
        }
        return trimmed.removePrefix(SERIALIZATION_PREFIX)
            .split(';')
            .mapNotNull { item ->
                val values = item.split(',').mapNotNull { it.trim().toFloatOrNull() }
                values.takeIf { it.size >= MIN_FEATURE_SIZE }?.toFloatArray()
            }
    }

    private fun extractEmbedding(context: Context, samples: FloatArray): FloatArray {
        val modelBytes = context.assets.open(MODEL_ASSET_NAME).use { it.readBytes() }
        val env = OrtEnvironment.getEnvironment()
        env.createSession(modelBytes, OrtSession.SessionOptions()).use { session ->
            val inputName = session.inputNames.firstOrNull()
                ?: throw IllegalStateException("ONNX speaker model has no input.")
            val shape = inferInputShape(session, samples.size)
            OnnxTensor.createTensor(env, FloatBuffer.wrap(samples), shape).use { tensor ->
                session.run(mapOf(inputName to tensor)).use { results ->
                    val raw = results[0].value
                    return l2Normalize(flattenOutput(raw))
                }
            }
        }
    }

    private fun prepareModelSamples(samples: FloatArray): FloatArray {
        if (samples.size == MODEL_SAMPLE_COUNT) {
            return samples
        }

        if (samples.size < MODEL_SAMPLE_COUNT) {
            return FloatArray(MODEL_SAMPLE_COUNT) { index ->
                samples.getOrElse(index) { 0f }
            }
        }

        val windowStep = max(SAMPLE_RATE / 4, 1)
        var bestStart = 0
        var bestEnergy = Float.NEGATIVE_INFINITY
        var start = 0

        while (start + MODEL_SAMPLE_COUNT <= samples.size) {
            var energy = 0f
            for (i in start until start + MODEL_SAMPLE_COUNT) {
                energy += samples[i] * samples[i]
            }
            if (energy > bestEnergy) {
                bestEnergy = energy
                bestStart = start
            }
            start += windowStep
        }

        return samples.copyOfRange(bestStart, bestStart + MODEL_SAMPLE_COUNT)
    }

    private fun inferInputShape(session: OrtSession, sampleCount: Int): LongArray {
        val info = session.inputInfo.values.firstOrNull()?.info
        val shape = (info as? ai.onnxruntime.TensorInfo)?.shape
        if (shape != null && shape.isNotEmpty()) {
            val sanitized = shape.mapIndexed { index, dim ->
                when {
                    dim > 0 -> dim
                    index == shape.lastIndex -> sampleCount.toLong()
                    else -> 1L
                }
            }.toLongArray()
            val product = sanitized.fold(1L) { acc, dim -> acc * dim }
            if (product == sampleCount.toLong()) {
                return sanitized
            }
        }
        return longArrayOf(1L, sampleCount.toLong())
    }

    private fun flattenOutput(raw: Any?): FloatArray {
        return when (raw) {
            is FloatArray -> raw
            is Array<*> -> raw.flatMapTo(mutableListOf()) { item ->
                flattenOutput(item).asIterable()
            }.toFloatArray()
            else -> throw IllegalStateException("Unsupported ONNX speaker output.")
        }
    }

    private fun l2Normalize(values: FloatArray): FloatArray {
        var sum = 0f
        for (value in values) {
            sum += value * value
        }
        val norm = sqrt(sum).takeIf { it > 0f } ?: 1f
        return FloatArray(values.size) { index -> values[index] / norm }
    }

    private fun cosine(a: FloatArray, b: FloatArray): Float {
        val size = min(a.size, b.size)
        if (size == 0) return 0f
        var dot = 0f
        for (i in 0 until size) {
            dot += a[i] * b[i]
        }
        return dot.coerceIn(-1f, 1f)
    }

    private fun buildRecorder(minBuffer: Int, requestedBufferBytes: Int): AudioRecord {
        return AudioRecord.Builder()
            .setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
            .setAudioFormat(
                AudioFormat.Builder()
                    .setSampleRate(SAMPLE_RATE)
                    .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .build()
            )
            .setBufferSizeInBytes(max(minBuffer, requestedBufferBytes))
            .build()
    }
}
