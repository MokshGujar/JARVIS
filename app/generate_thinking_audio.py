import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = PROJECT_ROOT / "frontend" / "audio"

STARTER_PHRASES = [
    ("starter_1", "One moment please."),
    ("starter_2", "Sure, one moment."),
    ("starter_3", "Got it, hold on."),
    ("starter_4", "On it right now."),
    ("starter_5", "Alright, give me a sec."),
    ("starter_6", "Right, one moment."),
    ("starter_7", "Okay, hold on."),
    ("starter_8", "One second please."),
    ("starter_9", "Give me a moment."),
    ("starter_10", "Just a moment please."),
]

PHRASES = STARTER_PHRASES
VOICE = "en-GB-RyanNeural"
RATE = "+20%"


def _safe_print(message: str) -> None:
    """Print without failing on Windows terminals that use cp1252."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    safe_message = message.encode(encoding, errors="replace").decode(encoding)
    print(safe_message)


async def generate_one(name: str, text: str) -> bool:
    try:
        import edge_tts
    except ImportError:
        return False

    path = AUDIO_DIR / f"{name}.mp3"

    try:
        communicate = edge_tts.Communicate(text, VOICE, rate=RATE)
        await communicate.save(str(path))
        _safe_print(f"[OK] {name}.mp3")
        return True
    except Exception as e:
        _safe_print(f"[FAIL] {name}.mp3: {e}")
        return False


async def main():
    try:
        import edge_tts
    except ImportError:
        print("edge-tts not installed. Run: pip install edge-tts")
        return 1

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    for f in AUDIO_DIR.glob("followup_*.mp3"):
        try:
            f.unlink()
            _safe_print(f"[REMOVED] {f.name}")
        except OSError:
            pass

    _safe_print(f"Generating thinking audio in {AUDIO_DIR}...")
    success = 0

    for name, text in PHRASES:
        if await generate_one(name, text):
            success += 1

    _safe_print(f"Done: {success}/{len(PHRASES)} files.")
    return 0 if success == len(PHRASES) else 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
    except KeyboardInterrupt:
        exit_code = 130

    sys.exit(exit_code)
