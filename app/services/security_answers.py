"""
Shared normalization for security-question answers, used wherever one
is hashed or verified (setup, self-service update, recovery). Case and
surrounding whitespace shouldn't matter for a human typing an answer
from memory weeks or months later.
"""


def normalize_answer(answer: str) -> str:
    return answer.strip().lower()
