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
        configured_clients = settings.configured_api_clients()
        if configured_clients:
            self._clients = tuple(
                (
                    client.api_key_hash,
                    ClientIdentity(client.client_id, frozenset(client.scopes)),
                )
                for client in configured_clients
                if client.enabled
            )
            return

        self._clients = self._legacy_clients(settings)

    @staticmethod
    def _legacy_clients(settings: Settings) -> tuple[tuple[str, ClientIdentity], ...]:
        return (
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
                            "task:read",
                            "approval:write",
                            "admin:write",
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
