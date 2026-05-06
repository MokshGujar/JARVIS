from __future__ import annotations

import re
import time
from typing import Dict

from app.connectors.youtube_connector import YouTubeConnector

try:
    import requests
    from bs4 import BeautifulSoup
    REQUESTS_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover
    requests = None
    BeautifulSoup = None
    REQUESTS_IMPORT_ERROR = exc

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    TRANSCRIPT_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover
    YouTubeTranscriptApi = None
    TRANSCRIPT_IMPORT_ERROR = exc


class YouTubeToolsService:
    def __init__(self, groq_service=None, youtube_connector: YouTubeConnector | None = None) -> None:
        self.groq_service = groq_service
        self.youtube_connector = youtube_connector or YouTubeConnector()

    def play(self, query: str) -> Dict[str, str | bool]:
        query = (query or "").strip()
        if not query:
            return {"success": False, "action": "youtube_tools", "message": "Tell me what to play on YouTube."}
        return self.youtube_connector.play(query)

    def summarize(self, url: str) -> Dict[str, str | bool]:
        video_id = self._extract_video_id(url)
        if not video_id:
            return {"success": False, "action": "youtube_tools", "message": "I could not find a YouTube video ID in that URL."}
        transcript = self._get_transcript(video_id)
        if not transcript:
            return {"success": False, "action": "youtube_tools", "message": "I could not fetch a transcript for that video."}
        if not self.groq_service:
            return {"success": False, "action": "youtube_tools", "message": "Groq summary service is not available."}
        prompt = (
            "Summarize this YouTube transcript in one short overview and 3-5 key points. "
            "Be concise and useful.\n\n"
            f"{transcript[:60000]}"
        )
        try:
            summary = self.groq_service.get_response(prompt, chat_history=[])
            return {"success": True, "action": "youtube_tools", "message": summary}
        except Exception as exc:
            return {"success": False, "action": "youtube_tools", "message": f"Could not summarize the video: {exc}"}

    def info(self, url: str) -> Dict[str, str | bool]:
        video_id = self._extract_video_id(url)
        if not video_id:
            return {"success": False, "action": "youtube_tools", "message": "I could not find a YouTube video ID in that URL."}
        if requests is None:
            return {"success": False, "action": "youtube_tools", "message": f"YouTube info is unavailable. Import error: {REQUESTS_IMPORT_ERROR}"}
        try:
            page = requests.get(f"https://www.youtube.com/watch?v={video_id}", timeout=12, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(page.text, "html.parser")
            title = (soup.find("title").get_text(" ", strip=True) if soup.find("title") else "YouTube video").replace(" - YouTube", "")
            return {"success": True, "action": "youtube_tools", "message": f"{title}\nhttps://www.youtube.com/watch?v={video_id}"}
        except Exception as exc:
            return {"success": False, "action": "youtube_tools", "message": f"Could not fetch video info: {exc}"}

    def trending(self, region: str = "US") -> Dict[str, str | bool]:
        if requests is None:
            return {"success": False, "action": "youtube_tools", "message": f"YouTube trending is unavailable. Import error: {REQUESTS_IMPORT_ERROR}"}
        try:
            url = f"https://www.youtube.com/feed/trending?gl={(region or 'US').upper()}"
            page = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
            titles = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"', page.text)
            unique = []
            for title in titles:
                if title not in unique:
                    unique.append(title)
                if len(unique) >= 8:
                    break
            message = "\n".join(f"{i + 1}. {title}" for i, title in enumerate(unique)) or "No trending videos found."
            return {"success": True, "action": "youtube_tools", "message": message}
        except Exception as exc:
            return {"success": False, "action": "youtube_tools", "message": f"Could not fetch trending videos: {exc}"}

    def _extract_video_id(self, value: str) -> str | None:
        for pattern in (r"(?:v=|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})", r"^([A-Za-z0-9_-]{11})$"):
            match = re.search(pattern, value or "")
            if match:
                return match.group(1)
        return None

    def _get_transcript(self, video_id: str) -> str | None:
        if YouTubeTranscriptApi is None:
            return None
        try:
            fetched = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
            return " ".join(item.get("text", "") for item in fetched)
        except Exception:
            try:
                transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
                transcript = next(iter(transcripts))
                return " ".join(item.get("text", "") for item in transcript.fetch())
            except Exception:
                return None
