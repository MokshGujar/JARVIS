import unittest
from unittest.mock import Mock, patch

from app.services.research_tools_service import ResearchToolsService


class ResearchToolsServiceTests(unittest.TestCase):
    def test_extract_youtube_video_id_from_common_urls(self):
        service = ResearchToolsService()

        self.assertEqual(
            service.extract_youtube_video_id("summarize https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(
            service.extract_youtube_video_id("transcript https://youtu.be/dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(
            service.extract_youtube_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )

    def test_get_youtube_transcript_uses_optional_loader(self):
        service = ResearchToolsService()

        with patch.object(
            service,
            "_load_transcript_segments",
            return_value=[{"text": "first line"}, {"text": "second line"}],
        ):
            result = service.get_youtube_transcript("get transcript https://youtu.be/dQw4w9WgXcQ")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "youtube_transcript")
        self.assertIn("first line second line", result["message"])

    def test_summarize_youtube_uses_current_groq_backend(self):
        groq = Mock()
        groq.get_response.return_value = "short summary"
        service = ResearchToolsService(groq_service=groq)

        with patch.object(
            service,
            "_load_transcript_segments",
            return_value=[{"text": "transcript content"}],
        ):
            result = service.summarize_youtube("summarize youtube https://youtu.be/dQw4w9WgXcQ")

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "short summary")
        groq.get_response.assert_called_once()

    def test_weather_and_flight_requests_use_realtime_service(self):
        realtime = Mock()
        realtime.get_response.return_value = "lookup answer"
        service = ResearchToolsService(realtime_service=realtime)

        weather = service.handle_request("weather in Mumbai tomorrow")
        flight = service.handle_request("find flights from Delhi to Bangalore next Friday")

        self.assertTrue(weather["success"])
        self.assertEqual(weather["action"], "weather")
        self.assertTrue(flight["success"])
        self.assertEqual(flight["action"], "flight_search")
        self.assertEqual(realtime.get_response.call_count, 2)

    def test_weather_fails_gracefully_without_realtime_service(self):
        service = ResearchToolsService()

        result = service.handle_request("weather in Mumbai tomorrow")

        self.assertFalse(result["success"])
        self.assertIn("realtime search is not configured", result["message"])


if __name__ == "__main__":
    unittest.main()
