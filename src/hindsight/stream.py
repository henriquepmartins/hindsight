"""One report at a time, straight out of the partition zip.

A partition is ~800 MB of JSON compressed to ~155 MB. Neither the archive nor
the `results` array is ever materialized: `ZipFile.open()` decompresses lazily
as the parser reads, and ijson yields each report as its closing brace arrives.
Peak memory is one report — around 100 KB — whatever the partition weighs. At
1,767 partitions there is no version of "read it all, then loop" that works.

The contract is narrow on purpose: this yields exactly what `json.load` would
have produced for each element of `results`, only incrementally. Nothing is
filtered, coerced, or renamed here — the keep-list that dropped `companynumb`
from 89.6% of reports (L-005) has no place to hide in a function this shape.

Pass 1 (schema inference) and pass 2 (the Parquet write) both call this, which
is why it does not know what a schema is.
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from pathlib import Path

import ijson


REPORTS_PREFIX = "results.item"


# --- errors -----------------------------------------------------------------


class StreamError(Exception):
    """Base for every failure in this module."""


class UnexpectedArchiveShape(StreamError):
    """The archive is not one JSON member holding a populated `results` array.

    Raised rather than yielding nothing, which downstream would read as a
    partition that legitimately had no reports.
    """


# --- parsing ----------------------------------------------------------------


def _sole_json_member(archive: zipfile.ZipFile) -> str:
    """The one `.json` member, or raise naming what the archive actually holds."""
    members = [
        info.filename
        for info in archive.infolist()
        if not info.is_dir() and info.filename.endswith(".json")
    ]

    if len(members) != 1:
        contents = ", ".join(repr(info.filename) for info in archive.infolist())

        raise UnexpectedArchiveShape(
            f"{archive.filename} should hold exactly one .json member, found "
            f"{len(members)}. It contains: {contents or '(nothing)'}."
        )

    return members[0]


# --- api --------------------------------------------------------------------


def iter_reports(zip_path: Path | str) -> Iterator[dict]:
    """Yield every report in a partition archive, in file order.

    Lazy: the first report arrives long before the archive has been read
    through. Reading to exhaustion also checks the member's CRC-32, so an
    archive that rotted on disk raises instead of ending the stream early.

    `use_float=True` is what keeps ijson from yielding `decimal.Decimal` for
    numbers. FAERS is all strings in 2025q1 (measured: 19,648,458 scalars, every
    one a str), but a Decimal reaching T7's `json.dumps` hash would raise, and
    the promise here is `json.load`'s output rather than something more exotic.

    Raises:
        UnexpectedArchiveShape: not one JSON member, or no reports inside it.
        ijson.JSONError: the member is not the JSON openFDA documents.
        zipfile.BadZipFile: the archive did not survive its own CRC.
    """
    with (
        zipfile.ZipFile(zip_path) as archive,
        archive.open(_sole_json_member(archive)) as member,
    ):
        reports = ijson.items(member, REPORTS_PREFIX, use_float=True)
        first = next(reports, None)

        # Checked here rather than after the pass, so a moved shape costs
        # milliseconds instead of 800 MB of parsing. Safe to treat as an error:
        # no partition in the 2026-08-10 export reports zero records — the
        # smallest, 2024q4/0029-of-0029, holds 324.
        if first is None:
            raise UnexpectedArchiveShape(
                f"{zip_path} parsed, but nothing came out of {REPORTS_PREFIX!r}: "
                f"the reports array is empty, renamed, or no longer top level."
            )

        yield first
        yield from reports
