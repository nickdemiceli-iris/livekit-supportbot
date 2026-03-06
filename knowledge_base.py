from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

FALLBACK_MESSAGE = (
    "I apologize, but I do not have the answer to that question. "
    "I can note this down for one of our representatives to get back to you."
)

_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "so",
    "that",
    "the",
    "to",
    "we",
    "what",
    "when",
    "where",
    "who",
    "why",
    "with",
    "you",
    "your",
}


@dataclass(frozen=True)
class KnowledgeBaseEntry:
    id: str
    question: str
    answer: str
    keywords: list[str]


@dataclass(frozen=True)
class LookupResult:
    found: bool
    answer: str
    matched_article_id: str | None = None
    matched_question: str | None = None
    confidence: float | None = None
    noted_for_follow_up: bool = False


def _tokenize(text: str) -> set[str]:
    tokens = {token for token in re.findall(r"[a-z0-9']+", text.lower()) if token not in _STOP_WORDS}
    return {token for token in tokens if len(token) > 2}


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


class KnowledgeBase:
    def __init__(
        self,
        entries: list[KnowledgeBaseEntry],
        fallback_message: str = FALLBACK_MESSAGE,
        min_confidence: float = 0.32,
        unanswered_log_path: Path | None = None,
    ) -> None:
        self.entries = entries
        self.fallback_message = fallback_message
        self.min_confidence = min_confidence
        self.unanswered_log_path = unanswered_log_path

    @classmethod
    def from_json(
        cls,
        path: Path,
        fallback_message: str = FALLBACK_MESSAGE,
        min_confidence: float = 0.32,
        unanswered_log_path: Path | None = None,
    ) -> "KnowledgeBase":
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = cls._parse_entries(raw, source=str(path))

        return cls(
            entries=entries,
            fallback_message=fallback_message,
            min_confidence=min_confidence,
            unanswered_log_path=unanswered_log_path,
        )

    @classmethod
    def from_directory(
        cls,
        directory: Path,
        fallback_message: str = FALLBACK_MESSAGE,
        min_confidence: float = 0.32,
        unanswered_log_path: Path | None = None,
    ) -> "KnowledgeBase":
        if not directory.exists() or not directory.is_dir():
            raise ValueError(f"Knowledge base directory not found: {directory}")

        candidates = sorted(path for path in directory.glob("*.json") if path.name != "unanswered_questions.jsonl")
        if not candidates:
            raise ValueError(f"No JSON files found in knowledge base directory: {directory}")

        combined_entries: list[KnowledgeBaseEntry] = []
        for path in candidates:
            raw = json.loads(path.read_text(encoding="utf-8"))
            combined_entries.extend(cls._parse_entries(raw, source=str(path)))

        if not combined_entries:
            raise ValueError(f"No valid knowledge base entries found in: {directory}")

        return cls(
            entries=combined_entries,
            fallback_message=fallback_message,
            min_confidence=min_confidence,
            unanswered_log_path=unanswered_log_path,
        )

    @staticmethod
    def _parse_entries(raw: object, source: str) -> list[KnowledgeBaseEntry]:
        if isinstance(raw, dict):
            raw_entries = raw.get("entries")
        else:
            raw_entries = raw

        if not isinstance(raw_entries, list):
            raise ValueError(f"Knowledge base JSON must be a list (or object with entries[]) in {source}.")

        entries: list[KnowledgeBaseEntry] = []
        for idx, item in enumerate(raw_entries):
            if not isinstance(item, dict):
                raise ValueError(f"Knowledge base entry at index {idx} in {source} must be an object.")

            entry_id = str(item.get("id", f"entry-{idx + 1}"))
            question = str(item.get("question", "")).strip()
            answer = str(item.get("answer", "")).strip()
            keywords = [str(keyword).strip() for keyword in item.get("keywords", []) if str(keyword).strip()]

            if not question or not answer:
                raise ValueError(f"Knowledge base entry '{entry_id}' in {source} must include question and answer.")

            entries.append(
                KnowledgeBaseEntry(
                    id=entry_id,
                    question=question,
                    answer=answer,
                    keywords=keywords,
                )
            )

        return entries

    def _score(self, query: str, entry: KnowledgeBaseEntry) -> float:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return 0.0

        entry_text = f"{entry.question} {entry.answer} {' '.join(entry.keywords)}"
        entry_tokens = _tokenize(entry_text)
        if not entry_tokens:
            return 0.0

        overlap_score = len(query_tokens & entry_tokens) / len(query_tokens)
        keyword_tokens = _tokenize(" ".join(entry.keywords))
        keyword_score = len(query_tokens & keyword_tokens) / max(1, len(query_tokens))
        similarity_score = _similarity(query, entry.question)

        return (0.65 * overlap_score) + (0.20 * keyword_score) + (0.15 * similarity_score)

    def lookup(self, query: str) -> tuple[KnowledgeBaseEntry | None, float]:
        best_entry: KnowledgeBaseEntry | None = None
        best_score = 0.0

        for entry in self.entries:
            score = self._score(query, entry)
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_entry is None or best_score < self.min_confidence:
            return None, best_score

        return best_entry, best_score

    def note_unanswered(self, question: str) -> bool:
        if self.unanswered_log_path is None:
            return False

        self.unanswered_log_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "question": question.strip(),
        }
        with self.unanswered_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
        return True

    def answer_query(self, query: str) -> LookupResult:
        entry, confidence = self.lookup(query)
        if entry is None:
            noted = self.note_unanswered(query)
            return LookupResult(
                found=False,
                answer=self.fallback_message,
                confidence=confidence,
                noted_for_follow_up=noted,
            )

        return LookupResult(
            found=True,
            answer=entry.answer,
            matched_article_id=entry.id,
            matched_question=entry.question,
            confidence=confidence,
            noted_for_follow_up=False,
        )
