package com.jarvis.companion

import kotlin.math.max
import kotlin.math.min

class ContactMatcher {
    fun rank(query: String, contacts: List<ContactCandidate>): List<ContactCandidate> {
        val normalizedQuery = normalizeName(query)
        if (normalizedQuery.isBlank()) return emptyList()

        return contacts.mapNotNull { contact ->
            val names = listOf(contact.normalizedName) +
                contact.aliases.map { normalizeName(it) } +
                derivedAliases(contact.displayName).map { normalizeName(it) }
            var bestScore = 0f
            var bestReason = ""

            names.forEach { name ->
                val scored = scoreName(normalizedQuery, name)
                if (scored.first > bestScore) {
                    bestScore = scored.first
                    bestReason = scored.second
                }
            }

            if (bestScore <= 0f) {
                null
            } else {
                val reasons = mutableListOf(bestReason)
                var boost = 0f
                if (contact.favorite) {
                    boost += 0.03f
                    reasons += "favorite"
                }
                if (contact.timesContacted >= 5) {
                    boost += 0.04f
                    reasons += "frequent"
                }
                if (contact.lastContacted > 0L && System.currentTimeMillis() - contact.lastContacted < RECENT_WINDOW_MS) {
                    boost += 0.04f
                    reasons += "recent"
                }

                contact.copy(
                    score = min(1f, bestScore + boost),
                    reasons = reasons.filter { it.isNotBlank() },
                )
            }
        }.sortedByDescending { it.score }
    }

    fun isAutoCallable(query: String, candidates: List<ContactCandidate>): Boolean {
        if (candidates.isEmpty()) return false
        val compactQuery = normalizeName(query).replace(" ", "")
        if (compactQuery.length <= 3) return false

        val top = candidates[0]
        val second = candidates.getOrNull(1)
        val gap = if (second == null) 1f else top.score - second.score
        return top.score >= HIGH_CONFIDENCE && gap >= MIN_AUTO_CALL_GAP
    }

    fun normalizeName(value: String): String {
        return value
            .lowercase()
            .replace(Regex("[^\\p{L}\\p{N}]"), " ")
            .replace(Regex("\\s+"), " ")
            .trim()
    }

    private fun scoreName(query: String, name: String): Pair<Float, String> {
        if (query.isBlank() || name.isBlank()) return 0f to ""
        if (query == name) return 1f to "exact"
        if (aliasScore(query, name) > 0f) return aliasScore(query, name) to "alias"
        if (name.startsWith(query)) return (if (query.length >= 4) 0.94f else 0.72f) to "prefix"
        if (query.startsWith(name) && name.length >= 4) return 0.82f to "reverse_prefix"

        val fuzzy = levenshteinSimilarity(query, name) * 0.9f
        val phonetic = if (phoneticKey(query) == phoneticKey(name)) 0.86f else 0f
        return if (phonetic >= fuzzy && phonetic > 0f) {
            phonetic to "phonetic"
        } else {
            fuzzy to "fuzzy"
        }
    }

    private fun aliasScore(query: String, name: String): Float {
        val families = listOf(
            setOf("mom", "mother", "maa", "mummy", "mumma"),
            setOf("dad", "father", "papa", "daddy"),
            setOf("bro", "brother", "bhai"),
            setOf("sis", "sister", "didi"),
        )
        return if (families.any { query in it && name in it }) 0.92f else 0f
    }

    private fun derivedAliases(displayName: String): List<String> {
        val normalized = normalizeName(displayName)
        val aliases = mutableListOf<String>()
        val words = normalized.split(" ").filter { it.isNotBlank() }
        if (words.size > 1) {
            aliases += words.first()
            aliases += words.last()
        }
        when {
            normalized.contains("mother") || normalized.contains("mummy") -> aliases += listOf("mom", "maa", "mumma")
            normalized.contains("father") || normalized.contains("papa") -> aliases += listOf("dad", "daddy")
            normalized.contains("brother") -> aliases += listOf("bro", "bhai")
            normalized.contains("sister") -> aliases += listOf("sis", "didi")
        }
        return aliases.distinct()
    }

    private fun phoneticKey(value: String): String {
        return normalizeName(value)
            .replace(" ", "")
            .replace(Regex("(sh|ch|ck|kh)"), "k")
            .replace(Regex("[aeiou]+"), "")
            .replace(Regex("(.)\\1+"), "$1")
            .take(8)
    }

    private fun levenshteinSimilarity(a: String, b: String): Float {
        val distance = levenshtein(a, b)
        val width = max(a.length, b.length).coerceAtLeast(1)
        return (1f - distance.toFloat() / width).coerceIn(0f, 1f)
    }

    private fun levenshtein(a: String, b: String): Int {
        if (a == b) return 0
        if (a.isEmpty()) return b.length
        if (b.isEmpty()) return a.length

        var previous = IntArray(b.length + 1) { it }
        var current = IntArray(b.length + 1)
        for (i in a.indices) {
            current[0] = i + 1
            for (j in b.indices) {
                val cost = if (a[i] == b[j]) 0 else 1
                current[j + 1] = minOf(
                    current[j] + 1,
                    previous[j + 1] + 1,
                    previous[j] + cost,
                )
            }
            val temp = previous
            previous = current
            current = temp
        }
        return previous[b.length]
    }

    companion object {
        const val HIGH_CONFIDENCE = 0.88f
        const val MEDIUM_CONFIDENCE = 0.65f
        const val MIN_AUTO_CALL_GAP = 0.08f
        private const val RECENT_WINDOW_MS = 30L * 24L * 60L * 60L * 1000L
    }
}
