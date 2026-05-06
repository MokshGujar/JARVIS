import unittest


class BrowserStreamingUxSourceTests(unittest.TestCase):
    def test_streaming_client_uses_request_id_and_stale_guard(self):
        with open("frontend/script.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("function buildClientRequestId()", script)
        self.assertIn("let activeClientRequestId = null;", script)
        self.assertIn("isCurrentStreamPayload(data, clientRequestId)", script)
        self.assertIn("client_request_id: clientRequestId", script)
        self.assertIn("activeClientRequestId === expectedRequestId", script)

    def test_interrupt_clears_tts_and_stream_state(self):
        with open("frontend/script.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("function interruptCurrentResponse(reason = 'user_interrupt')", script)
        self.assertIn("activeStreamController?.abort()", script)
        self.assertIn("cancelThinkingSound()", script)
        self.assertIn("stopBrowserSpeech()", script)
        self.assertIn("browserStreamSpeaker.reset()", script)
        self.assertIn("ttsPlayer.stop()", script)
        self.assertIn("document.querySelectorAll('.stream-cursor').forEach(node => node.remove())", script)
        self.assertIn("function handleVoiceBargeInSpeechStart()", script)
        self.assertIn("fetch(`${API}/chat/interrupt`", script)

    def test_streamed_tts_uses_edge_tts_queue_and_never_streams_raw_audio_chunks(self):
        with open("frontend/script.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("class VoiceAudioQueue", script)
        self.assertIn("async playFinalText(text, turnId)", script)
        self.assertIn("fetch(`${API}/tts`", script)
        self.assertIn("body: JSON.stringify({ text: content, turn_id: turnId, request_id: turnId })", script)
        self.assertIn("tts: false", script)
        self.assertIn("await voiceAudioQueue?.playFinalText(fullResponse, clientRequestId);", script)
        self.assertIn("Phase 4H uses end-only final TTS", script)
        self.assertNotIn("browserStreamSpeaker.pushText(chunkText, clientRequestId);", script)
        self.assertNotIn("ttsPlayer.enqueue(data.audio", script)

    def test_thinking_audio_starts_before_stream_and_waits_before_final_tts(self):
        with open("frontend/script.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("class VoiceAudioQueue", script)
        self.assertIn("scheduleThinkingSound(data.activity.ack, clientRequestId);", script)
        self.assertIn("function scheduleThinkingSound(text, requestId = null)", script)
        self.assertIn("fetch(`${API}/tts/thinking`", script)
        self.assertIn("text_hash: ack?.text_hash || ''", script)
        self.assertIn("isThinkingAckCurrent(ack, turnId)", script)
        self.assertIn("responseHash !== (ack?.text_hash || '')", script)
        self.assertIn("this.thinkingPlayedTurns = new Set();", script)
        self.assertIn("this.finalPlayedTurns = new Set();", script)
        self.assertIn("if (this.activeKind === 'thinking' && this.activeTurnId === turnId", script)
        self.assertIn("await this.activePromise.catch(() => {});", script)

    def test_backend_stt_barge_in_listens_during_assistant_audio(self):
        with open("frontend/script.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("function shouldAllowBackendBargeIn()", script)
        self.assertIn("bargeInListeningMode && shouldAllowBackendBargeIn()", script)
        self.assertIn("handleVoiceBargeInSpeechStart();", script)
        self.assertIn("startListening({ bargeIn });", script)
        self.assertIn("maybeRestartListening(120);", script)

    def test_tts_player_stop_clears_audio_queue_and_state(self):
        with open("frontend/script.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("this.audio.pause()", script)
        self.assertIn("this.audio.removeAttribute('src')", script)
        self.assertIn("this.audio.load()", script)
        self.assertIn("this.queue = []", script)
        self.assertIn("this.audio.onended = null", script)
        self.assertIn("this.audio.onerror = null", script)

    def test_actions_execute_immediately_without_in_app_face_step_up(self):
        with open("frontend/script.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("handleServerActions(data.actions);", script)
        self.assertIn("addImageResultMessage('Image ready.'", script)
        self.assertIn("addContentResultMessage('Content ready.'", script)
        self.assertIn("window.open(url, '_blank', 'noopener')", script)
        self.assertIn("That action needs permission before it can run.", script)
        self.assertNotIn("await performFaceAuthorization(data.actions.auth, clientRequestId);", script)
        self.assertNotIn("/face/verify", script)
        self.assertNotIn("/auth/step-up/start", script)
        self.assertNotIn("face_session_id:", script)
        self.assertIn("try { controller.abort(); } catch (_) {}", script)
        self.assertIn("invalidateActiveStepUp()", script)

    def test_launcher_bootstrap_is_entry_gate_only(self):
        with open("frontend/script.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("/auth/launcher/exchange-bootstrap", script)
        self.assertIn("jarvis_entry_gate_session_id", script)
        self.assertIn("entryGateSessionId = payload.face_session_id;", script)
        self.assertNotIn("jarvis_face_session_id", script)

    def test_canonical_action_list_contract_is_handled(self):
        with open("frontend/script.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("Array.isArray(actions)", script)
        self.assertIn("type === 'show_status'", script)
        self.assertIn("type === 'show_task_result'", script)
        self.assertIn("type === 'download_file'", script)

    def test_voice_input_fails_loudly_when_browser_speech_is_unavailable(self):
        with open("frontend/script.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("Voice input requires Chrome or Edge.", script)
        self.assertIn("Microphone could not start. Allow mic access and use Chrome or Edge.", script)

    def test_voice_input_loads_runtime_stt_timing_and_uses_longer_send_window(self):
        with open("frontend/script.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("async function fetchRuntimeVoiceConfig()", script)
        self.assertIn("sttCaptureMode =", script)
        self.assertIn("function isBackendSttCaptureMode()", script)
        self.assertIn("speechSendDelayMs = Math.max(700", script)
        self.assertIn("sttMaxRecordSeconds", script)
        self.assertIn("sttSpeechPaddingMs", script)
        self.assertIn("voiceMaxRecordTimeout = setTimeout", script)

    def test_backend_stt_mode_transcribes_before_chat_send(self):
        with open("frontend/script.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("fetch(`${API}/stt/transcribe`", script)
        self.assertIn("const payload = await transcribeCapturedVoiceAudio(voiceAudioBase64);", script)
        self.assertIn("Promise.resolve(sendMessage(transcript, {", script)
        self.assertIn("if (isBackendSttCaptureMode()) {", script)

    def test_empty_backend_stt_transcript_does_not_send_chat_or_thinking_audio(self):
        with open("frontend/script.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("function handleEmptyTranscript()", script)
        self.assertIn("cancelThinkingSound();", script)
        self.assertIn("['empty_transcript', 'empty_audio', 'no_speech', 'no_speech_detected'].includes", script)
        self.assertIn("handleEmptyTranscript();", script)
        self.assertIn("return false;", script)

    def test_session_id_persists_across_reload_until_new_chat(self):
        with open("frontend/script.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("const CHAT_SESSION_STORAGE_KEY = 'jarvis_chat_session_id';", script)
        self.assertIn("let sessionId = localStorage.getItem(CHAT_SESSION_STORAGE_KEY) || null;", script)
        self.assertIn("function setChatSessionId(nextSessionId)", script)
        self.assertIn("localStorage.setItem(CHAT_SESSION_STORAGE_KEY, sessionId);", script)
        self.assertIn("localStorage.removeItem(CHAT_SESSION_STORAGE_KEY);", script)
        self.assertIn("if (data.session_id) setChatSessionId(data.session_id);", script)
        self.assertIn("setChatSessionId(null);", script)

    def test_smart_thinking_audio_skips_fast_semantic_and_clarification(self):
        with open("frontend/script.js", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("thinkingAudioMode = String(thinkingAudio.mode", script)
        self.assertIn("thinkingAudioSkipForFastSemantic = thinkingAudio.skip_for_fast_semantic !== false;", script)
        self.assertIn("thinkingAudioSkipForEmptyTranscript = thinkingAudio.skip_for_empty_transcript !== false;", script)
        self.assertIn("thinkingAudioSkipForClarification = thinkingAudio.skip_for_clarification !== false;", script)
        self.assertIn("thinkingAudioSkipForConfirmation = thinkingAudio.skip_for_confirmation !== false;", script)
        self.assertIn("thinkingAudioSkipForGreeting = thinkingAudio.skip_for_greeting !== false;", script)
        self.assertIn("function shouldSkipThinkingAudioForText(text)", script)
        self.assertIn("port waldenet", script)
        self.assertIn("thinkingAudioMinDelayMs", script)


if __name__ == "__main__":
    unittest.main()
