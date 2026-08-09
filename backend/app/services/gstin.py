"""Offline GSTIN structural + checksum validation and deterministic generation.

GSTIN shape (15 chars): 2-digit state code + 10-char PAN (5 letters, 4 digits,
1 letter) + 1 entity-registration char (1-9 or A-Z) + fixed 'Z' + 1 checksum char.

The checksum is the standard mod-36 "Luhn-like" algorithm used across GSTIN
validators: each of the first 14 characters is mapped to its index in the
36-character alphabet, multiplied by an alternating factor of 2/1, and the
result is folded back into base 36 before summing.

This is pure offline structural/checksum validation — it does NOT call the
real GST portal (that's the `verification` STUB integration, see
CONTRACT.md/metrics_demo). It only proves a GSTIN is *well-formed*.
"""

import re
from dataclasses import dataclass
from random import Random

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_STRUCTURE_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


@dataclass(frozen=True)
class GstinCheck:
    valid: bool
    structure_valid: bool
    checksum_valid: bool
    reason: str | None = None


def _checksum_char(first_14: str) -> str:
    factor = 1
    total = 0
    for ch in first_14:
        digit = _ALPHABET.index(ch)
        factor = 2 if factor == 1 else 1
        product = digit * factor
        total += (product // 36) + (product % 36)
    check_value = (36 - (total % 36)) % 36
    return _ALPHABET[check_value]


def validate_gstin(gstin: str) -> GstinCheck:
    gstin = (gstin or "").strip().upper()

    if not _STRUCTURE_RE.match(gstin):
        return GstinCheck(
            valid=False,
            structure_valid=False,
            checksum_valid=False,
            reason="Does not match GSTIN structure: 2-digit state code + 10-char PAN + entity code + 'Z' + checksum",
        )

    expected = _checksum_char(gstin[:14])
    if expected != gstin[14]:
        return GstinCheck(
            valid=False,
            structure_valid=True,
            checksum_valid=False,
            reason=f"Checksum mismatch: expected '{expected}', got '{gstin[14]}'",
        )

    return GstinCheck(valid=True, structure_valid=True, checksum_valid=True, reason=None)


def generate_valid_gstin(state_code: str, seed: int) -> str:
    """Deterministically generates a structurally + checksum valid GSTIN.

    `state_code` must be a 2-digit string (e.g. "27" for Maharashtra). `seed`
    drives an isolated Random instance, so the same (state_code, seed) pair
    always produces the same GSTIN — required for idempotent seeding.
    """
    if not re.match(r"^[0-9]{2}$", state_code):
        raise ValueError("state_code must be a 2-digit string, e.g. '27'")

    rng = Random(seed)
    pan_letters_1 = "".join(rng.choice(_ALPHABET[10:]) for _ in range(5))
    pan_digits = "".join(rng.choice(_ALPHABET[:10]) for _ in range(4))
    pan_letter_2 = rng.choice(_ALPHABET[10:])
    entity_code = rng.choice("123456789")

    first_14 = f"{state_code}{pan_letters_1}{pan_digits}{pan_letter_2}{entity_code}Z"
    checksum = _checksum_char(first_14)
    gstin = first_14 + checksum

    check = validate_gstin(gstin)
    assert check.valid, f"generate_valid_gstin produced an invalid GSTIN: {gstin} ({check.reason})"
    return gstin
