package com.jarvis.companion

import android.content.Context
import android.media.MediaPlayer
import java.io.File

class Mp3Speaker(context: Context) {
    private val appContext = context.applicationContext
    @Volatile
    private var currentPlayer: MediaPlayer? = null
    @Volatile
    private var currentTempFile: File? = null

    fun play(audioBytes: ByteArray): Result<Unit> {
        if (audioBytes.isEmpty()) {
            return Result.failure(IllegalArgumentException("Audio payload is empty"))
        }

        return runCatching {
            stopCurrentPlayback()
            val tempFile = File.createTempFile("jarvis-caller-", ".mp3", appContext.cacheDir)
            tempFile.writeBytes(audioBytes)

            val player = MediaPlayer().apply {
                setDataSource(tempFile.absolutePath)
                setOnCompletionListener {
                    if (currentPlayer === it) {
                        currentPlayer = null
                    }
                    if (currentTempFile == tempFile) {
                        currentTempFile = null
                    }
                    it.release()
                    tempFile.delete()
                }
                setOnErrorListener { mp, _, _ ->
                    if (currentPlayer === mp) {
                        currentPlayer = null
                    }
                    if (currentTempFile == tempFile) {
                        currentTempFile = null
                    }
                    mp.release()
                    tempFile.delete()
                    true
                }
                prepare()
                currentTempFile = tempFile
                currentPlayer = this
                start()
            }
        }
    }

    @Synchronized
    private fun stopCurrentPlayback() {
        currentPlayer?.runCatching {
            if (isPlaying) {
                stop()
            }
        }
        currentPlayer?.release()
        currentPlayer = null
        currentTempFile?.delete()
        currentTempFile = null
    }
}
