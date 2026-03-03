from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPORTED_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml"}
_TOKEN_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_'-]*")
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "can",
    "do",
    "does",
    "for",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "when",
    "where",
    "why",
    "you",
}


def _tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(text)]


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _split_sentences(text: str) -> list[str]:
    cleaned = text.replace("\n", " ")
    cleaned = re.sub(r"\s+#{1,6}\s+", ". ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return []

    parts = re.split(r"(?<=[.!?])\s+|\s+-\s+", cleaned)
    sentences: list[str] = []
    for part in parts:
        normalized = _normalize_whitespace(part)
        normalized = re.sub(r"^#{1,6}\s*", "", normalized)
        normalized = re.sub(r"^-+\s*", "", normalized)
        if normalized:
            sentences.append(normalized)
    return sentences


def _extract_relevant_excerpt(text: str, query_tokens: set[str], *, max_chars: int) -> str:
    normalized = _normalize_whitespace(text)
    if len(normalized) <= max_chars:
        return normalized

    lowered = normalized.lower()
    positions = [lowered.find(token) for token in query_tokens if token and lowered.find(token) != -1]
    if not positions:
        return normalized[: max_chars - 3].rstrip() + "..."

    center = min(positions)
    window_start = max(0, center - (max_chars // 3))
    window_end = min(len(normalized), window_start + max_chars)
    excerpt = normalized[window_start:window_end].strip()
    if window_start > 0:
        excerpt = "... " + excerpt
    if window_end < len(normalized):
        excerpt = excerpt + " ..."
    return excerpt


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    chunk_id: int
    source: str
    text: str
    token_count: int
    token_freq: dict[str, int]


@dataclass(frozen=True, slots=True)
class SearchResult:
    chunk: KnowledgeChunk
    score: float


class KnowledgeBase:
    def __init__(
        self,
        knowledge_dir: str | Path,
        *,
        chunk_size_chars: int = 900,
        chunk_overlap_chars: int = 140,
    ) -> None:
        self.knowledge_dir = Path(knowledge_dir)
        self.chunk_size_chars = max(300, chunk_size_chars)
        self.chunk_overlap_chars = max(0, min(chunk_overlap_chars, self.chunk_size_chars // 2))

        self._chunks: list[KnowledgeChunk] = []
        self._inverted_index: dict[str, set[int]] = {}
        self._doc_freq: dict[str, int] = {}
        self._avg_doc_len = 0.0
        self._source_counts: dict[str, int] = {}
        self._tool_cache: dict[tuple[str, int], str] = {}

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def source_count(self) -> int:
        return len(self._source_counts)

    def load(self) -> "KnowledgeBase":
        self._chunks.clear()
        self._inverted_index.clear()
        self._doc_freq.clear()
        self._source_counts.clear()
        self._tool_cache.clear()

        next_chunk_id = 0
        total_tokens = 0

        for path in self._iter_source_files():
            source_text = self._read_source_text(path)
            if not source_text:
                continue
            source_name = str(path.relative_to(self.knowledge_dir))
            chunks = self._chunk_text(source_text)
            if not chunks:
                continue

            self._source_counts[source_name] = len(chunks)
            for chunk_text in chunks:
                tokens = _tokenize(chunk_text)
                if not tokens:
                    continue
                token_freq: dict[str, int] = {}
                for token in tokens:
                    token_freq[token] = token_freq.get(token, 0) + 1
                token_count = len(tokens)
                total_tokens += token_count
                chunk = KnowledgeChunk(
                    chunk_id=next_chunk_id,
                    source=source_name,
                    text=chunk_text,
                    token_count=token_count,
                    token_freq=token_freq,
                )
                self._chunks.append(chunk)
                for token in token_freq:
                    self._inverted_index.setdefault(token, set()).add(next_chunk_id)
                next_chunk_id += 1

        for token, chunk_ids in self._inverted_index.items():
            self._doc_freq[token] = len(chunk_ids)

        self._avg_doc_len = total_tokens / len(self._chunks) if self._chunks else 0.0
        return self

    def search(self, query: str, *, top_k: int = 4) -> list[SearchResult]:
        raw_query_tokens = _tokenize(query)
        query_tokens = [token for token in raw_query_tokens if token not in _STOP_WORDS]
        if not query_tokens:
            query_tokens = raw_query_tokens
        if not query_tokens or not self._chunks:
            return []

        unique_query_tokens = set(query_tokens)
        if len(unique_query_tokens) <= 2:
            min_terms_required = len(unique_query_tokens)
        elif len(unique_query_tokens) <= 4:
            min_terms_required = 2
        else:
            min_terms_required = 3
        candidate_ids: set[int] = set()
        for token in unique_query_tokens:
            candidate_ids.update(self._inverted_index.get(token, set()))

        if not candidate_ids:
            return []

        total_docs = len(self._chunks)
        k1 = 1.5
        b = 0.75
        lowered_query = _normalize_whitespace(query).lower()

        scored_results: list[SearchResult] = []
        for chunk_id in candidate_ids:
            chunk = self._chunks[chunk_id]
            doc_len = chunk.token_count or 1
            score = 0.0
            matched_terms = 0

            for token in unique_query_tokens:
                tf = chunk.token_freq.get(token, 0)
                if tf == 0:
                    continue
                matched_terms += 1
                df = self._doc_freq.get(token, 0)
                idf = math.log(1.0 + ((total_docs - df + 0.5) / (df + 0.5)))
                denom = tf + k1 * (1 - b + b * (doc_len / (self._avg_doc_len or 1)))
                score += idf * ((tf * (k1 + 1)) / (denom or 1))

            if lowered_query and lowered_query in chunk.text.lower():
                score += 0.8

            score += 0.35 * (matched_terms / max(1, len(unique_query_tokens)))
            if matched_terms >= min_terms_required and score > 0:
                scored_results.append(SearchResult(chunk=chunk, score=score))

        scored_results.sort(key=lambda result: result.score, reverse=True)
        if not scored_results:
            return []
        top_score = scored_results[0].score
        min_score = max(0.5, top_score * 0.22)
        filtered = [result for result in scored_results if result.score >= min_score]
        return filtered[: max(1, top_k)]

    def answer(
        self,
        question: str,
        *,
        top_k: int = 3,
        max_sentences: int = 3,
    ) -> tuple[str, list[SearchResult], bool]:
        results = self.search(question, top_k=max(1, top_k))
        if not results:
            return (
                "I could not find a confident match in the knowledge base for that question.",
                [],
                False,
            )

        raw_query_tokens = set(_tokenize(question))
        query_tokens = {token for token in raw_query_tokens if token not in _STOP_WORDS} or raw_query_tokens
        if query_tokens:
            query_tokens = {token for token in query_tokens if token not in _STOP_WORDS} or query_tokens
        candidate_sentences: list[tuple[float, str]] = []
        seen: set[str] = set()

        for result in results:
            for sentence in _split_sentences(result.chunk.text):
                norm_sentence = _normalize_whitespace(sentence)
                if not norm_sentence:
                    continue
                sentence_tokens = _tokenize(norm_sentence)
                if len(sentence_tokens) < 5 and not norm_sentence.endswith((".", "!", "?")):
                    continue
                sentence_key = norm_sentence.lower()
                if sentence_key in seen:
                    continue
                seen.add(sentence_key)
                overlap = len(query_tokens & set(sentence_tokens))
                if overlap == 0:
                    continue
                sentence_score = overlap + (result.score * 0.12)
                candidate_sentences.append((sentence_score, norm_sentence))

        if not candidate_sentences:
            fallback = _normalize_whitespace(results[0].chunk.text)
            if len(fallback) > 320:
                fallback = fallback[:317].rstrip() + "..."
            answer_text = fallback
        else:
            candidate_sentences.sort(key=lambda item: item[0], reverse=True)
            selected = [sentence for _, sentence in candidate_sentences[:max(1, max_sentences)]]
            answer_text = " ".join(selected)

        answer_text = re.sub(r"\.\.+", ".", answer_text)

        citations = []
        for result in results:
            if result.chunk.source not in citations:
                citations.append(result.chunk.source)
            if len(citations) >= 2:
                break
        citation_suffix = f" [source: {', '.join(citations)}]" if citations else ""
        confidence_high = self._is_high_confidence(question, results)
        return answer_text + citation_suffix, results, confidence_high

    def render_tool_payload(self, question: str, *, top_k: int = 3) -> str:
        cache_key = (_normalize_whitespace(question).lower(), max(1, top_k))
        cached = self._tool_cache.get(cache_key)
        if cached:
            return cached

        answer_text, results, confidence_high = self.answer(question, top_k=top_k)
        if not results:
            payload = (
                "NO_MATCH\n"
                "No relevant answer was found in the local knowledge base. "
                "Ask a clarifying question or offer escalation."
            )
            self._tool_cache[cache_key] = payload
            return payload

        if not confidence_high:
            payload = (
                "LOW_CONFIDENCE\n"
                "Potentially related information exists, but there is not enough confidence to provide "
                "a factual answer. Ask a concise clarifying question or offer escalation."
            )
            self._tool_cache[cache_key] = payload
            return payload

        query_tokens = set(_tokenize(question))
        lines = [f"ANSWER\n{answer_text}", "EVIDENCE"]
        for index, result in enumerate(results, start=1):
            excerpt = _extract_relevant_excerpt(
                result.chunk.text,
                query_tokens,
                max_chars=320,
            )
            lines.append(
                f"[{index}] source={result.chunk.source} score={result.score:.3f} text={excerpt}"
            )
        payload = "\n".join(lines)
        self._tool_cache[cache_key] = payload
        return payload

    def inventory_summary(self, *, max_sources: int = 20) -> str:
        if not self._source_counts:
            return "No knowledge base documents were found."
        parts: list[str] = []
        for source_name in sorted(self._source_counts.keys())[:max_sources]:
            parts.append(f"- {source_name} ({self._source_counts[source_name]} chunks)")
        if len(self._source_counts) > max_sources:
            parts.append(f"- ...and {len(self._source_counts) - max_sources} more sources")
        return "\n".join(parts)

    def _is_high_confidence(
        self,
        question: str,
        results: list[SearchResult],
    ) -> bool:
        if not results:
            return False
        raw_query_tokens = set(_tokenize(question))
        query_tokens = {token for token in raw_query_tokens if token not in _STOP_WORDS} or raw_query_tokens
        if not query_tokens:
            return False

        top_chunk = results[0].chunk
        top_score = results[0].score
        coverage = len(query_tokens & set(top_chunk.token_freq.keys())) / len(query_tokens)

        required_coverage = 1.0 if len(query_tokens) <= 2 else 0.6
        required_score = 1.6
        return coverage >= required_coverage and top_score >= required_score

    def _iter_source_files(self) -> list[Path]:
        if not self.knowledge_dir.exists():
            return []
        paths = [
            path
            for path in self.knowledge_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        paths.sort()
        return paths

    def _read_source_text(self, path: Path) -> str:
        try:
            if path.suffix.lower() == ".json":
                with path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                return self._flatten_json(payload)
            with path.open("r", encoding="utf-8") as handle:
                return handle.read()
        except Exception:
            return ""

    def _flatten_json(self, payload: Any) -> str:
        lines: list[str] = []

        def _walk(value: Any, prefix: str = "") -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    next_prefix = f"{prefix}.{key}" if prefix else str(key)
                    _walk(nested, next_prefix)
                return
            if isinstance(value, list):
                for idx, nested in enumerate(value):
                    next_prefix = f"{prefix}[{idx}]"
                    _walk(nested, next_prefix)
                return
            scalar = _normalize_whitespace(str(value))
            if not scalar:
                return
            if prefix:
                lines.append(f"{prefix}: {scalar}")
            else:
                lines.append(scalar)

        _walk(payload)
        return "\n".join(lines)

    def _chunk_text(self, text: str) -> list[str]:
        normalized_lines = text.replace("\r\n", "\n")
        sections = [
            _normalize_whitespace(part)
            for part in re.split(r"\n{2,}", normalized_lines)
            if _normalize_whitespace(part)
        ]
        if not sections:
            return []

        units: list[str] = []
        for section in sections:
            if len(section) <= self.chunk_size_chars:
                units.append(section)
                continue
            sentence_buffer: list[str] = []
            sentence_len = 0
            for sentence in _split_sentences(section):
                norm_sentence = _normalize_whitespace(sentence)
                if not norm_sentence:
                    continue
                if len(norm_sentence) > self.chunk_size_chars:
                    if sentence_buffer:
                        units.append(" ".join(sentence_buffer))
                        sentence_buffer = []
                        sentence_len = 0
                    start = 0
                    while start < len(norm_sentence):
                        end = min(len(norm_sentence), start + self.chunk_size_chars)
                        segment = norm_sentence[start:end].strip()
                        if segment:
                            units.append(segment)
                        start = end
                    continue
                projected_len = sentence_len + len(norm_sentence) + (1 if sentence_buffer else 0)
                if sentence_buffer and projected_len > self.chunk_size_chars:
                    units.append(" ".join(sentence_buffer))
                    sentence_buffer = [norm_sentence]
                    sentence_len = len(norm_sentence)
                else:
                    sentence_buffer.append(norm_sentence)
                    sentence_len = projected_len
            if sentence_buffer:
                units.append(" ".join(sentence_buffer))

        chunks: list[str] = []
        current_parts: list[str] = []
        current_len = 0

        for unit in units:
            projected_len = current_len + len(unit) + (1 if current_parts else 0)
            if current_parts and projected_len > self.chunk_size_chars:
                chunks.append(" ".join(current_parts))
                if self.chunk_overlap_chars > 0:
                    overlap_parts: list[str] = []
                    overlap_len = 0
                    for part in reversed(current_parts):
                        added_len = len(part) + (1 if overlap_parts else 0)
                        if overlap_len + added_len > self.chunk_overlap_chars:
                            break
                        overlap_parts.insert(0, part)
                        overlap_len += added_len
                    current_parts = overlap_parts
                    current_len = len(" ".join(current_parts)) if current_parts else 0
                else:
                    current_parts = []
                    current_len = 0

            if current_parts:
                current_parts.append(unit)
                current_len = len(" ".join(current_parts))
            else:
                current_parts = [unit]
                current_len = len(unit)

        if current_parts:
            chunks.append(" ".join(current_parts))

        return chunks
