package com.jarvis.companion

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.core.content.ContextCompat
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.max

data class CapturedVoiceClip(
    val samples: FloatArray,
    val sampleRate: Int,
    val channels: Int,
    val durationMs: Int,
)

object CommandAudioRecorder {
    private val preferredSampleRates = intArrayOf(16_000, 44_100, 48_000)
    private const val CHANNELS = 1

    class LiveRecording internal constructor(
        private val recorder: AudioRecord,
        private val sampleRate: Int,
        private val keepRecording: AtomicBoolean,
        private val readThread: Thread,
        private val sampleLock: Any,
        private val samples: MutableList<Float>,
    ) {
        fun stopAndCapture(): Result<CapturedVoiceClip> {
            keepRecording.set(false)
            runCatching { recorder.stop() }
            runCatching { readThread.join(1_500L) }
            runCatching { recorder.release() }

            val captured = synchronized(sampleLock) {
                samples.toFloatArray()
            }

            return runCatching {
                if (captured.isEmpty()) {
                    throw IllegalStateException("Voice sample was empty.")
                }
                CapturedVoiceClip(
                    samples = captured,
                    sampleRate = sampleRate,
                    channels = CHANNELS,
                    durationMs = ((captured.size * 1000L) / max(1, sampleRate)).toInt(),
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

    fun startLiveRecording(context: Context): Result<LiveRecording> {
        if (
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            return Result.failure(SecurityException("Microphone permission is not granted."))
        }

        return runCatching {
            val (recorder, sampleRate, readBuffer) = buildRecorder()
            val keepRecording = AtomicBoolean(true)
            val sampleLock = Any()
            val samples = mutableListOf<Float>()
            recorder.startRecording()

            val readThread = Thread {
                while (keepRecording.get()) {
                    val read = recorder.read(readBuffer, 0, readBuffer.size)
                    if (read > 0) {
                        synchronized(sampleLock) {
                            for (index in 0 until read) {
                                samples += readBuffer[index] / 32768f
                            }
                        }
                    }
                }
            }.apply {
                name = "JarvisCommandAudioRecorder"
                start()
            }

            LiveRecording(
                recorder = recorder,
                sampleRate = sampleRate,
                keepRecording = keepRecording,
                readThread = readThread,
                sampleLock = sampleLock,
                samples = samples,
            )
        }
    }

    private fun buildRecorder(): Triple<AudioRecord, Int, ShortArray> {
        preferredSampleRates.forEach { sampleRate ->
            val minBuffer = AudioRecord.getMinBufferSize(
                sampleRate,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT
            )
            if (minBuffer <= 0) {
                return@forEach
            }

            val readBuffer = ShortArray(max(minBuffer / 2, 1024))
            val recorder = AudioRecord.Builder()
                .setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setSampleRate(sampleRate)
                        .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .build()
                )
                .setBufferSizeInBytes(max(minBuffer, readBuffer.size * 2))
                .build()

            if (recorder.state == AudioRecord.STATE_INITIALIZED) {
                return Triple(recorder, sampleRate, readBuffer)
            }
            recorder.release()
        }

        throw IllegalStateException("Could not initialize deterministic command audio recorder.")
    }
}
