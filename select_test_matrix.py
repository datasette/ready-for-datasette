#!/usr/bin/env python3
"""Select released plugin/Datasette combinations that still need testing."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from run_plugin_tests import (
    RUNNER_VERSION,
    latest_datasette_alpha,
    normalize_package_name,
    pypi_project,
)


TERMINAL_OUTCOMES = {
    "passed",
    "test_failures",
    "collection_error",
    "no_tests",
    "install_error",
}
MAX_TESTS = 10
OWNER_PRIORITY = {"datasette": 0, "dogsheep": 1, "simonw": 2, "asg017": 3}


def released_plugins(records: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    released: dict[str, str] = {}
    for record in records:
        name = record.get("name")
        version = record.get("latest_version")
        if not isinstance(name, str) or not isinstance(version, str) or not version:
            continue
        normalized = normalize_package_name(name)
        previous = released.get(normalized)
        if previous is not None and previous != version:
            raise ValueError(
                f"Conflicting latest versions for {normalized}: "
                f"{previous!r} and {version!r}"
            )
        released[normalized] = version
    return released


def plugin_repositories(records: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    candidates: dict[str, list[str]] = {}
    for record in records:
        name = record.get("name")
        repository = record.get("github_repo")
        if not isinstance(name, str) or not isinstance(repository, str):
            continue
        normalized = normalize_package_name(name)
        candidates.setdefault(normalized, []).append(repository)
    return {
        name: min(
            repositories,
            key=lambda repository: (
                OWNER_PRIORITY.get(repository.partition("/")[0].casefold(), 99),
                repository.casefold(),
            ),
        )
        for name, repositories in candidates.items()
    }


def load_plugin_records(path: Path) -> list[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(
        isinstance(item, Mapping) for item in payload
    ):
        raise ValueError(f"Expected {path} to contain a JSON array of objects")
    return payload


def load_plugins(path: Path) -> dict[str, str]:
    return released_plugins(load_plugin_records(path))


def parse_requested_plugins(value: str) -> list[str]:
    requested: list[str] = []
    seen: set[str] = set()
    for item in value.split(","):
        name = item.strip()
        if not name:
            continue
        normalized = normalize_package_name(name)
        if normalized not in seen:
            requested.append(normalized)
            seen.add(normalized)
    if not requested:
        raise ValueError("No plugin names were provided")
    return requested


def select_requested_plugins(
    plugins: Mapping[str, str],
    requested_plugins: Sequence[str],
    datasette_version: str,
    *,
    repositories: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    if len(requested_plugins) > MAX_TESTS:
        raise ValueError(f"A manual test matrix may contain at most {MAX_TESTS} plugins")
    repositories = {} if repositories is None else repositories
    normalized_plugins = {
        normalize_package_name(name): version for name, version in plugins.items()
    }
    requested = [normalize_package_name(name) for name in requested_plugins]
    missing = [name for name in requested if name not in normalized_plugins]
    if missing:
        label = "plugin" if len(missing) == 1 else "plugins"
        raise ValueError(
            f"Unknown or unreleased {label}: {', '.join(missing)}"
        )

    candidates: list[dict[str, str]] = []
    for package in requested:
        candidate = {
            "package": package,
            "package_version": normalized_plugins[package],
            "datasette_version": datasette_version,
            "reason": "manual_request",
        }
        repository = repositories.get(package)
        if repository:
            candidate["repository"] = repository
        candidates.append(candidate)
    return candidates


def load_history(results_dir: Path) -> list[Mapping[str, Any]]:
    history: list[Mapping[str, Any]] = []
    if not results_dir.exists():
        return history
    for path in sorted(results_dir.glob("*/datasette-*/runs/*/result.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as ex:
            raise ValueError(f"Could not read historical result {path}: {ex}") from ex
        if not isinstance(payload, Mapping):
            raise ValueError(f"Expected an object in historical result {path}")
        history.append(payload)
    return history


def _result_identity(result: Mapping[str, Any]) -> tuple[str, str, str] | None:
    package = result.get("package")
    datasette = result.get("datasette")
    if not isinstance(package, Mapping) or not isinstance(datasette, Mapping):
        return None
    name = package.get("name")
    version = package.get("version")
    datasette_version = datasette.get("requested_version")
    if not all(
        isinstance(value, str) and value
        for value in (name, version, datasette_version)
    ):
        return None
    return normalize_package_name(name), version, datasette_version


def _completed_at(result: Mapping[str, Any]) -> datetime | None:
    run = result.get("run")
    value = run.get("completed_at") if isinstance(run, Mapping) else None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def select_candidates(
    plugins: Mapping[str, str],
    history: Sequence[Mapping[str, Any]],
    datasette_version: str,
    *,
    limit: int = 5,
    now: datetime | None = None,
    retry_after: timedelta = timedelta(hours=6),
    repositories: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    if limit < 0:
        raise ValueError("limit must not be negative")
    now = datetime.now(UTC) if now is None else now.astimezone(UTC)
    repositories = {} if repositories is None else repositories
    terminal: list[tuple[tuple[str, str, str], Mapping[str, Any]]] = []
    runner_errors: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    older_runner_identities: set[tuple[str, str, str]] = set()
    for result in history:
        identity = _result_identity(result)
        outcome = result.get("outcome")
        if identity is None or not isinstance(outcome, str):
            continue
        if result.get("runner_version") != RUNNER_VERSION:
            older_runner_identities.add(identity)
            continue
        if outcome in TERMINAL_OUTCOMES:
            terminal.append((identity, result))
        elif outcome == "runner_error":
            runner_errors.setdefault(identity, []).append(result)

    candidates: list[tuple[int, str, dict[str, str]]] = []
    for raw_name, package_version in plugins.items():
        package = normalize_package_name(raw_name)
        identity = (package, package_version, datasette_version)
        if any(existing_identity == identity for existing_identity, _ in terminal):
            continue

        exact_runner_errors = runner_errors.get(identity, [])
        if exact_runner_errors:
            latest_attempt = max(
                (_completed_at(item) for item in exact_runner_errors),
                default=None,
                key=lambda value: value or datetime.min.replace(tzinfo=UTC),
            )
            if latest_attempt is not None and now - latest_attempt < retry_after:
                continue
            priority = 3
            reason = "retry_runner_error"
        else:
            package_terminal = [
                existing_identity
                for existing_identity, _ in terminal
                if existing_identity[0] == package
            ]
            version_terminal = [
                existing_identity
                for existing_identity in package_terminal
                if existing_identity[1] == package_version
            ]
            if identity in older_runner_identities:
                priority = 0
                reason = "runner_updated"
            elif package_terminal and not version_terminal:
                priority = 0
                reason = "new_release"
            elif not package_terminal:
                priority = 1
                reason = "never_tested"
            else:
                priority = 2
                reason = "new_datasette_alpha"

        candidate = {
            "package": package,
            "package_version": package_version,
            "datasette_version": datasette_version,
            "reason": reason,
        }
        repository = repositories.get(package)
        if repository:
            candidate["repository"] = repository
        candidates.append((priority, package, candidate))

    candidates.sort(key=lambda item: (item[0], item[1]))
    return [candidate for _, _, candidate in candidates[: min(limit, MAX_TESTS)]]


def write_github_outputs(candidates: Sequence[Mapping[str, str]], path: Path) -> None:
    matrix = json.dumps({"include": list(candidates)}, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as output:
        output.write(f"has_work={'true' if candidates else 'false'}\n")
        output.write(f"matrix={matrix}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugins", type=Path, default=Path("plugins.json"))
    parser.add_argument("--results", type=Path, default=Path("results"))
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--plugin-names",
        default="",
        help=(
            "Comma-separated plugin names to test explicitly, ignoring history "
            f"and --limit (maximum {MAX_TESTS})"
        ),
    )
    parser.add_argument("--datasette-version")
    parser.add_argument("--github-output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    datasette_version = args.datasette_version or latest_datasette_alpha(
        pypi_project("datasette")
    )
    plugin_records = load_plugin_records(args.plugins)
    plugins = released_plugins(plugin_records)
    repositories = plugin_repositories(plugin_records)
    if args.plugin_names:
        candidates = select_requested_plugins(
            plugins,
            parse_requested_plugins(args.plugin_names),
            datasette_version,
            repositories=repositories,
        )
    else:
        candidates = select_candidates(
            plugins,
            load_history(args.results),
            datasette_version,
            limit=args.limit,
            repositories=repositories,
        )
    if args.github_output:
        write_github_outputs(candidates, args.github_output)
    print(json.dumps({"include": candidates}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
