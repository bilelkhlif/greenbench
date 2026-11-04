"""Vectorised open-addressing hash table (linear probing, Fibonacci hashing).

Shared by the hash join and the hash index. Keys must be unique int64 values (a primary
key). Inserts and probes advance all pending keys one slot per round, so the work is
O(n x average probe length) with no sorting anywhere: a genuine hash table, written in
the same NumPy style as the sort-based variants it is compared with.
"""

from __future__ import annotations

import numpy as np

EMPTY = np.iinfo(np.int64).min
_GOLDEN = np.uint64(0x9E3779B97F4A7C15)


def fib_hash(keys: np.ndarray, bits: int) -> np.ndarray:
    """Top `bits` bits of key * 2^64/phi (mod 2^64)."""
    h = np.ascontiguousarray(keys, dtype=np.int64).view(np.uint64) * _GOLDEN
    return (h >> np.uint64(64 - bits)).astype(np.int64)


class HashTable:
    def __init__(self, keys: np.ndarray, load_factor: float = 0.5):
        keys = np.ascontiguousarray(keys, dtype=np.int64)
        n = keys.size
        self.bits = max(4, int(np.ceil(np.log2(max(n, 1) / load_factor))))
        cap = 1 << self.bits
        self.mask = cap - 1
        self.slot_keys = np.full(cap, EMPTY, dtype=np.int64)
        self.slot_rows = np.full(cap, -1, dtype=np.int64)
        slots = fib_hash(keys, self.bits)
        pending = np.arange(n, dtype=np.int64)
        placed = np.zeros(n, dtype=bool)
        self.rounds = 0
        while pending.size:
            self.rounds += 1
            s = slots[pending]
            free = self.slot_keys[s] == EMPTY
            cand, cs = pending[free], s[free]
            if cand.size:
                # Several candidates may target one free slot: whoever is written last owns it.
                self.slot_rows[cs] = cand
                won = self.slot_rows[cs] == cand
                self.slot_keys[cs[won]] = keys[cand[won]]
                placed[cand[won]] = True
            pending = pending[~placed[pending]]
            slots[pending] = (slots[pending] + 1) & self.mask

    def lookup(self, probe: np.ndarray) -> np.ndarray:
        """Row index of each probe key in the build input, or -1 when absent."""
        probe = np.ascontiguousarray(probe, dtype=np.int64)
        slots = fib_hash(probe, self.bits)
        out = np.full(probe.size, -1, dtype=np.int64)
        pending = np.arange(probe.size, dtype=np.int64)
        while pending.size:
            s = slots[pending]
            k = self.slot_keys[s]
            hit = k == probe[pending]
            out[pending[hit]] = self.slot_rows[s[hit]]
            go_on = ~(hit | (k == EMPTY))
            pending = pending[go_on]
            slots[pending] = (s[go_on] + 1) & self.mask
        return out


def radix_partition(keys: np.ndarray, parts: int) -> tuple[np.ndarray, np.ndarray]:
    """Group row ids by hash partition. Returns (row order, partition offsets).

    Uses the low bits of a second multiplicative hash so partitions are independent of the
    table slots; the stable argsort on a uint8 key is a linear-time radix sort in NumPy.
    """
    h = (np.ascontiguousarray(keys, dtype=np.int64).view(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F))
    part = ((h >> np.uint64(56)) % np.uint64(parts)).astype(np.uint8)
    order = np.argsort(part, kind="stable")
    offsets = np.concatenate([[0], np.cumsum(np.bincount(part, minlength=parts))])
    return order, offsets
