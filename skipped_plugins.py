"""Load and apply the repository's package skip list."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from run_plugin_tests import normalize_package_name

DEFAULT_SKIP_FILE = Path(__file__).with_name("skip-these.txt")


def load_skipped_plugins(path: Path = DEFAULT_SKIP_FILE) -> frozenset[str]:
    skipped: set[str] = set()
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        package = line.partition("#")[0].strip()
        if not package:
            continue
        try:
            skipped.add(normalize_package_name(package))
        except ValueError as ex:
            raise ValueError(
                f"Invalid package name in {path} on line {line_number}: {package!r}"
            ) from ex
    return frozenset(skipped)


def without_skipped_records(
    records: Sequence[Mapping[str, Any]],
    skipped: frozenset[str],
) -> list[Mapping[str, Any]]:
    included: list[Mapping[str, Any]] = []
    for record in records:
        name = record.get("name")
        if isinstance(name, str) and normalize_package_name(name) in skipped:
            continue
        included.append(record)
    return included
