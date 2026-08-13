"""The openfda dimension: every distinct enrichment block, stored once.

`openfda` blocks are 92.7% of the corpus's JSON bytes, and they repeat — the
same enrichment is stamped onto every drug row that mentions the product
(L-001). Storing one copy per distinct block is most of what turns 111 GB into
something a laptop can hold.

A block's identity is its own content rather than a key someone picked, which
is the move Git makes for every object it stores. `sort_keys=True` is
load-bearing: without it two identical blocks written in a different key order
hash differently and the dimension silently doubles.

Absent and empty are different facts. No `openfda` on a drug means nobody
looked; `openfda: {}` means someone looked and found nothing. Collapsing them
with a falsy test produced 492 round-trip mismatches in the spike (L-005), and
2025q1/0001-of-0028 carries 507 empty blocks that would go the same way. The
distinction lives in `key()`, so no caller has to remember it.
"""

from __future__ import annotations

import hashlib
import json


KEY_LENGTH = 16


# --- errors -----------------------------------------------------------------


class NormalizeError(Exception):
    """Base for every failure in this module."""


class KeyCollision(NormalizeError):
    """Two different blocks hashed to the same dimension key.

    Astronomically unlikely, and silent if unchecked: every drug row pointing
    at the key would carry another product's enrichment.
    """


# --- hashing ----------------------------------------------------------------


def _digest(block: dict) -> str:
    """sha1 over the block's canonical JSON, full width.

    Not a security hash — it is a content address, hence `usedforsecurity`.
    `key()` truncates it; the untruncated digest is what makes a truncation
    collision detectable.
    """
    canonical = json.dumps(block, sort_keys=True)

    return hashlib.sha1(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()


def key(block: dict | None) -> str | None:
    """The `dim_openfda` key for a block, or None if there was no block.

    None means absent, and only absent. An empty dict is a real block with a
    real key — the module docstring says why that difference is load-bearing.
    """
    return None if block is None else _digest(block)[:KEY_LENGTH]


# --- api --------------------------------------------------------------------


class OpenfdaDimension:
    """Every distinct block, emitted on first sight.

    Holds digests, never blocks. The 2,251 distinct blocks in
    2025q1/0001-of-0028 cost ~400 KB as digests against ~30 MB as blocks, and
    the ratio only widens with the corpus. The spike held the blocks; that is
    the version that does not survive 1,767 partitions.
    """

    def __init__(self) -> None:
        # key -> the full digest it was truncated from. Storing the whole
        # digest is what turns a collision into an exception instead of a
        # silently merged row, and at 2,251 entries it costs ~90 KB.
        self._digests: dict[str, str] = {}

    def __len__(self) -> int:
        """Distinct blocks seen so far. T9's metrics.json reports this."""
        return len(self._digests)

    def add(self, block: dict | None) -> tuple[str | None, dict | None]:
        """Return the block's key, plus the block itself only on first sight.

        `(None, None)` for an absent block, so the caller writes no branch of
        its own. That is what keeps the L-005 trap structurally impossible
        rather than a rule someone has to remember at every call site.

        Raises:
            KeyCollision: a different block already claims this key.
        """
        if block is None:
            return None, None

        digest = _digest(block)
        block_key = digest[:KEY_LENGTH]
        known = self._digests.get(block_key)

        if known is None:
            self._digests[block_key] = digest

            return block_key, block

        if known != digest:
            raise KeyCollision(
                f"Two different openfda blocks both truncate to {block_key!r} "
                f"({digest} vs {known}). Widen KEY_LENGTH before ingesting "
                f"further — dim_openfda would merge them."
            )

        return block_key, None
