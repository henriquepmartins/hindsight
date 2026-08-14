from __future__ import annotations

import zipfile
from collections.abc import Iterator
from pathlib import Path

import ijson


REPORTS_PREFIX = "results.item"


class StreamError(Exception):
    pass


class UnexpectedArchiveShape(StreamError):
    pass


def _sole_json_member(archive: zipfile.ZipFile) -> str:
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


def json_bytes(zip_path: Path | str) -> int:
    with zipfile.ZipFile(zip_path) as archive:
        return archive.getinfo(_sole_json_member(archive)).file_size


def iter_reports(zip_path: Path | str) -> Iterator[dict]:
    with (
        zipfile.ZipFile(zip_path) as archive,
        archive.open(_sole_json_member(archive)) as member,
    ):
        reports = ijson.items(member, REPORTS_PREFIX, use_float=True)
        first = next(reports, None)

        if first is None:
            raise UnexpectedArchiveShape(
                f"{zip_path} parsed, but nothing came out of {REPORTS_PREFIX!r}: "
                f"the reports array is empty, renamed, or no longer top level."
            )

        yield first
        yield from reports
