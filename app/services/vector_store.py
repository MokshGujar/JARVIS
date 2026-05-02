import json
import logging
import os
import time
from typing import List, Optional

from app.utils.atomic_io import write_json_atomic

from config import (
    LEARNING_DATA_DIR,
    CHATS_DATA_DIR,
    VECTOR_STORE_DIR,
    EMBEDDING_MODEL,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
)

logger = logging.getLogger("J.A.R.V.I.S")

INDEX_MANIFEST_VERSION = 1
INDEX_FAISS_FILE = "index.faiss"
INDEX_PICKLE_FILE = "index.pkl"
INDEX_MANIFEST_FILE = "index_manifest.json"
CHAT_HISTORY_CACHE_STABILIZATION_SECONDS = 60


class Document:
    def __init__(self, page_content: str, metadata: Optional[dict] = None):
        self.page_content = page_content
        self.metadata = metadata or {}


def _vector_retrieval_enabled() -> bool:
    raw = os.getenv("JARVIS_ENABLE_VECTOR_STORE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


class VectorStoreService:

    def __init__(self):
        self.available = False
        self.embeddings = None
        self.text_splitter = None
        self._faiss_cls = None
        self._document_cls = Document
        self._degraded_reason: Optional[str] = None
        self._degraded_warning_logged = False
        self.vector_store: Optional[object] = None
        self._retriever_cache: dict = {}

    def _degrade(self, reason: str) -> None:
        self.available = False
        self.embeddings = None
        self.text_splitter = None
        self._faiss_cls = None
        self.vector_store = None
        self._degraded_reason = reason
        if not self._degraded_warning_logged:
            logger.warning("[VECTOR] Retrieval degraded: %s", reason)
            self._degraded_warning_logged = True

    def status(self) -> dict:
        ready = bool(self.available and self.vector_store is not None)
        return {
            "available": ready,
            "degraded": not ready,
            "reason": self._degraded_reason,
            "enabled": _vector_retrieval_enabled(),
            "index_loaded": self.vector_store is not None,
        }

    def _load_vector_dependencies(self) -> bool:
        if not _vector_retrieval_enabled():
            self._degrade(
                "Vector retrieval disabled at startup. Set JARVIS_ENABLE_VECTOR_STORE=1 to enable optional ML retrieval."
            )
            return False

        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
            from langchain_huggingface import HuggingFaceEmbeddings
            from langchain_community.vectorstores import FAISS
            from langchain_core.documents import Document as LangchainDocument
        except BaseException as exc:  # pragma: no cover - environment resilience
            self._degrade(f"Optional vector dependencies unavailable: {exc}")
            return False

        try:
            self.embeddings = HuggingFaceEmbeddings(
                model_name=EMBEDDING_MODEL,
                model_kwargs={"device": "cpu", "local_files_only": True},
            )
            self.text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=CHUNK_SIZE,
                chunk_overlap=CHUNK_OVERLAP,
            )
        except BaseException as exc:  # pragma: no cover - environment resilience
            self._degrade(f"Embedding model unavailable: {exc}")
            return False

        self._faiss_cls = FAISS
        self._document_cls = LangchainDocument
        self.available = True
        self._degraded_reason = None
        return True

    def load_learning_data(self) -> List[Document]:
        documents = []

        for file_path in sorted(LEARNING_DATA_DIR.glob("*.txt")):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()

                if content:
                    documents.append(
                        self._document_cls(
                            page_content=content,
                            metadata={"source": str(file_path.name)},
                        )
                    )
                    logger.info(
                        "[VECTOR] Loaded learning data: %s (%d chars)",
                        file_path.name,
                        len(content),
                    )

            except Exception as e:
                logger.warning(
                    "Could not load learning data file %s: %s",
                    file_path,
                    e,
                )

        logger.info(
            "[VECTOR] Total learning data files loaded: %d",
            len(documents),
        )
        return documents

    def load_chat_history(self) -> List[Document]:
        documents = []

        for file_path in sorted(CHATS_DATA_DIR.glob("chat_*.json")):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    chat_data = json.load(f)

                messages = chat_data.get("messages", [])
                if not isinstance(messages, list):
                    logger.warning(
                        "[VECTOR] Skipping malformed chat history file %s: messages is not a list",
                        file_path.name,
                    )
                    continue

                parts = []

                for msg in messages:
                    if not isinstance(msg, dict):
                        continue

                    role = msg.get("role", "user")
                    content = msg.get("content", "")

                    if not isinstance(content, str):
                        content = str(content or "")

                    content = content.strip()
                    if not content:
                        continue

                    speaker = "User" if role == "user" else "Assistant"
                    parts.append(f"{speaker}: {content}")

                if not parts:
                    continue

                session_id = chat_data.get("session_id") or file_path.stem.removeprefix("chat_")
                documents.append(
                    self._document_cls(
                        page_content="\n".join(parts),
                        metadata={
                            "source": file_path.name,
                            "type": "chat_history",
                            "session_id": session_id,
                        },
                    )
                )
                logger.info(
                    "[VECTOR] Loaded chat history: %s (%d messages)",
                    file_path.name,
                    len(parts),
                )

            except Exception as e:
                logger.warning(
                    "Could not load chat history file %s: %s",
                    file_path,
                    e,
                )

        logger.info(
            "[VECTOR] Total chat history files loaded: %d",
            len(documents),
        )
        return documents

    def create_vector_store(self) -> object:
        if not self._load_vector_dependencies():
            return None

        manifest = self._build_cache_manifest()
        if self._load_cached_vector_store(manifest):
            return self.vector_store

        learning_docs = self.load_learning_data()
        chat_docs = self.load_chat_history()
        all_documents = learning_docs + chat_docs

        logger.info(
            "[VECTOR] Total documents to index: %d (learning: %d, chat: %d)",
            len(all_documents),
            len(learning_docs),
            len(chat_docs),
        )

        if not all_documents:
            self.vector_store = self._faiss_cls.from_texts(
                ["No data available yet."],
                self.embeddings,
            )
            logger.info("[VECTOR] No documents found, created placeholder index")
        else:
            chunks = self.text_splitter.split_documents(all_documents)
            logger.info(
                "[VECTOR] Split into %d chunks (chunk_size=%d, overlap=%d)",
                len(chunks),
                CHUNK_SIZE,
                CHUNK_OVERLAP,
            )

            self.vector_store = self._faiss_cls.from_documents(chunks, self.embeddings)
            logger.info(
                "[VECTOR] FAISS index built successfully with %d vectors",
                len(chunks),
            )

        self._retriever_cache.clear()
        self.save_vector_store(manifest)
        return self.vector_store

    def save_vector_store(self, manifest: Optional[dict] = None):
        if self.vector_store:
            try:
                self.vector_store.save_local(str(VECTOR_STORE_DIR))
                if manifest is not None:
                    write_json_atomic(
                        self._manifest_path(),
                        manifest,
                        indent=2,
                        ensure_ascii=False,
                    )
            except Exception as e:
                logger.error("Failed to save vector store to disk: %s", e)

    def _manifest_path(self):
        return VECTOR_STORE_DIR / INDEX_MANIFEST_FILE

    def _index_files_exist(self) -> bool:
        return (
            (VECTOR_STORE_DIR / INDEX_FAISS_FILE).exists()
            and (VECTOR_STORE_DIR / INDEX_PICKLE_FILE).exists()
        )

    def _iter_source_files(self, *, include_recent_chat_history: bool = True):
        for file_path in sorted(LEARNING_DATA_DIR.glob("*.txt")):
            yield "learning_data", file_path

        recent_chat_cutoff = time.time() - CHAT_HISTORY_CACHE_STABILIZATION_SECONDS
        for file_path in sorted(CHATS_DATA_DIR.glob("chat_*.json")):
            if not include_recent_chat_history:
                try:
                    if file_path.stat().st_mtime > recent_chat_cutoff:
                        continue
                except OSError:
                    continue
            yield "chat_history", file_path

    def _build_source_manifest(self, *, include_recent_chat_history: bool = True) -> dict:
        sources = []

        for source_type, file_path in self._iter_source_files(
            include_recent_chat_history=include_recent_chat_history
        ):
            try:
                stat = file_path.stat()
            except OSError as exc:
                logger.warning("[VECTOR] Could not stat source file %s: %s", file_path, exc)
                continue

            try:
                relative_path = str(file_path.relative_to(LEARNING_DATA_DIR.parent))
            except ValueError:
                relative_path = str(file_path.resolve())

            sources.append(
                {
                    "type": source_type,
                    "path": relative_path.replace("\\", "/"),
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )

        return {
            "version": INDEX_MANIFEST_VERSION,
            "embedding_model": EMBEDDING_MODEL,
            "chunk_size": CHUNK_SIZE,
            "chunk_overlap": CHUNK_OVERLAP,
            "sources": sources,
        }

    def _build_cache_manifest(self) -> dict:
        return self._build_source_manifest(include_recent_chat_history=False)

    def _load_saved_manifest(self) -> Optional[dict]:
        path = self._manifest_path()
        if not path.exists():
            return None

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("[VECTOR] Could not load index manifest %s: %s", path, exc)
            return None

    def _cache_is_valid(self, current_manifest: dict) -> bool:
        if not self._index_files_exist():
            return False

        saved_manifest = self._load_saved_manifest()
        return saved_manifest == current_manifest

    def _load_cached_vector_store(self, current_manifest: dict) -> bool:
        if not self._cache_is_valid(current_manifest):
            return False

        try:
            self.vector_store = self._faiss_cls.load_local(
                str(VECTOR_STORE_DIR),
                self.embeddings,
                allow_dangerous_deserialization=True,
            )
            self._retriever_cache.clear()
            logger.info(
                "[VECTOR] Loaded cached FAISS index from %s (%d sources unchanged)",
                VECTOR_STORE_DIR,
                len(current_manifest.get("sources", [])),
            )
            return True
        except TypeError:
            try:
                self.vector_store = self._faiss_cls.load_local(str(VECTOR_STORE_DIR), self.embeddings)
                self._retriever_cache.clear()
                logger.info("[VECTOR] Loaded cached FAISS index from %s", VECTOR_STORE_DIR)
                return True
            except Exception as exc:
                logger.warning("[VECTOR] Cached index load failed; rebuilding: %s", exc)
                return False
        except Exception as exc:
            logger.warning("[VECTOR] Cached index load failed; rebuilding: %s", exc)
            return False

    def get_retriever(self, k: int = 10):
        if not self.vector_store:
            reason = self._degraded_reason or "vector store has not been initialized"
            raise RuntimeError(f"Vector retrieval is unavailable: {reason}")

        if k not in self._retriever_cache:
            self._retriever_cache[k] = self.vector_store.as_retriever(
                search_kwargs={"k": k}
            )

        return self._retriever_cache[k]
