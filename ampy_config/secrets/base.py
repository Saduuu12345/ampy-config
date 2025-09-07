from __future__ import annotations
from typing import Protocol

class SecretResolver(Protocol):
    scheme: str  # e.g., "secret", "aws-sm", "gcp-sm", "local"

    def resolve(self, ref: str) -> str:
        """
        Resolve a secret reference to a value.
        Must raise RuntimeError with a helpful message if not found / misconfigured.
        """
        ...
