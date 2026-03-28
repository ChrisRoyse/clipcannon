"""Context window manager for LLM token budgeting."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class ContextManager:
    MAX_TOKENS: int = 32000
    SYSTEM_RESERVE: int = 2000
    RESPONSE_RESERVE: int = 512
    HISTORY_BUDGET: int = MAX_TOKENS - SYSTEM_RESERVE - RESPONSE_RESERVE

    def __init__(self, tokenizer_path: str | None = None) -> None:
        self._tokenizer = None
        if tokenizer_path:
            try:
                from transformers import AutoTokenizer
                self._tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)
                logger.info("Loaded tokenizer from %s", tokenizer_path)
            except Exception as exc:
                logger.warning(
                    "Failed to load tokenizer from '%s': %s. "
                    "Falling back to char-based estimation.",
                    tokenizer_path, exc,
                )

    def _count_tokens(self, text: str) -> int:
        if not text:
            return 0
        if self._tokenizer:
            return len(self._tokenizer.encode(text))
        return max(1, len(text) // 4)

    def build_messages(
        self,
        system_prompt: str,
        conversation_history: list[dict[str, str]],
        user_input: str,
    ) -> list[dict[str, str]]:
        """Build message list for the LLM, respecting token budget.

        Returns [system_msg, ...history_msgs, user_msg].
        Drops OLDEST history turns first when over budget.
        """
        system_msg = {"role": "system", "content": system_prompt}
        user_msg = {"role": "user", "content": user_input}

        system_tokens = self._count_tokens(system_prompt)
        user_tokens = self._count_tokens(user_input)

        budget = self.MAX_TOKENS - system_tokens - user_tokens - self.RESPONSE_RESERVE
        if budget < 0:
            logger.warning(
                "System (%d) + user (%d) + reserve (%d) > MAX_TOKENS (%d). No history.",
                system_tokens, user_tokens, self.RESPONSE_RESERVE, self.MAX_TOKENS,
            )
            return [system_msg, user_msg]

        turn_tokens = [self._count_tokens(t["content"]) for t in conversation_history]
        total = sum(turn_tokens)

        if total <= budget:
            return [system_msg] + list(conversation_history) + [user_msg]

        included_start = 0
        running = total
        while included_start < len(conversation_history) and running > budget:
            running -= turn_tokens[included_start]
            included_start += 1

        dropped = included_start
        if dropped > 0:
            logger.info("Dropped %d oldest turns to fit budget", dropped)

        return [system_msg] + list(conversation_history[included_start:]) + [user_msg]
