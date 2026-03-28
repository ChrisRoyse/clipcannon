"""Sentence boundary detection for streaming TTS.

Extracts complete sentences from a text buffer as tokens arrive from the LLM.
"""


class SentenceChunker:
    MIN_WORDS: int = 3
    MAX_WORDS: int = 50

    SENTENCE_ENDS: list[str] = [". ", "! ", "? ", ".\n", "!\n", "?\n"]
    CLAUSE_SEPS: list[str] = [", ", "; ", ": "]

    def extract_sentence(self, buffer: str) -> str | None:
        """Extract a complete sentence from the token buffer.

        Returns the sentence string (stripped) if found, None otherwise.
        The caller must advance the buffer past the returned text.
        """
        if not buffer:
            return None

        best = self._find_sentence_boundary(buffer)
        if best is not None:
            return best

        best = self._find_clause_boundary(buffer)
        if best is not None:
            return best

        words = buffer.split()
        if len(words) > self.MAX_WORDS:
            chunk_words = words[:self.MAX_WORDS]
            return " ".join(chunk_words)

        return None

    def _find_sentence_boundary(self, buffer: str) -> str | None:
        candidates: list[tuple[int, str]] = []
        for end in self.SENTENCE_ENDS:
            idx = buffer.find(end)
            if idx >= 0:
                candidate = buffer[:idx + 1].strip()
                candidates.append((idx, candidate))

        candidates.sort(key=lambda x: x[0])

        for _idx, candidate in candidates:
            if len(candidate.split()) >= self.MIN_WORDS:
                return candidate

        return None

    def _find_clause_boundary(self, buffer: str) -> str | None:
        candidates: list[tuple[int, str]] = []
        for sep in self.CLAUSE_SEPS:
            idx = buffer.find(sep)
            if idx >= 0 and idx > 60:
                candidate = buffer[:idx + 1].strip()
                candidates.append((idx, candidate))

        candidates.sort(key=lambda x: x[0])

        for _idx, candidate in candidates:
            if len(candidate.split()) >= self.MIN_WORDS:
                return candidate

        return None
