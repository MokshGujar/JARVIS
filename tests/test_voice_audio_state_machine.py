import unittest


class VoiceAudioStateMachineSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("frontend/script.js", encoding="utf-8") as handle:
            cls.script = handle.read()

    def test_voice_turn_manager_owns_turn_state_and_stale_checks(self):
        self.assertIn("class VoiceTurnManager", self.script)
        self.assertIn("this.activeTurnId", self.script)
        self.assertIn("beginTurn(turnId = null, state = 'chat_streaming')", self.script)
        self.assertIn("isCurrent(turnId)", self.script)
        self.assertIn("transition(state, turnId = this.activeTurnId)", self.script)
        self.assertIn("interruptedTurnIds", self.script)

    def test_single_voice_audio_queue_prevents_overlap(self):
        self.assertIn("class VoiceAudioQueue", self.script)
        self.assertIn("this.activeKind", self.script)
        self.assertIn("voiceAudioAllowOverlap", self.script)
        self.assertIn("if (this.activeKind && !voiceAudioAllowOverlap) this.cancelActive('new_audio');", self.script)
        self.assertIn("URL.revokeObjectURL(this.activeUrl)", self.script)

    def test_thinking_and_final_tts_are_once_per_turn(self):
        self.assertIn("this.thinkingPlayedTurns = new Set();", self.script)
        self.assertIn("this.finalPlayedTurns = new Set();", self.script)
        self.assertIn("thinkingAudioOnePerTurn && this.thinkingPlayedTurns.has", self.script)
        self.assertIn("if (this.finalPlayedTurns.has(turnId)) return;", self.script)

    def test_final_tts_is_end_only(self):
        self.assertIn("await voiceAudioQueue?.playFinalText(fullResponse, clientRequestId);", self.script)
        self.assertIn("Phase 4H uses end-only final TTS", self.script)
        self.assertNotIn("browserStreamSpeaker.pushText(chunkText, clientRequestId);", self.script)

    def test_empty_transcript_skips_every_downstream_voice_action(self):
        self.assertIn("[VOICE-STT] empty_transcript", self.script)
        self.assertIn("[VOICE-STT] skipped_chat reason=empty_transcript", self.script)
        self.assertIn("[VOICE-STT] skipped_thinking reason=empty_transcript", self.script)
        self.assertIn("voiceSendInFlight = false;", self.script)

    def test_interrupt_is_debounced_and_not_tts_end_driven(self):
        self.assertIn("VOICE_DO_NOT_INTERRUPT_ON_TTS_END", open("config.py", encoding="utf-8").read())
        self.assertIn("voiceInterruptDebounceMs", self.script)
        self.assertIn("this.interruptSentTurnIds.has(turnId)", self.script)
        self.assertIn("interruptCurrentResponse('barge_in')", self.script)
        self.assertIn("if (voiceAutoRestartMicAfterTts) maybeRestartListening();", self.script)

    def test_failed_tts_unlocks_state(self):
        self.assertIn("voiceTurnManager.transition('error_recovering', turnId)", self.script)
        self.assertIn("finally {", self.script)
        self.assertIn("voiceTurnManager.complete(turnId)", self.script)


if __name__ == "__main__":
    unittest.main()
