import logging
import re
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from config import YOUTUBE_TRANSCRIPTS_ENABLED


logger = logging.getLogger("J.A.R.V.I.S")


class ResearchToolsService:
    """Small, safe research utilities adapted from Mark-XXXV without Gemini coupling."""

    def __init__(self, groq_service=None, realtime_service=None):
        self.groq_service = groq_service
        self.realtime_service = realtime_service

    def looks_like_research_request(self, command: str) -> bool:
        text = " ".join((command or "").strip().lower().split())
        if not text:
            return False

        if "youtube" in text and any(word in text for word in ("summarize", "summary", "transcript", "caption")):
            return True
        if re.search(r"\b(weather|forecast|temperature)\b", text):
            return True
        if re.search(r"\b(flight|flights)\b", text) and re.search(r"\b(from|to|between)\b", text):
            return True
        return False

    def handle_request(self, command: str, chat_history: Optional[list[tuple]] = None) -> Dict[str, Any]:
        text = (command or "").strip()
        lowered = text.lower()

        if "youtube" in lowered and any(word in lowered for word in ("summarize", "summary", "transcript", "caption")):
            if "transcript" in lowered or "caption" in lowered:
                return self.get_youtube_transcript(text)
            return self.summarize_youtube(text, chat_history=chat_history)

        if re.search(r"\b(weather|forecast|temperature)\b", lowered):
            return self.answer_with_realtime(
                text,
                action="weather",
                fallback_message="Weather lookup is unavailable because realtime search is not configured.",
                chat_history=chat_history,
            )

        if re.search(r"\b(flight|flights)\b", lowered):
            return self.answer_with_realtime(
                text,
                action="flight_search",
                fallback_message="Flight lookup is unavailable because realtime search is not configured.",
                chat_history=chat_history,
            )

        return {
            "success": False,
            "action": "research",
            "message": "Tell me what you want me to look up.",
        }

    def get_youtube_transcript(self, command: str) -> Dict[str, Any]:
        if not YOUTUBE_TRANSCRIPTS_ENABLED:
            return {
                "success": False,
                "action": "youtube_transcript",
                "message": "YouTube transcripts are disabled in configuration.",
            }

        video_id = self.extract_youtube_video_id(command)
        if not video_id:
            return {
                "success": False,
                "action": "youtube_transcript",
                "message": "Send me a YouTube link or video ID to fetch the transcript.",
            }

        try:
            transcript = self._load_transcript_text(video_id)
        except ImportError:
            return {
                "success": False,
                "action": "youtube_transcript",
                "message": "YouTube transcript support is not installed. Install youtube-transcript-api and try again.",
            }
        except Exception as exc:
            logger.warning("[RESEARCH] YouTube transcript failed for %s: %s", video_id, exc)
            return {
                "success": False,
                "action": "youtube_transcript",
                "message": f"I could not fetch a transcript for that video: {exc}",
            }

        return {
            "success": True,
            "action": "youtube_transcript",
            "message": self._clip_text(transcript, 6000),
            "video_id": video_id,
        }

    def summarize_youtube(self, command: str, chat_history: Optional[list[tuple]] = None) -> Dict[str, Any]:
        transcript_result = self.get_youtube_transcript(command)
        if not transcript_result.get("success"):
            return transcript_result

        transcript = str(transcript_result.get("message", ""))
        video_id = str(transcript_result.get("video_id", ""))
        prompt = (
            "Summarize this YouTube transcript for the user. "
            "Give a concise overview, the key points, and any practical takeaways.\n\n"
            f"Video ID: {video_id}\n\nTranscript:\n{transcript[:12000]}"
        )

        try:
            if self.groq_service:
                summary = self.groq_service.get_response(prompt, chat_history=chat_history or [])
            else:
                summary = self._fallback_transcript_summary(transcript)
        except Exception as exc:
            logger.warning("[RESEARCH] YouTube summary failed for %s: %s", video_id, exc)
            summary = self._fallback_transcript_summary(transcript)

        return {
            "success": True,
            "action": "youtube_summary",
            "message": summary,
            "video_id": video_id,
        }

    def answer_with_realtime(
        self,
        command: str,
        *,
        action: str,
        fallback_message: str,
        chat_history: Optional[list[tuple]] = None,
    ) -> Dict[str, Any]:
        if not self.realtime_service:
            return {"success": False, "action": action, "message": fallback_message}

        try:
            answer = self.realtime_service.get_response(command, chat_history=chat_history or [])
            return {"success": True, "action": action, "message": answer}
        except Exception as exc:
            logger.warning("[RESEARCH] %s failed: %s", action, exc)
            return {"success": False, "action": action, "message": f"I could not complete that lookup: {exc}"}

    def extract_youtube_video_id(self, text: str) -> str:
        raw = (text or "").strip()
        url_match = re.search(r"https?://\S+|www\.\S+", raw, flags=re.IGNORECASE)
        candidate = url_match.group(0).rstrip(".,!?)]}") if url_match else raw.strip()
        if candidate.startswith("www."):
            candidate = "https://" + candidate

        if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
            return candidate

        try:
            parsed = urlparse(candidate)
        except Exception:
            parsed = None

        if parsed and parsed.netloc:
            host = parsed.netloc.lower()
            if host.endswith("youtu.be"):
                possible = parsed.path.strip("/").split("/")[0]
                return possible if re.fullmatch(r"[A-Za-z0-9_-]{11}", possible or "") else ""
            if "youtube.com" in host:
                query_id = parse_qs(parsed.query).get("v", [""])[0]
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", query_id or ""):
                    return query_id
                path_parts = [part for part in parsed.path.split("/") if part]
                for marker in ("shorts", "embed", "live"):
                    if marker in path_parts:
                        idx = path_parts.index(marker)
                        if idx + 1 < len(path_parts):
                            possible = path_parts[idx + 1]
                            return possible if re.fullmatch(r"[A-Za-z0-9_-]{11}", possible or "") else ""

        loose = re.search(r"\b[A-Za-z0-9_-]{11}\b", raw)
        return loose.group(0) if loose else ""

    def _load_transcript_text(self, video_id: str) -> str:
        segments = self._load_transcript_segments(video_id)
        parts = []
        for segment in segments:
            if isinstance(segment, dict):
                text = str(segment.get("text", "")).strip()
            else:
                text = str(getattr(segment, "text", "")).strip()
            if text:
                parts.append(text)
        if not parts:
            raise ValueError("Transcript is empty.")
        return " ".join(parts)

    def _load_transcript_segments(self, video_id: str):
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except Exception as exc:
            raise ImportError(str(exc)) from exc

        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            return YouTubeTranscriptApi.get_transcript(video_id)

        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id)
        if hasattr(fetched, "to_raw_data"):
            return fetched.to_raw_data()
        return fetched

    def _fallback_transcript_summary(self, transcript: str) -> str:
        clipped = self._clip_text(transcript, 1800)
        return f"I fetched the transcript, but summarization is unavailable. Transcript preview:\n{clipped}"

    def _clip_text(self, text: str, limit: int) -> str:
        cleaned = re.sub(r"\s+", " ", (text or "")).strip()
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[:limit].rstrip() + f"... truncated at {limit} characters."
