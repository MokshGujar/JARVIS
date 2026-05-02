package com.jarvis.companion

import android.util.Base64
import java.nio.ByteBuffer
import java.nio.ByteOrder

object WavEncoding {
    fun encodeClipAsBase64(clip: CapturedVoiceClip): String {
        require(clip.channels == 1) { "Only mono clips are supported." }
        val pcmData = ByteBuffer.allocate(clip.samples.size * 2).order(ByteOrder.LITTLE_ENDIAN)
        for (sample in clip.samples) {
            val clamped = sample.coerceIn(-1f, 1f)
            val value = if (clamped < 0f) {
                (clamped * Short.MIN_VALUE.toFloat()).toInt()
            } else {
                (clamped * Short.MAX_VALUE.toFloat()).toInt()
            }
            pcmData.putShort(value.coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt()).toShort())
        }

        val pcmSize = pcmData.position()
        val bytesPerSample = 2
        val byteRate = clip.sampleRate * clip.channels * bytesPerSample
        val blockAlign = clip.channels * bytesPerSample
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
            put("RIFF".toByteArray())
            putInt(36 + pcmSize)
            put("WAVE".toByteArray())
            put("fmt ".toByteArray())
            putInt(16)
            putShort(1)
            putShort(clip.channels.toShort())
            putInt(clip.sampleRate)
            putInt(byteRate)
            putShort(blockAlign.toShort())
            putShort(16)
            put("data".toByteArray())
            putInt(pcmSize)
        }.array()

        val wavBytes = ByteArray(header.size + pcmSize)
        System.arraycopy(header, 0, wavBytes, 0, header.size)
        System.arraycopy(pcmData.array(), 0, wavBytes, header.size, pcmSize)
        return Base64.encodeToString(wavBytes, Base64.NO_WRAP)
    }
}
