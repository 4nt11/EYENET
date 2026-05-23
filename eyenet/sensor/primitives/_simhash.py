"""64-bit simhash over a feature-frequency mapping.

Algorithm (Charikar 2002):
  1. Hash each feature to a 64-bit integer.
  2. For each hash bit: add weight if 1, subtract if 0.
  3. Fingerprint: bit i = 1 iff sum_i > 0.

The `fnv1a_64` hash is used for speed and avalanche; not cryptographic.
"""

from __future__ import annotations

_FNV_PRIME = 0x100000001B3
_FNV_OFFSET = 0xCBF29CE484222325


def _fnv1a_64(data: bytes) -> int:
    h = _FNV_OFFSET
    for byte in data:
        h ^= byte
        h = (h * _FNV_PRIME) & 0xFFFFFFFFFFFFFFFF
    return h


def simhash64(features: dict[str, float]) -> str:
    """Return a 16-char lowercase hex string for the 64-bit simhash.

    `features` maps feature string → weight (typically raw frequency).
    Empty features dict → all-zeros fingerprint.
    """

    v = [0.0] * 64
    for feature, weight in features.items():
        h = _fnv1a_64(feature.encode("utf-8"))
        for i in range(64):
            if h & (1 << i):
                v[i] += weight
            else:
                v[i] -= weight

    bits = 0
    for i in range(64):
        if v[i] > 0:
            bits |= 1 << i

    return f"{bits:016x}"


__all__ = ["simhash64"]
