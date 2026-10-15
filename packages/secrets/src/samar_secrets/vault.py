from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32


@dataclass(frozen=True)
class SealedSecret:
    ciphertext: bytes
    wrapped_dek: bytes
    nonce: bytes
    dek_nonce: bytes
    kek_version: int
    last4: str


def seal(plaintext: str, aad: bytes, kek: bytes, kek_version: int) -> SealedSecret:
    if len(kek) != KEY_BYTES:
        raise ValueError("KEK must be 32 bytes")
    dek = os.urandom(KEY_BYTES)
    dek_nonce = os.urandom(12)
    wrapped_dek = AESGCM(kek).encrypt(dek_nonce, dek, aad)
    nonce = os.urandom(12)
    ciphertext = AESGCM(dek).encrypt(nonce, plaintext.encode("utf-8"), aad)
    return SealedSecret(
        ciphertext=ciphertext,
        wrapped_dek=wrapped_dek,
        nonce=nonce,
        dek_nonce=dek_nonce,
        kek_version=kek_version,
        last4=plaintext[-4:],
    )


def open_secret(sealed: SealedSecret, aad: bytes, kek: bytes) -> str:
    dek = AESGCM(kek).decrypt(sealed.dek_nonce, sealed.wrapped_dek, aad)
    raw = AESGCM(dek).decrypt(sealed.nonce, sealed.ciphertext, aad)
    return raw.decode("utf-8")


def rewrap(sealed: SealedSecret, aad: bytes, old_kek: bytes, new_kek: bytes, new_version: int) -> SealedSecret:
    dek = AESGCM(old_kek).decrypt(sealed.dek_nonce, sealed.wrapped_dek, aad)
    dek_nonce = os.urandom(12)
    wrapped = AESGCM(new_kek).encrypt(dek_nonce, dek, aad)
    return SealedSecret(
        ciphertext=sealed.ciphertext,
        wrapped_dek=wrapped,
        nonce=sealed.nonce,
        dek_nonce=dek_nonce,
        kek_version=new_version,
        last4=sealed.last4,
    )


def associated_data(user_id: str, kind: str) -> bytes:
    return f"{user_id}|{kind}".encode()
