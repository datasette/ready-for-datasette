#!/usr/bin/env python3
"""Merge staged plugin test artifacts into the immutable results history."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from run_plugin_tests import normalize_package_name, result_paths


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as ex:
        raise ValueError(f"Could not read {path}: {ex}") from ex
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def _required_string(mapping: Mapping[str, Any], key: str, path: Path) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Expected a non-empty {key!r} string in {path}")
    return value


def _nested_object(
    mapping: Mapping[str, Any], key: str, path: Path
) -> Mapping[str, Any]:
    value = mapping.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"Expected a {key!r} object in {path}")
    return value


def _completed_at(result: Mapping[str, Any], path: Path) -> datetime:
    run = _nested_object(result, "run", path)
    value = _required_string(run, "completed_at", path)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as ex:
        raise ValueError(f"Invalid completed_at timestamp in {path}: {value!r}") from ex
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            json.dump(payload, temporary, indent=2)
            temporary.write("\n")
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def _canonical_result(
    source_result: Path, results_dir: Path
) -> tuple[dict[str, Any], Path, Path]:
    payload = _read_object(source_result)
    package = _nested_object(payload, "package", source_result)
    datasette = _nested_object(payload, "datasette", source_result)
    run = _nested_object(payload, "run", source_result)
    package_name = normalize_package_name(
        _required_string(package, "name", source_result)
    )
    datasette_version = _required_string(datasette, "requested_version", source_result)
    run_id = _required_string(run, "id", source_result)
    _completed_at(payload, source_result)
    paths = result_paths(results_dir, package_name, datasette_version, run_id)

    canonical = copy.deepcopy(payload)
    artifacts = canonical.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
        canonical["artifacts"] = artifacts
    try:
        output_path = paths.pytest_output.relative_to(results_dir.parent)
    except ValueError:
        output_path = paths.pytest_output
    artifacts["pytest_output"] = output_path.as_posix()
    return canonical, paths.result, paths.pytest_output


def _same_json(path: Path, expected: Mapping[str, Any]) -> bool:
    try:
        return _read_object(path) == expected
    except ValueError:
        return False


def _latest_sort_key(result: Mapping[str, Any], path: Path) -> tuple[datetime, str]:
    run = _nested_object(result, "run", path)
    return _completed_at(result, path), _required_string(run, "id", path)


def _index_results(results_dir: Path) -> list[dict[str, Any]]:
    latest_results = [
        _read_object(path)
        for path in sorted(results_dir.glob("*/datasette-*/latest.json"))
    ]
    return sorted(
        latest_results,
        key=lambda item: (
            str((item.get("package") or {}).get("name", "")),
            str((item.get("datasette") or {}).get("requested_version", "")),
        ),
    )


def _rebuild_index(results_dir: Path) -> None:
    latest_results = _index_results(results_dir)
    completed_values = [
        _required_string(
            _nested_object(item, "run", results_dir),
            "completed_at",
            results_dir,
        )
        for item in latest_results
    ]
    index = {
        "schema_version": 1,
        "generated_at": max(completed_values, default=None),
        "results": latest_results,
    }
    _atomic_write_json(results_dir / "index.json", index)


def merge_results(incoming_dir: Path, results_dir: Path) -> list[Path]:
    incoming_dir = Path(incoming_dir)
    results_dir = Path(results_dir)
    staged_results = sorted(incoming_dir.rglob("result.json"))
    if not staged_results:
        return []

    merged: list[Path] = []
    for source_result in staged_results:
        source_output = source_result.with_name("pytest.txt")
        if not source_output.is_file():
            raise ValueError(f"Missing pytest.txt next to {source_result}")
        canonical, destination_result, destination_output = _canonical_result(
            source_result, results_dir
        )
        destination_directory = destination_result.parent
        if destination_directory.exists():
            if not (
                destination_result.is_file()
                and destination_output.is_file()
                and _same_json(destination_result, canonical)
                and destination_output.read_bytes() == source_output.read_bytes()
            ):
                raise FileExistsError(
                    f"Conflicting immutable run at {destination_directory}"
                )
        else:
            destination_directory.mkdir(parents=True)
            shutil.copyfile(source_output, destination_output)
            _atomic_write_json(destination_result, canonical)

        pair_directory = destination_directory.parent.parent
        latest_path = pair_directory / "latest.json"
        if not latest_path.exists() or _latest_sort_key(
            canonical, source_result
        ) >= _latest_sort_key(_read_object(latest_path), latest_path):
            _atomic_write_json(latest_path, canonical)
        merged.append(destination_directory)

    _rebuild_index(results_dir)
    return merged


OUTCOME_LABELS = {
    "passed": "passed",
    "test_failures": "test failures",
    "collection_error": "collection error",
    "no_tests": "no tests",
    "install_error": "install error",
    "no_sdist": "no source distribution",
    "runner_error": "runner error",
}


def _describe_result(result: Mapping[str, Any]) -> str:
    package = result.get("package") or {}
    datasette = result.get("datasette") or {}
    counts = result.get("counts") or {}
    outcome = str(result.get("outcome") or "unknown")
    label = OUTCOME_LABELS.get(outcome, outcome.replace("_", " "))
    line = (
        f"- {package.get('name', 'unknown')} {package.get('version', '?')}"
        f" on Datasette {datasette.get('requested_version', '?')}: {label}"
    )
    count_parts = [
        f"{counts[key]} {key}"
        for key in ("passed", "failed", "errors", "skipped")
        if isinstance(counts.get(key), int) and counts[key]
    ]
    if count_parts:
        line += f" ({', '.join(count_parts)})"
    return line


def commit_message(results: Sequence[Mapping[str, Any]]) -> str:
    """Build a commit message summarizing a batch of merged results."""
    names: list[str] = []
    for result in results:
        name = str((result.get("package") or {}).get("name", "unknown"))
        if name not in names:
            names.append(name)
    title = "Test results: " + ", ".join(names) if names else "Record plugin test results"

    tally: dict[str, int] = {}
    for result in results:
        outcome = str(result.get("outcome") or "unknown")
        tally[outcome] = tally.get(outcome, 0) + 1
    summary = ", ".join(
        f"{count} {OUTCOME_LABELS.get(outcome, outcome.replace('_', ' '))}"
        for outcome, count in sorted(
            tally.items(), key=lambda item: (item[0] != "passed", item[0])
        )
    )
    run_word = "run" if len(results) == 1 else "runs"
    lines = [title, "", f"{len(results)} {run_word}: {summary}", ""]
    lines.extend(_describe_result(result) for result in results)

    for result in results:
        name = (result.get("package") or {}).get("name", "unknown")
        failing = list(result.get("failing_tests") or []) + list(
            result.get("error_tests") or []
        )
        warnings = [
            w.get("message") or w.get("code")
            for w in result.get("warnings") or []
            if isinstance(w, Mapping)
        ]
        if not failing and not warnings:
            continue
        lines.extend(["", f"{name}:"])
        for test in failing[:10]:
            lines.append(f"  - {test}")
        if len(failing) > 10:
            lines.append(f"  - ...and {len(failing) - 10} more")
        for warning in warnings:
            lines.append(f"  - Warning: {warning}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("incoming", type=Path)
    parser.add_argument("--results", type=Path, default=Path("results"))
    parser.add_argument(
        "--commit-message",
        type=Path,
        help="Write a commit message summarizing the merged results to this file",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    merged = merge_results(args.incoming, args.results)
    if not merged:
        print(f"No result.json files found under {args.incoming}; nothing to merge")
        return 0
    for directory in merged:
        print(directory)
    if args.commit_message is not None:
        results = [_read_object(directory / "result.json") for directory in merged]
        args.commit_message.write_text(commit_message(results), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
