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

        best = self._find_boundary(buffer, self.SENTENCE_ENDS, min_position=0)
        if best is not None:
            return best

        best = self._find_boundary(buffer, self.CLAUSE_SEPS, min_position=60)
        if best is not None:
            return best

        words = buffer.split()
        if len(words) > self.MAX_WORDS:
            return " ".join(words[:self.MAX_WORDS])

        return None

    def _find_boundary(
        self, buffer: str, delimiters: list[str], min_position: int = 0,
    ) -> str | None:
        """Find the earliest delimiter that yields a chunk with enough words.

        Args:
            buffer: Text to search.
            delimiters: Delimiter strings to look for.
            min_position: Minimum index at which a delimiter is accepted.
        """
        candidates: list[tuple[int, str]] = []
        for delim in delimiters:
            idx = buffer.find(delim)
            if idx >= min_position:
                candidate = buffer[:idx + 1].strip()
                candidates.append((idx, candidate))

        candidates.sort(key=lambda x: x[0])

        for _idx, candidate in candidates:
            if len(candidate.split()) >= self.MIN_WORDS:
                return candidate

        return None
