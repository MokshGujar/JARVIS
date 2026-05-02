from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.adapters.providers.nemo_parakeet_provider import NemoParakeetProvider
from app.core.config_loader import ConfigLoader


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/manual_test_nemo_parakeet_stt.py <audio-file>")
        print('Install note: pip install -U "nemo_toolkit[asr]" after installing a CUDA-compatible PyTorch build.')
        return 2

    audio_path = Path(sys.argv[1])
    if audio_path.suffix.lower() != ".wav":
        print("Parakeet manual smoke test expects WAV input. Convert the audio to .wav first or set PARAKEET_REQUIRE_WAV=false for experimentation.")
        return 2

    config = ConfigLoader().get_section("stt")
    provider = NemoParakeetProvider(config=config)
    print("Readiness:")
    print(json.dumps(provider.readiness(), indent=2))
    result = provider.transcribe_file(str(audio_path))
    if result.get("success"):
        print("Transcript:")
        print(result.get("text", ""))
        print("Metadata:")
        metadata_keys = (
            "provider",
            "model",
            "device",
            "language",
            "duration",
            "source",
            "raw_result_type",
            "post_processing_used",
            "domain_correction_used",
            "corrections_applied",
        )
        print(json.dumps({key: result.get(key) for key in metadata_keys if key in result}, indent=2))
        return 0
    print("Error:")
    print(json.dumps({k: v for k, v in result.items() if k not in {"segments", "timestamps"}}, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
