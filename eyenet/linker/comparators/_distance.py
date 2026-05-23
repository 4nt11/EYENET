"""Hamming distance helpers for 64-bit simhashes.

`hamming64(hex_a, hex_b)` is the single function all simhash comparators use.
It takes two 16-char hex strings (as produced by `sensor/primitives/_simhash.py`)
and returns the number of differing bits (0-64).
"""

from __future__ import annotations

_HEX_LEN = 16


def hamming64(hex_a: str, hex_b: str) -> int:
    """Compute the Hamming distance between two 64-bit values represented as hex strings.

    Args:
        hex_a: 16-character lowercase hex string.
        hex_b: 16-character lowercase hex string.

    Returns:
        Number of bits that differ (0-64).

    Raises:
        ValueError: if either string is not a valid 16-char hex string.
    """
    if len(hex_a) != _HEX_LEN or len(hex_b) != _HEX_LEN:
        raise ValueError(
            f"hamming64 requires 16-char hex strings; got {len(hex_a)!r} and {len(hex_b)!r}"
        )
    xor = int(hex_a, 16) ^ int(hex_b, 16)
    return bin(xor).count("1")


__all__ = ["hamming64"]
