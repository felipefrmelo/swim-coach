from dataclasses import replace

import pytest

from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import UserId
from swim_coach.infrastructure.security import AesGcmSecretCipher, mask_account_label


def test_aes_gcm_round_trip_tamper_detection_and_rotation() -> None:
    user_id = UserId.new()
    old_cipher = AesGcmSecretCipher({"v1": b"1" * 32}, "v1")
    encrypted = old_cipher.encrypt(b'{"token":"secret"}', user_id=user_id)

    assert old_cipher.decrypt(encrypted, user_id=user_id) == b'{"token":"secret"}'
    assert b"secret" not in encrypted.ciphertext

    with pytest.raises(DomainError, match="authenticated"):
        old_cipher.decrypt(
            replace(encrypted, ciphertext=encrypted.ciphertext[:-1] + b"x"),
            user_id=user_id,
        )
    with pytest.raises(DomainError):
        old_cipher.decrypt(encrypted, user_id=UserId.new())

    rotating = AesGcmSecretCipher({"v1": b"1" * 32, "v2": b"2" * 32}, "v2")
    rotated = rotating.rotate(encrypted, user_id=user_id)
    assert rotated.key_version == "v2"
    assert rotating.decrypt(rotated, user_id=user_id) == b'{"token":"secret"}'


def test_account_label_is_masked() -> None:
    assert mask_account_label("Athlete@Example.com") == "a***@example.com"
    assert mask_account_label("invalid") == "***"
