"""Deterministic UUIDv4 generation for seed data.

Regular uuid.uuid4() draws from os.urandom and can't be reproduced across seed
runs, but the seed script needs stable IDs so `--reset` (or a plain re-run)
produces an identical dataset every time. This builds a UUID from a seeded
random.Random instance and stamps in the standard version-4 / variant bits, so
the result is indistinguishable in shape from a "real" uuid4 — just reproducible.
"""

import uuid
from random import Random


def det_uuid4(rng: Random) -> str:
    raw = bytearray(rng.getrandbits(8) for _ in range(16))
    raw[6] = (raw[6] & 0x0F) | 0x40  # version 4
    raw[8] = (raw[8] & 0x3F) | 0x80  # variant 10xx
    return str(uuid.UUID(bytes=bytes(raw)))
