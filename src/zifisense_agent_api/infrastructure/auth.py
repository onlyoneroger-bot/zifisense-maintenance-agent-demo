from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from zifisense_agent_api.config import Settings


@dataclass(frozen=True, slots=True)
class ClientIdentity:
    client_id: str
    scopes: frozenset[str]


class ApiKeyAuthenticator:
    def __init__(self, settings: Settings) -> None:
        self._clients = (
            (
                settings.evaluator_api_key_hash,
                ClientIdentity(
                    client_id="evaluator",
                    scopes=frozenset(
                        {
                            "capability:read",
                            "evaluation:create",
                            "agent:invoke",
                            "event:write",
                            "mcp:use",
                        }
                    ),
                ),
            ),
            (settings.limited_api_key_hash, ClientIdentity("limited", frozenset())),
        )

    def authenticate(self, token: str) -> ClientIdentity | None:
        candidate = hashlib.sha256(token.encode("utf-8")).hexdigest()
        for expected_hash, identity in self._clients:
            if hmac.compare_digest(candidate, expected_hash):
                return identity
        return None
