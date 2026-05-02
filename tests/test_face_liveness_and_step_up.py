import time
import unittest
from dataclasses import dataclass

import numpy as np

from app.adapters.face.face_detector import FaceDetection
from app.adapters.face.face_liveness import PassiveMultiFrameLiveness
from app.adapters.face.face_quality import FaceQualityResult
from app.services.command_risk_service import CommandRiskService
from app.services.face_identity_service import AttemptLimiter, FaceIdentityService
from app.services.step_up_auth_service import StepUpAuthService
from app.core.face_profile_store import FaceProfileStore


@dataclass
class FakeFrame:
    gray: np.ndarray


def frame(value: int) -> FakeFrame:
    return FakeFrame(np.full((100, 100), value, dtype=np.uint8))


def face_at(x: float, y: float) -> FaceDetection:
    return FaceDetection((x, y, x + 100, y + 100), 0.99)


def quality_ok() -> FaceQualityResult:
    return FaceQualityResult(True, "ok", 1, 0.99, 100, 200, 120)


class PassiveLivenessTests(unittest.TestCase):
    def test_static_identical_frames_fail_liveness(self):
        frames = [frame(80) for _ in range(5)]
        detections = [[face_at(10, 10)] for _ in frames]
        result = PassiveMultiFrameLiveness().evaluate(frames, detections, [quality_ok() for _ in frames])
        self.assertFalse(result.is_live)
        self.assertEqual(result.reason, "frames_identical_or_static")

    def test_natural_small_movement_passes_liveness(self):
        frames = [frame(80 + i * 5) for i in range(5)]
        detections = [[face_at(10 + i, 10)] for i in range(5)]
        result = PassiveMultiFrameLiveness().evaluate(frames, detections, [quality_ok() for _ in frames])
        self.assertTrue(result.is_live)

    def test_excessive_movement_fails_liveness(self):
        frames = [frame(80 + i * 5) for i in range(5)]
        detections = [[face_at(10 + i * 80, 10)] for i in range(5)]
        result = PassiveMultiFrameLiveness().evaluate(frames, detections, [quality_ok() for _ in frames])
        self.assertFalse(result.is_live)
        self.assertIn(result.reason, {"excessive_motion", "face_tracking_unstable"})

    def test_quality_failure_blocks_liveness(self):
        frames = [frame(80 + i * 5) for i in range(5)]
        qualities = [quality_ok() for _ in frames]
        qualities[2] = FaceQualityResult(False, "too_blurry", 1, 0.99, 100, 10, 120)
        detections = [[face_at(10 + i, 10)] for i in range(5)]
        result = PassiveMultiFrameLiveness().evaluate(frames, detections, qualities)
        self.assertFalse(result.is_live)
        self.assertEqual(result.reason, "too_blurry")


class FaceIdentityEnrollmentPolicyTests(unittest.TestCase):
    def test_profile_below_current_required_sample_count_is_not_enrolled(self):
        from pathlib import Path

        class Backend:
            model_name = "fake"
            embedding_dim = 2

            def status(self):
                return {"available": True, "backend": "fake", "model_name": "fake", "embedding_dim": 2}

        data_dir = Path("tests") / "_tmp" / "face_profile_required_samples"
        data_dir.mkdir(parents=True, exist_ok=True)
        store = FaceProfileStore(data_dir)
        store.save_profile(
            {
                "profile_id": "owner-default",
                "user_name": "Moksh",
                "is_active": True,
                "centroid_embedding": [1.0, 0.0],
                "accepted_samples": 12,
                "required_samples": 12,
            }
        )
        face = FaceIdentityService(backend=Backend(), profile_store=store)

        self.assertFalse(face.status()["profile_enrolled"])
        self.assertEqual(face.status()["required_samples"], 20)
        payload = face.verify_frames(["frame"], client_id="policy-test", require_liveness=False)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["reason"], "not_enrolled")


class FakeFaceIdentityService:
    def __init__(self):
        self.valid_sessions = {"face-session"}
        self.status = "verified"
        self.reason = "verified_match"

    def validate_session(self, session_id):
        return session_id in self.valid_sessions

    def verify_frames(self, frames, **kwargs):
        if self.status != "verified":
            return {
                "status": self.status,
                "reason": self.reason,
                "cosine_similarity": 0.2,
                "liveness": {"is_live": False, "confidence": 0.0, "reason": self.reason, "checks": {}},
            }
        return {
            "status": "verified",
            "reason": "verified_match",
            "cosine_similarity": 0.91,
            "liveness": {"is_live": True, "confidence": 0.9, "reason": "live", "checks": {}},
        }


class StepUpAuthTests(unittest.TestCase):
    def test_high_risk_command_requires_and_consumes_step_up_token_once(self):
        risk_service = CommandRiskService()
        face = FakeFaceIdentityService()
        service = StepUpAuthService(face_identity_service=face, command_risk_service=risk_service, token_ttl_seconds=30)
        start = service.start(face_session_id="face-session", command_text="delete file notes.txt", command_action="delete_file")
        self.assertTrue(start["step_up_required"])
        verified = service.verify(
            challenge_id=start["challenge_id"],
            face_session_id="face-session",
            command_text="delete file notes.txt",
            command_action="delete_file",
            frames=["frame"],
        )
        token = verified["step_up_token"]
        risk = risk_service.classify("delete file notes.txt", command_action="delete_file")
        self.assertEqual(service.consume(token=token, face_session_id="face-session", risk=risk), (True, "ok"))
        self.assertEqual(service.consume(token=token, face_session_id="face-session", risk=risk), (False, "step_up_token_reused"))

    def test_rejected_liveness_does_not_issue_token(self):
        risk_service = CommandRiskService()
        face = FakeFaceIdentityService()
        face.status = "rejected"
        face.reason = "liveness_frames_identical_or_static"
        service = StepUpAuthService(face_identity_service=face, command_risk_service=risk_service)
        start = service.start(face_session_id="face-session", command_text="delete file notes.txt", command_action="delete_file")
        verified = service.verify(
            challenge_id=start["challenge_id"],
            face_session_id="face-session",
            command_text="delete file notes.txt",
            command_action="delete_file",
            frames=["frame"],
        )
        self.assertFalse(verified["token_issued"])
        self.assertEqual(verified["step_up_decision"], "rejected")

    def test_whatsapp_call_does_not_start_step_up_challenge(self):
        risk_service = CommandRiskService()
        face = FakeFaceIdentityService()
        face.status = "rejected"
        face.reason = "liveness_frames_identical_or_static"
        service = StepUpAuthService(face_identity_service=face, command_risk_service=risk_service)
        command = "voice call Suhani on whatsapp"
        start = service.start(face_session_id="face-session", command_text=command, command_action="automation")

        self.assertFalse(start["step_up_required"])
        self.assertNotIn("challenge_id", start)

    def test_expired_token_is_rejected(self):
        risk_service = CommandRiskService()
        face = FakeFaceIdentityService()
        service = StepUpAuthService(face_identity_service=face, command_risk_service=risk_service, token_ttl_seconds=1)
        start = service.start(face_session_id="face-session", command_text="delete file a.txt", command_action="delete_file")
        verified = service.verify(
            challenge_id=start["challenge_id"],
            face_session_id="face-session",
            command_text="delete file a.txt",
            command_action="delete_file",
            frames=["frame"],
        )
        token = verified["step_up_token"]
        service._tokens[token]["expires_at"] = time.time() - 1
        risk = risk_service.classify("delete file a.txt", command_action="delete_file")
        self.assertEqual(service.consume(token=token, face_session_id="face-session", risk=risk), (False, "step_up_token_expired"))

    def test_rate_limiter_locks_after_three_failures(self):
        limiter = AttemptLimiter(max_per_minute=10, lock_failure_count=3, lock_seconds=45)
        for _ in range(3):
            self.assertEqual(limiter.check("client")[0], True)
            limiter.record_failure("client")
        allowed, reason, retry_after = limiter.check("client")
        self.assertFalse(allowed)
        self.assertEqual(reason, "locked")
        self.assertGreater(retry_after, 0)

    def test_profile_delete_invalidates_sessions_and_step_up_tokens(self):
        from pathlib import Path

        class Backend:
            model_name = "fake"
            embedding_dim = 2

            def status(self):
                return {"available": True, "backend": "fake", "model_name": "fake", "embedding_dim": 2}

        data_dir = Path("tests") / "_tmp" / "face_profile_delete"
        data_dir.mkdir(parents=True, exist_ok=True)
        store = FaceProfileStore(data_dir)
        face = FaceIdentityService(backend=Backend(), profile_store=store)
        risk_service = CommandRiskService()
        step_up = StepUpAuthService(face_identity_service=face, command_risk_service=risk_service)
        face.register_profile_delete_callback(step_up.invalidate_all)
        session_id = face._issue_session({"profile_id": "owner-default"}, 0.9)
        risk = risk_service.classify("delete file notes.txt", command_action="delete_file")
        step_up._tokens["token"] = {
            "face_session_id": session_id,
            "command_hash": risk.command_hash(),
            "expires_at": time.time() + 30,
            "consumed": False,
        }
        face.delete_profile()
        self.assertFalse(face.validate_session(session_id))
        self.assertEqual(step_up.consume(token="token", face_session_id=session_id, risk=risk), (False, "step_up_token_not_found"))


if __name__ == "__main__":
    unittest.main()
