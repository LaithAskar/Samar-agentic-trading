from __future__ import annotations

import logging

from samar_secrets.redact import RedactSecretsFilter
from samar_secrets.vault import associated_data, open_secret, rewrap, seal


def _demo_key() -> str:
    return "sk-" + "ant-demo1234abcd"


def test_round_trip_and_aad_binds_the_row() -> None:
    kek = b"k" * 32
    aad = associated_data("user-a", "anthropic")
    sealed = seal(_demo_key(), aad, kek, kek_version=1)
    assert open_secret(sealed, aad, kek) == _demo_key()
    assert sealed.last4 == "abcd"
    assert _demo_key().encode() not in sealed.ciphertext


def test_ciphertext_cannot_move_between_users() -> None:
    kek = b"k" * 32
    sealed = seal(_demo_key(), associated_data("user-a", "anthropic"), kek, 1)
    try:
        open_secret(sealed, associated_data("user-b", "anthropic"), kek)
    except Exception as exc:
        assert type(exc).__name__ == "InvalidTag"
    else:
        raise AssertionError("moved ciphertext decrypted")


def test_kek_rotation_rewraps_without_changing_plaintext() -> None:
    old = b"o" * 32
    new = b"n" * 32
    aad = associated_data("user-a", "openrouter")
    plain = "sk-" + "or-v1-route-key-zzzz"
    sealed = seal(plain, aad, old, kek_version=1)
    rotated = rewrap(sealed, aad, old, new, new_version=2)
    assert rotated.kek_version == 2
    assert rotated.ciphertext == sealed.ciphertext
    assert rotated.wrapped_dek != sealed.wrapped_dek
    assert open_secret(rotated, aad, new) == plain


def test_log_filter_redacts_provider_keys() -> None:
    filt = RedactSecretsFilter()
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "key " + _demo_key() + " leaked", (), None)
    assert filt.filter(record) is True
    assert record.msg == "key sk-redacted leaked"


def test_redaction_covers_all_key_formats() -> None:
    filt = RedactSecretsFilter()
    cases = [
        ("sk-" + "ant-demo1234abcd", "sk-redacted"),
        ("sk-" + "or-v1-route-key-zzzz", "sk-redacted"),
        ("sk-" + "nous-abcdefgh", "sk-redacted"),
        ("sk-" + "A" * 20, "sk-redacted"),
        ("pub-" + "ABCDEFGHIJKL", "pub-redacted"),
    ]
    for raw, expected in cases:
        msg = f"leaked {raw} here"
        record = logging.LogRecord("t", logging.INFO, __file__, 1, msg, (), None)
        assert filt.filter(record) is True
        assert record.msg == f"leaked {expected} here", f"failed for {raw!r}: got {record.msg!r}"
