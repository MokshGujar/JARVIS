This folder contains `speaker_verify.onnx`, the local Android ONNX speaker
embedding model used for protected Jarvis voice verification.

The bundled model is a minimal 16 kHz waveform embedding model. It is enough to
exercise the ONNX verification pipeline end to end. For stronger production
speaker verification, replace it with a trained speaker-embedding ONNX model
that accepts the same 4.5-second 16 kHz mono waveform input shape `[1, 72000]`
and returns a fixed float embedding.
