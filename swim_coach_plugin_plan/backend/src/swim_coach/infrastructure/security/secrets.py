"""Versioned AES-256-GCM protection for Garmin token bundles."""

from __future__ import annotations

import secrets
from collections.abc import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import EncryptedSecret, UserId


class AesGcmSecretCipher:
    def __init__(self, keys: Mapping[str, bytes], active_version: str) -> None:
        self._keys = dict(keys)
        self.active_version = active_version
        if active_version not in self._keys:
            raise ValueError("active secret key version is missing")
        if any(len(key) != 32 for key in self._keys.values()):
            raise ValueError("AES-256-GCM keys must contain exactly 32 bytes")

    @staticmethod
    def _aad(user_id: UserId, purpose: str) -> bytes:
        return f"swim-coach|{purpose}|{user_id}".encode()

    def encrypt(
        self,
        plaintext: bytes,
        *,
        user_id: UserId,
        purpose: str = "garmin-token-bundle",
    ) -> EncryptedSecret:
        if not plaintext:
            raise ValueError("secret plaintext cannot be empty")
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._keys[self.active_version]).encrypt(
            nonce,
            plaintext,
            self._aad(user_id, purpose),
        )
        return EncryptedSecret(ciphertext, nonce, self.active_version)

    def decrypt(
        self,
        secret: EncryptedSecret,
        *,
        user_id: UserId,
        purpose: str = "garmin-token-bundle",
    ) -> bytes:
        key = self._keys.get(secret.key_version)
        if key is None:
            raise DomainError("TOKEN_INVALID", "The Garmin secret key version is unavailable.")
        try:
            return AESGCM(key).decrypt(
                secret.nonce,
                secret.ciphertext,
                self._aad(user_id, purpose),
            )
        except InvalidTag as exc:
            raise DomainError(
                "TOKEN_INVALID", "The Garmin secret could not be authenticated."
            ) from exc

    def rotate(self, secret: EncryptedSecret, *, user_id: UserId) -> EncryptedSecret:
        if secret.key_version == self.active_version:
            return secret
        plaintext = self.decrypt(secret, user_id=user_id)
        try:
            return self.encrypt(plaintext, user_id=user_id)
        finally:
            plaintext = b""


def mask_account_label(email: str) -> str:
    local, separator, domain = email.strip().casefold().partition("@")
    if not separator or not local or not domain:
        return "***"
    return f"{local[0]}***@{domain}"
