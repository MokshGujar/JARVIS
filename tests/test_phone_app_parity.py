from pathlib import Path

import config


ROOT = Path(__file__).resolve().parents[1]
BACKGROUND_SERVICE = ROOT / "android-companion" / "app" / "src" / "main" / "java" / "com" / "jarvis" / "companion" / "BackgroundVoiceService.kt"
PREFERENCES = ROOT / "android-companion" / "app" / "src" / "main" / "java" / "com" / "jarvis" / "companion" / "JarvisPreferences.kt"


def test_phone_listening_beep_config_default_disabled():
    assert config.JARVIS_PHONE_LISTENING_BEEP is False


def test_android_background_listening_cues_are_disabled_by_default():
    preferences = PREFERENCES.read_text(encoding="utf-8")
    service = BACKGROUND_SERVICE.read_text(encoding="utf-8")

    assert 'prefs.getBoolean(KEY_LISTENING_CUE_ENABLED, false)' in preferences
    assert "if (prefs.isListeningCueEnabled())" in service
    assert "warmJarvisCueCache()" in service
    assert "Jarvis cue suppressed by listening cue config" in service
    assert ".setSilent(true)" in service
    assert "setSound(null as Uri?, null)" in service
