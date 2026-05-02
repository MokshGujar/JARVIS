import unittest

from config import (
    FACE_IDENTITY_MAX_STORED_SAMPLES,
    FACE_IDENTITY_PREFERRED_SAMPLES,
    FACE_IDENTITY_REQUIRED_SAMPLES,
)
from app.services.face_enrollment_service import FaceEnrollmentService


class FakeProfileStore:
    def __init__(self):
        self.saved = None

    def save_profile(self, profile):
        self.saved = profile


class FakeFaceIdentityService:
    profile_id = "owner-default"
    user_name = "Moksh"

    def __init__(self):
        self.backend = type("Backend", (), {"model_name": "fake-backend"})()
        self.profile_store = FakeProfileStore()
        self.deleted = 0

    def delete_profile(self):
        self.deleted += 1


def embedding(index):
    values = [1.0] + [0.0] * 40
    values[(index % 40) + 1] = 0.12
    return values


def accepted_result(vector):
    return {
        "accepted": True,
        "reason": "accepted",
        "embedding": vector,
        "quality": {"passed": True, "face_count": 1, "reason": "ok"},
        "liveness": {"is_live": True, "confidence": 0.95, "reason": "live", "checks": {}},
    }


def rejected_result(reason, *, quality=None, liveness=None):
    return {
        "accepted": False,
        "reason": reason,
        "quality": quality or {"passed": False, "face_count": 1, "reason": reason},
        "liveness": liveness or {"is_live": False, "confidence": 0.0, "reason": reason, "checks": {}},
    }


class FaceEnrollmentServiceTests(unittest.TestCase):
    def make_service(self):
        identity = FakeFaceIdentityService()
        return FaceEnrollmentService(identity), identity

    def queue_results(self, service, results):
        service._extract_batch_frame_results = lambda _frames: list(results)

    def start_session(self, service):
        started = service.start()
        return started, started["enrollment_session_id"]

    def test_config_uses_fast_enrollment_sample_counts(self):
        self.assertEqual(FACE_IDENTITY_REQUIRED_SAMPLES, 20)
        self.assertEqual(FACE_IDENTITY_PREFERRED_SAMPLES, 20)
        self.assertEqual(FACE_IDENTITY_MAX_STORED_SAMPLES, 25)

    def test_start_response_exposes_required_preferred_and_max_counts(self):
        service, _identity = self.make_service()

        started = service.start()

        self.assertEqual(started["required_samples"], 20)
        self.assertEqual(started["preferred_samples"], 20)
        self.assertEqual(started["max_stored_samples"], 25)

    def test_batch_rejects_low_quality_frames(self):
        service, _identity = self.make_service()
        _started, session_id = self.start_session(service)
        self.queue_results(service, [rejected_result("too_dark")])

        payload = service.add_batch(session_id, ["frame"])

        self.assertEqual(payload["accepted_count"], 0)
        self.assertEqual(payload["quality_failed_count"], 1)
        self.assertEqual(payload["accepted_samples"], 0)
        self.assertEqual(payload["guidance"], "Lighting is too low. Move closer to a light source.")
        self.assertEqual(payload["lighting"], "Too dark")
        self.assertEqual(payload["reason_counts"]["too_dark"], 1)

    def test_batch_rejects_liveness_failed_frames(self):
        service, _identity = self.make_service()
        _started, session_id = self.start_session(service)
        self.queue_results(service, [rejected_result("liveness_frames_identical_or_static")])

        payload = service.add_batch(session_id, ["frame"])

        self.assertEqual(payload["accepted_count"], 0)
        self.assertEqual(payload["rejected_count"], 1)
        self.assertEqual(payload["liveness_failed_count"], 1)
        self.assertEqual(payload["guidance"], "Move naturally.")

    def test_batch_rejects_duplicate_embeddings(self):
        service, _identity = self.make_service()
        _started, session_id = self.start_session(service)
        same = embedding(0)
        self.queue_results(service, [accepted_result(same), accepted_result(same)])

        payload = service.add_batch(session_id, ["frame-a", "frame-b"])

        self.assertEqual(payload["accepted_count"], 1)
        self.assertEqual(payload["duplicate_count"], 1)
        self.assertEqual(payload["accepted_samples"], 1)
        self.assertEqual(payload["duplicate_rejection_count"], 1)
        self.assertIn(payload["diversity"], {"Low", "Needs angle change"})

    def test_batch_rejects_inconsistent_embedding_after_centroid_exists(self):
        service, _identity = self.make_service()
        _started, session_id = self.start_session(service)
        initial = [accepted_result(embedding(index)) for index in range(6)]
        self.queue_results(service, initial)
        service.add_batch(session_id, ["frame"] * 6)
        outlier = [0.0, 1.0] + [0.0] * 40
        self.queue_results(service, [accepted_result(outlier)])

        payload = service.add_batch(session_id, ["outlier"])

        self.assertEqual(payload["accepted_count"], 0)
        self.assertEqual(payload["inconsistent_count"], 1)
        self.assertEqual(payload["accepted_samples"], 6)
        self.assertEqual(payload["inconsistent_rejection_count"], 1)
        self.assertEqual(payload["guidance"], "Keep same face, avoid extreme angles.")

    def test_enrollment_can_complete_after_minimum_accepted_samples(self):
        service, identity = self.make_service()
        _started, session_id = self.start_session(service)
        self.queue_results(service, [accepted_result(embedding(index)) for index in range(20)])
        service.add_batch(session_id, ["frame"] * 20)

        payload = service.complete(session_id)

        self.assertTrue(payload["enrolled"])
        self.assertTrue(identity.profile_store.saved["is_active"])
        self.assertEqual(payload["accepted_samples"], 20)
        self.assertNotIn("face_session_id", payload)
        self.assertNotIn("launcher_bootstrap_token", payload)

    def test_batch_auto_completes_after_preferred_accepted_samples(self):
        service, _identity = self.make_service()
        _started, session_id = self.start_session(service)
        self.queue_results(service, [accepted_result(embedding(index)) for index in range(20)])

        payload = service.add_batch(session_id, ["frame"] * 20)

        self.assertTrue(payload["can_complete"])
        self.assertTrue(payload["auto_complete"])
        self.assertEqual(payload["accepted_samples"], 20)

    def test_max_stored_samples_caps_accepted_embeddings(self):
        service, _identity = self.make_service()
        _started, session_id = self.start_session(service)
        self.queue_results(service, [accepted_result(embedding(index)) for index in range(30)])

        payload = service.add_batch(session_id, ["frame"] * 30)

        self.assertEqual(payload["accepted_samples"], 25)
        self.assertEqual(payload["accepted_count"], 25)
        self.assertEqual(payload["rejected_count"], 5)

    def test_sample_endpoint_compatibility_uses_batch_logic(self):
        service, _identity = self.make_service()
        _started, session_id = self.start_session(service)
        self.queue_results(service, [accepted_result(embedding(0))])

        payload = service.add_sample(session_id, ["frame"])

        self.assertTrue(payload["accepted"])
        self.assertEqual(payload["accepted_samples"], 1)
        self.assertEqual(payload["required_samples"], 20)


if __name__ == "__main__":
    unittest.main()
