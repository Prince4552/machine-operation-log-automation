from __future__ import annotations

from abc import ABC, abstractmethod


class SignatureProvider(ABC):
    @abstractmethod
    def create_signature_request(self, document_id: str, signers: list[str], idempotency_key: str) -> str: ...


class MockSignatureProvider(SignatureProvider):
    def create_signature_request(self, document_id: str, signers: list[str], idempotency_key: str) -> str:
        return "SIGN-" + idempotency_key[:16].upper()
