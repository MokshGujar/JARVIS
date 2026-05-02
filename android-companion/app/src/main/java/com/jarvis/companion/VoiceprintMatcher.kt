package com.jarvis.companion

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.core.content.ContextCompat
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.ln
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt

object VoiceprintMatcher {
    const val DEFAULT_THRESHOLD = 0.85f
    const val SAMPLE_RATE = 16_000

    private const val RECORD_MS = 4_500
    private const val MIN_VOICED_MS = 1_200
    private const val MIN_RMS = 0.010f
    private const val MAX_CLIPPED_RATIO = 0.08f
    private const val MAX_REPEATED_WINDOW_SIMILARITY = 0.998f
    private const val FRAME_MS = 25
    private const val HOP_MS = 10
    private const val FFT_SIZE = 512
    private const val MEL_FILTER_COUNT = 26
    private const val MFCC_COUNT = 13
    private const val MIN_FEATURE_SIZE = 60
    private const val MAX_FEATURE_WINDOWS = 10

    data class VoiceprintSample(
        val features: List<FloatArray>,
        val samples: FloatArray,
    )

    class LiveRecording internal constructor(
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
                    features = extractFeatureSet(captured),
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

    fun startLiveRecording(context: Context): Result<LiveRecording> {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
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
                name = "JarvisVoiceprintEnrollment"
                start()
            }

            LiveRecording(
                recorder = recorder,
                keepRecording = keepRecording,
                readThread = readThread,
                sampleLock = sampleLock,
                samples = samples,
            )
        }
    }

    fun recordAndExtract(context: Context): Result<FloatArray> {
        return recordAndExtractSample(context).map { sample ->
            sample.features.first()
        }
    }

    fun recordAndExtractFeatureSet(context: Context): Result<List<FloatArray>> {
        return recordAndExtractSample(context).map { sample ->
            sample.features
        }
    }

    fun recordAndExtractSample(context: Context): Result<VoiceprintSample> {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
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

        val targetSamples = SAMPLE_RATE * RECORD_MS / 1000
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

            val captured = samples.copyOf(offset)
            VoiceprintSample(
                features = extractFeatureSet(captured),
                samples = captured,
            )
        }.also {
            runCatching { recorder?.stop() }
            runCatching { recorder?.release() }
        }
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

    fun serialize(features: FloatArray): String {
        return features.joinToString(",") { "%.6f".format(Locale.US, it) }
    }

    fun serializeFeatureSet(features: List<FloatArray>): String {
        return features.joinToString(";") { serialize(it) }
    }

    fun parse(serialized: String): FloatArray? {
        val parts = serialized.split(',').mapNotNull { it.trim().toFloatOrNull() }
        return parts.takeIf { it.size >= MIN_FEATURE_SIZE }?.toFloatArray()
    }

    fun parseFeatureSet(serialized: String): List<FloatArray> {
        val trimmed = serialized.trim()
        if (trimmed.isBlank()) return emptyList()

        return if (trimmed.contains(";")) {
            trimmed.split(';').mapNotNull { parse(it) }
        } else {
            listOfNotNull(parse(trimmed))
        }
    }

    fun extractFeatureSet(samples: FloatArray): List<FloatArray> {
        val voiced = prepareSpeechSamples(samples)
        val features = mutableListOf(extract(voiced))
        val windowSize = SAMPLE_RATE * 3
        val step = SAMPLE_RATE

        var start = 0
        while (start + SAMPLE_RATE <= voiced.size && features.size < MAX_FEATURE_WINDOWS) {
            val end = min(voiced.size, start + windowSize)
            if (end - start >= SAMPLE_RATE) {
                runCatching {
                    features += extract(voiced.copyOfRange(start, end))
                }
            }
            start += step
        }

        return features.distinctBy { feature ->
            feature.joinToString(",") { "%.3f".format(Locale.US, it) }
        }
    }

    fun maxSimilarity(enrolled: List<FloatArray>, current: FloatArray): Float {
        return maxSimilarity(enrolled, listOf(current))
    }

    fun maxSimilarity(enrolled: List<FloatArray>, current: List<FloatArray>): Float {
        if (enrolled.isEmpty() || current.isEmpty()) return 0f

        val scores = mutableListOf<Float>()
        for (enrolledFeature in enrolled) {
            for (currentFeature in current) {
                scores += similarity(enrolledFeature, currentFeature)
            }
        }

        if (scores.isEmpty()) return 0f
        scores.sortDescending()
        val topCount = min(5, scores.size)
        val topAverage = scores.take(topCount).average().toFloat()
        val best = scores.first()
        return (best * 0.65f) + (topAverage * 0.35f)
    }

    fun similarity(a: FloatArray, b: FloatArray): Float {
        val size = min(a.size, b.size)
        if (size == 0) return 0f

        var dot = 0.0
        var aa = 0.0
        var bb = 0.0
        for (i in 0 until size) {
            dot += (a[i] * b[i]).toDouble()
            aa += (a[i] * a[i]).toDouble()
            bb += (b[i] * b[i]).toDouble()
        }

        val denom = sqrt(aa) * sqrt(bb)
        if (denom <= 0.0) return 0f

        val cosine = (dot / denom).toFloat().coerceIn(-1f, 1f)
        return ((cosine + 1f) / 2f).coerceIn(0f, 1f)
    }

    private fun prepareSpeechSamples(samples: FloatArray): FloatArray {
        val withoutDc = removeDc(samples)
        val clippedRatio = withoutDc.count { abs(it) > 0.98f }.toFloat() / max(1, withoutDc.size)
        if (clippedRatio > MAX_CLIPPED_RATIO) {
            throw IllegalStateException("Voice sample was clipped. Move farther from the mic and try again.")
        }

        val voiced = trimToVoice(withoutDc)
        if (voiced.size < SAMPLE_RATE * MIN_VOICED_MS / 1000) {
            throw IllegalStateException("Voice sample was too short or too quiet.")
        }

        val rms = rms(voiced)
        if (rms < MIN_RMS) {
            throw IllegalStateException("Voice sample was too quiet.")
        }
        if (hasRepeatedWaveformPattern(voiced)) {
            throw IllegalStateException("Voice sample looked repeated. Please speak live and try again.")
        }

        return normalizePeak(preEmphasis(voiced))
    }

    private fun hasRepeatedWaveformPattern(samples: FloatArray): Boolean {
        val windowSize = SAMPLE_RATE / 2
        if (samples.size < windowSize * 3) return false
        val first = samples.copyOfRange(0, windowSize)
        var repeated = 0
        var start = windowSize
        while (start + windowSize <= samples.size) {
            val next = samples.copyOfRange(start, start + windowSize)
            if (rawSimilarity(first, next) >= MAX_REPEATED_WINDOW_SIMILARITY) {
                repeated += 1
            }
            start += windowSize
        }
        return repeated >= 2
    }

    private fun rawSimilarity(a: FloatArray, b: FloatArray): Float {
        val size = min(a.size, b.size)
        if (size == 0) return 0f
        var dot = 0.0
        var aa = 0.0
        var bb = 0.0
        for (i in 0 until size) {
            dot += (a[i] * b[i]).toDouble()
            aa += (a[i] * a[i]).toDouble()
            bb += (b[i] * b[i]).toDouble()
        }
        val denom = sqrt(aa) * sqrt(bb)
        return if (denom <= 0.0) 0f else (dot / denom).toFloat().coerceIn(-1f, 1f)
    }

    private fun extract(samples: FloatArray): FloatArray {
        val frames = buildFrames(samples)
        if (frames.size < 12) {
            throw IllegalStateException("Voice sample was too short.")
        }

        val mfccFrames = frames.map { frame ->
            val power = powerSpectrum(frame)
            val melEnergies = melFilterEnergies(power)
            dct(melEnergies, MFCC_COUNT)
        }

        val features = mutableListOf<Float>()
        appendStats(features, mfccFrames, includeFirstCoefficient = false)
        appendDeltaStats(features, mfccFrames)
        appendProsodyStats(features, frames)

        val mean = features.average().toFloat()
        var variance = 0.0
        for (value in features) {
            variance += (value - mean) * (value - mean)
        }
        val std = sqrt(variance / max(1, features.size)).toFloat().coerceAtLeast(1e-5f)
        val standardized = features.map { (it - mean) / std }.toFloatArray()

        val norm = sqrt(standardized.sumOf { (it * it).toDouble() }).toFloat()
        return standardized.map { if (norm > 0f) it / norm else it }.toFloatArray()
    }

    private fun buildFrames(samples: FloatArray): List<FloatArray> {
        val frameSize = SAMPLE_RATE * FRAME_MS / 1000
        val hopSize = SAMPLE_RATE * HOP_MS / 1000
        val window = hamming(frameSize)
        val frames = mutableListOf<FloatArray>()
        var start = 0

        while (start + frameSize <= samples.size) {
            val frame = FloatArray(frameSize)
            var energy = 0.0
            for (i in 0 until frameSize) {
                val value = samples[start + i] * window[i]
                frame[i] = value
                energy += (value * value).toDouble()
            }
            if (sqrt(energy / frameSize) >= MIN_RMS * 0.55f) {
                frames += frame
            }
            start += hopSize
        }

        return frames
    }

    private fun appendStats(features: MutableList<Float>, mfccFrames: List<FloatArray>, includeFirstCoefficient: Boolean) {
        val startIndex = if (includeFirstCoefficient) 0 else 1
        for (coefficient in startIndex until MFCC_COUNT) {
            val values = mfccFrames.map { it[coefficient] }
            val mean = values.average().toFloat()
            val std = standardDeviation(values, mean)
            val low = percentile(values, 0.20f)
            val high = percentile(values, 0.80f)
            features += mean
            features += std
            features += high - low
        }
    }

    private fun appendDeltaStats(features: MutableList<Float>, mfccFrames: List<FloatArray>) {
        if (mfccFrames.size < 3) return

        for (coefficient in 1 until MFCC_COUNT) {
            val deltas = mutableListOf<Float>()
            for (i in 1 until mfccFrames.lastIndex) {
                deltas += (mfccFrames[i + 1][coefficient] - mfccFrames[i - 1][coefficient]) / 2f
            }
            val mean = deltas.average().toFloat()
            features += mean
            features += standardDeviation(deltas, mean)
        }
    }

    private fun appendProsodyStats(features: MutableList<Float>, frames: List<FloatArray>) {
        val rmsValues = frames.map { rms(it) }
        val zcrValues = frames.map { zeroCrossingRate(it) }
        val centroidValues = frames.map { spectralCentroid(it) }

        listOf(rmsValues, zcrValues, centroidValues).forEach { values ->
            val mean = values.average().toFloat()
            features += mean
            features += standardDeviation(values, mean)
            features += percentile(values, 0.80f) - percentile(values, 0.20f)
        }
    }

    private fun powerSpectrum(frame: FloatArray): FloatArray {
        val real = FloatArray(FFT_SIZE)
        val imag = FloatArray(FFT_SIZE)
        for (i in frame.indices) {
            real[i] = frame[i]
        }

        fft(real, imag)

        val bins = FFT_SIZE / 2 + 1
        val power = FloatArray(bins)
        for (i in 0 until bins) {
            power[i] = ((real[i] * real[i]) + (imag[i] * imag[i])) / FFT_SIZE
        }
        return power
    }

    private fun melFilterEnergies(power: FloatArray): FloatArray {
        val lowMel = hzToMel(80f)
        val highMel = hzToMel(SAMPLE_RATE / 2f)
        val melPoints = FloatArray(MEL_FILTER_COUNT + 2) { index ->
            lowMel + (highMel - lowMel) * index / (MEL_FILTER_COUNT + 1)
        }
        val bins = melPoints.map { mel ->
            (((FFT_SIZE + 1) * melToHz(mel) / SAMPLE_RATE).roundToInt()).coerceIn(0, power.lastIndex)
        }

        return FloatArray(MEL_FILTER_COUNT) { filter ->
            val left = bins[filter]
            val center = bins[filter + 1]
            val right = bins[filter + 2]
            var energy = 0.0

            if (center > left) {
                for (bin in left until center) {
                    energy += power[bin] * (bin - left).toDouble() / (center - left)
                }
            }
            if (right > center) {
                for (bin in center until right) {
                    energy += power[bin] * (right - bin).toDouble() / (right - center)
                }
            }

            ln(max(energy, 1e-10)).toFloat()
        }
    }

    private fun dct(values: FloatArray, coefficientCount: Int): FloatArray {
        return FloatArray(coefficientCount) { coefficient ->
            var sum = 0.0
            for (i in values.indices) {
                sum += values[i] * cos(PI * coefficient * (i + 0.5) / values.size)
            }
            sum.toFloat()
        }
    }

    private fun fft(real: FloatArray, imag: FloatArray) {
        val n = real.size
        var j = 0
        for (i in 1 until n) {
            var bit = n shr 1
            while (j and bit != 0) {
                j = j xor bit
                bit = bit shr 1
            }
            j = j xor bit
            if (i < j) {
                val tempReal = real[i]
                real[i] = real[j]
                real[j] = tempReal
                val tempImag = imag[i]
                imag[i] = imag[j]
                imag[j] = tempImag
            }
        }

        var length = 2
        while (length <= n) {
            val angle = -2.0 * PI / length
            val wLengthReal = cos(angle).toFloat()
            val wLengthImag = sin(angle).toFloat()
            var i = 0
            while (i < n) {
                var wReal = 1f
                var wImag = 0f
                for (k in 0 until length / 2) {
                    val evenReal = real[i + k]
                    val evenImag = imag[i + k]
                    val oddReal = real[i + k + length / 2] * wReal - imag[i + k + length / 2] * wImag
                    val oddImag = real[i + k + length / 2] * wImag + imag[i + k + length / 2] * wReal

                    real[i + k] = evenReal + oddReal
                    imag[i + k] = evenImag + oddImag
                    real[i + k + length / 2] = evenReal - oddReal
                    imag[i + k + length / 2] = evenImag - oddImag

                    val nextReal = wReal * wLengthReal - wImag * wLengthImag
                    wImag = wReal * wLengthImag + wImag * wLengthReal
                    wReal = nextReal
                }
                i += length
            }
            length = length shl 1
        }
    }

    private fun removeDc(samples: FloatArray): FloatArray {
        val mean = samples.average().toFloat()
        return FloatArray(samples.size) { index -> samples[index] - mean }
    }

    private fun trimToVoice(samples: FloatArray): FloatArray {
        val frameSize = SAMPLE_RATE * 30 / 1000
        val hopSize = SAMPLE_RATE * 10 / 1000
        val energies = mutableListOf<Pair<Int, Float>>()
        var start = 0
        while (start + frameSize <= samples.size) {
            energies += start to rms(samples, start, frameSize)
            start += hopSize
        }

        if (energies.isEmpty()) return samples

        val sorted = energies.map { it.second }.sorted()
        val noiseFloor = sorted[(sorted.size * 0.20f).roundToInt().coerceIn(0, sorted.lastIndex)]
        val threshold = max(MIN_RMS * 0.65f, noiseFloor * 2.4f)
        val voiced = energies.filter { it.second >= threshold }
        if (voiced.isEmpty()) return samples

        val first = max(0, voiced.first().first - frameSize)
        val last = min(samples.size, voiced.last().first + frameSize * 2)
        return samples.copyOfRange(first, last)
    }

    private fun normalizePeak(samples: FloatArray): FloatArray {
        val peak = samples.maxOfOrNull { abs(it) } ?: 0f
        if (peak <= 0f) return samples
        val gain = min(1f / peak, 8f)
        return FloatArray(samples.size) { index -> samples[index] * gain }
    }

    private fun preEmphasis(samples: FloatArray): FloatArray {
        if (samples.isEmpty()) return samples
        val emphasized = FloatArray(samples.size)
        emphasized[0] = samples[0]
        for (i in 1 until samples.size) {
            emphasized[i] = samples[i] - 0.97f * samples[i - 1]
        }
        return emphasized
    }

    private fun hamming(size: Int): FloatArray {
        return FloatArray(size) { index ->
            (0.54 - 0.46 * cos(2.0 * PI * index / max(1, size - 1))).toFloat()
        }
    }

    private fun rms(samples: FloatArray): Float {
        return rms(samples, 0, samples.size)
    }

    private fun rms(samples: FloatArray, start: Int, length: Int): Float {
        var sum = 0.0
        val end = min(samples.size, start + length)
        for (i in start until end) {
            sum += (samples[i] * samples[i]).toDouble()
        }
        return sqrt(sum / max(1, end - start)).toFloat()
    }

    private fun zeroCrossingRate(samples: FloatArray): Float {
        if (samples.size < 2) return 0f
        var crossings = 0
        for (i in 1 until samples.size) {
            if ((samples[i] >= 0f) != (samples[i - 1] >= 0f)) {
                crossings += 1
            }
        }
        return crossings.toFloat() / (samples.size - 1)
    }

    private fun spectralCentroid(frame: FloatArray): Float {
        val power = powerSpectrum(frame)
        var weighted = 0.0
        var total = 0.0
        for (i in power.indices) {
            val frequency = i.toDouble() * SAMPLE_RATE / FFT_SIZE
            weighted += frequency * power[i]
            total += power[i]
        }
        return if (total <= 0.0) 0f else (weighted / total / (SAMPLE_RATE / 2.0)).toFloat()
    }

    private fun standardDeviation(values: List<Float>, mean: Float): Float {
        if (values.isEmpty()) return 0f
        var variance = 0.0
        for (value in values) {
            variance += (value - mean) * (value - mean)
        }
        return sqrt(variance / values.size).toFloat()
    }

    private fun percentile(values: List<Float>, percentile: Float): Float {
        if (values.isEmpty()) return 0f
        val sorted = values.sorted()
        val index = ((sorted.size - 1) * percentile).roundToInt().coerceIn(0, sorted.lastIndex)
        return sorted[index]
    }

    private fun hzToMel(hz: Float): Float {
        return (2595.0 * log10(1.0 + hz / 700.0)).toFloat()
    }

    private fun melToHz(mel: Float): Float {
        return (700.0 * (10.0.pow(mel / 2595.0) - 1.0)).toFloat()
    }
}
