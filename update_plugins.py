#!/usr/bin/env python3
"""Discover Datasette plugins on GitHub and update plugins.json."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import sys
import tempfile
import time
import tokenize
import tomllib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from run_plugin_tests import github_repository, normalize_package_name

DEFAULT_OWNERS = ("simonw", "dogsheep", "datasette", "asg017", "eyeseast")
GITHUB_API = "https://api.github.com"
RAW_GITHUB = "https://raw.githubusercontent.com"
PYPI_API = "https://pypi.org/pypi"
USER_AGENT = "ready-for-datasette/1.0"
MAX_NAMED_PACKAGES = 10


class ProjectParseError(ValueError):
    """A packaging file could not be parsed safely."""


class FetchError(RuntimeError):
    """A remote resource could not be fetched."""


@dataclass(frozen=True)
class RawResponse:
    content: bytes | None
    etag: str | None
    not_modified: bool = False


@dataclass(frozen=True)
class PluginSource:
    name: str
    github_repo: str
    metadata_file: str
    metadata_sha256: str
    metadata_etag: str | None


@dataclass(frozen=True)
class PluginRecord:
    name: str
    github_repo: str
    metadata_file: str
    metadata_sha256: str
    metadata_etag: str | None
    latest_version: str | None


class HttpClient:
    """Small urllib wrapper with GitHub authentication and transient retries."""

    def __init__(
        self,
        github_token: str | None = None,
        *,
        timeout: float = 30,
        retries: int = 3,
    ) -> None:
        self.github_token = github_token
        self.timeout = timeout
        self.retries = retries

    def _get(
        self,
        url: str,
        *,
        github_api: bool = False,
        etag: str | None = None,
    ) -> RawResponse:
        headers = {"User-Agent": USER_AGENT}
        if etag is not None:
            headers["If-None-Match"] = etag
        if github_api:
            headers["Accept"] = "application/vnd.github+json"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
            if self.github_token:
                headers["Authorization"] = f"Bearer {self.github_token}"

        for attempt in range(self.retries + 1):
            request = Request(url, headers=headers)
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return RawResponse(
                        content=response.read(),
                        etag=response.headers.get("ETag"),
                    )
            except HTTPError as ex:
                if ex.code == 304:
                    return RawResponse(
                        content=None,
                        etag=ex.headers.get("ETag") or etag,
                        not_modified=True,
                    )
                if ex.code == 404:
                    return RawResponse(content=None, etag=None)
                retryable = ex.code == 429 or 500 <= ex.code < 600
                if not retryable or attempt == self.retries:
                    raise FetchError(f"HTTP {ex.code} fetching {url}") from ex
                retry_after = ex.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 2**attempt
            except (TimeoutError, URLError) as ex:
                if attempt == self.retries:
                    raise FetchError(f"Error fetching {url}: {ex}") from ex
                delay = 2**attempt
            time.sleep(min(delay, 30))

        raise AssertionError("retry loop ended unexpectedly")

    def get_raw(self, url: str, *, etag: str | None = None) -> RawResponse:
        return self._get(url, etag=etag)

    def get_json(self, url: str, *, github_api: bool = False) -> Any:
        response = self._get(url, github_api=github_api)
        if response.content is None:
            return None
        try:
            return json.loads(response.content)
        except (UnicodeDecodeError, json.JSONDecodeError) as ex:
            raise FetchError(f"Invalid JSON returned by {url}") from ex


def parse_pyproject(document: str) -> str | None:
    """Return the project name if TOML declares a Datasette entry point."""

    try:
        parsed = tomllib.loads(document)
    except tomllib.TOMLDecodeError as ex:
        raise ProjectParseError(f"Invalid pyproject.toml: {ex}") from ex

    project = parsed.get("project")
    if not isinstance(project, Mapping):
        return None
    name = project.get("name")
    entry_points = project.get("entry-points")
    if (
        isinstance(name, str)
        and isinstance(entry_points, Mapping)
        and "datasette" in entry_points
    ):
        return name
    return None


_UNKNOWN = object()


class _StaticEvaluator:
    """Resolve enough Python literals to inspect setup.py without executing it."""

    def __init__(self, bindings: Mapping[str, ast.AST]) -> None:
        self.bindings = bindings
        self.resolving: set[str] = set()

    def evaluate(self, node: ast.AST) -> Any:
        try:
            return ast.literal_eval(node)
        except (ValueError, TypeError):
            pass

        if isinstance(node, ast.Name):
            if node.id in self.resolving or node.id not in self.bindings:
                return _UNKNOWN
            self.resolving.add(node.id)
            try:
                return self.evaluate(self.bindings[node.id])
            finally:
                self.resolving.remove(node.id)

        if isinstance(node, ast.Dict):
            result: dict[Any, Any] = {}
            for key_node, value_node in zip(node.keys, node.values):
                value = self.evaluate(value_node)
                if key_node is None:
                    if isinstance(value, Mapping):
                        result.update(value)
                    continue
                key = self.evaluate(key_node)
                if key is not _UNKNOWN:
                    result[key] = value
            return result

        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            values = [self.evaluate(item) for item in node.elts]
            constructor = {
                ast.List: list,
                ast.Tuple: tuple,
                ast.Set: set,
            }[type(node)]
            return constructor(values)

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "dict":
                result: dict[Any, Any] = {}
                for argument in node.args:
                    value = self.evaluate(argument)
                    if isinstance(value, Mapping):
                        result.update(value)
                for keyword in node.keywords:
                    value = self.evaluate(keyword.value)
                    if keyword.arg is None:
                        if isinstance(value, Mapping):
                            result.update(value)
                    else:
                        result[keyword.arg] = value
                return result

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self.evaluate(node.left)
            right = self.evaluate(node.right)
            if left is not _UNKNOWN and right is not _UNKNOWN:
                try:
                    return left + right
                except TypeError:
                    pass

        return _UNKNOWN


def _setup_call(call: ast.Call) -> bool:
    if isinstance(call.func, ast.Name):
        return call.func.id == "setup"
    return isinstance(call.func, ast.Attribute) and call.func.attr == "setup"


def _setup_arguments(call: ast.Call, evaluator: _StaticEvaluator) -> dict[str, Any]:
    arguments: dict[str, Any] = {}
    for keyword in call.keywords:
        value = evaluator.evaluate(keyword.value)
        if keyword.arg is None:
            if isinstance(value, Mapping):
                arguments.update(value)
        else:
            arguments[keyword.arg] = value
    return arguments


def _has_datasette_entry_points(value: Any) -> bool:
    if isinstance(value, Mapping):
        return "datasette" in value
    if isinstance(value, str):
        # setuptools also accepts INI-style entry point declarations.
        return any(line.strip().lower() == "[datasette]" for line in value.splitlines())
    return False


def parse_setup_py(document: str) -> str | None:
    """Return a static setup() name when it declares a Datasette entry point."""

    try:
        tree = ast.parse(document, filename="setup.py")
    except SyntaxError as ex:
        raise ProjectParseError(
            f"Invalid setup.py: {ex.msg} (line {ex.lineno})"
        ) from ex

    bindings: dict[str, ast.AST] = {}
    for statement in tree.body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            value = statement.value
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            for target in targets:
                if isinstance(target, ast.Name) and value is not None:
                    bindings[target.id] = value

    evaluator = _StaticEvaluator(bindings)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _setup_call(node):
            continue
        arguments = _setup_arguments(node, evaluator)
        name = arguments.get("name")
        if isinstance(name, str) and _has_datasette_entry_points(
            arguments.get("entry_points")
        ):
            return name
    return None


def list_public_repositories(owner: str, client: HttpClient) -> list[dict[str, Any]]:
    """Fetch every public repository owned by a GitHub user or organization."""

    repositories: list[dict[str, Any]] = []
    page = 1
    while True:
        encoded_owner = quote(owner, safe="")
        url = (
            f"{GITHUB_API}/users/{encoded_owner}/repos"
            f"?per_page=100&page={page}&type=public"
        )
        payload = client.get_json(url, github_api=True)
        if not isinstance(payload, list):
            raise FetchError(f"Expected a list of repositories from {url}")
        repositories.extend(item for item in payload if isinstance(item, dict))
        if len(payload) < 100:
            return repositories
        page += 1


def _raw_url(repository: Mapping[str, Any], filename: str) -> str:
    full_name = repository.get("full_name")
    default_branch = repository.get("default_branch")
    if not isinstance(full_name, str) or "/" not in full_name:
        raise ValueError(f"Invalid GitHub repository name: {full_name!r}")
    if not isinstance(default_branch, str) or not default_branch:
        raise ValueError(f"No default branch for {full_name}")
    owner, name = full_name.split("/", 1)
    return "/".join(
        (
            RAW_GITHUB,
            quote(owner, safe=""),
            quote(name, safe=""),
            quote(default_branch, safe=""),
            filename,
        )
    )


def _decode_setup_py(content: bytes) -> str:
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(content).readline)
        return content.decode(encoding)
    except (SyntaxError, UnicodeDecodeError) as ex:
        raise ProjectParseError(f"Invalid setup.py encoding: {ex}") from ex


def _cached_etag(
    previous: Mapping[str, Any] | None,
    github_repo: str,
    metadata_file: str,
) -> str | None:
    if (
        previous is not None
        and previous.get("github_repo") == github_repo
        and previous.get("metadata_file") == metadata_file
        and isinstance(previous.get("name"), str)
        and isinstance(previous.get("metadata_sha256"), str)
        and isinstance(previous.get("metadata_etag"), str)
    ):
        return str(previous["metadata_etag"])
    return None


def _source_from_304(
    previous: Mapping[str, Any] | None,
    github_repo: str,
    metadata_file: str,
    response: RawResponse,
) -> PluginSource:
    if previous is None:
        raise FetchError(
            f"Received an unexpected 304 for {github_repo}/{metadata_file}"
        )
    name = previous.get("name")
    metadata_sha256 = previous.get("metadata_sha256")
    if not isinstance(name, str) or not isinstance(metadata_sha256, str):
        raise FetchError(f"Cannot reuse incomplete cached metadata for {github_repo}")
    return PluginSource(
        name=name,
        github_repo=github_repo,
        metadata_file=metadata_file,
        metadata_sha256=metadata_sha256,
        metadata_etag=response.etag,
    )


def inspect_repository(
    repository: Mapping[str, Any],
    client: HttpClient,
    previous: Mapping[str, Any] | None = None,
) -> PluginSource | None:
    """Inspect raw packaging metadata, preferring pyproject.toml over setup.py."""

    github_repo = str(repository["full_name"])
    pyproject_url = _raw_url(repository, "pyproject.toml")
    pyproject_response = client.get_raw(
        pyproject_url,
        etag=_cached_etag(previous, github_repo, "pyproject.toml"),
    )
    if pyproject_response.not_modified:
        return _source_from_304(
            previous,
            github_repo,
            "pyproject.toml",
            pyproject_response,
        )
    if pyproject_response.content is not None:
        content = pyproject_response.content
        try:
            document = content.decode("utf-8")
        except UnicodeDecodeError as ex:
            raise ProjectParseError(f"Invalid UTF-8 in {pyproject_url}") from ex
        name = parse_pyproject(document)
        metadata_file = "pyproject.toml"
        metadata_etag = pyproject_response.etag
    else:
        setup_url = _raw_url(repository, "setup.py")
        setup_response = client.get_raw(
            setup_url,
            etag=_cached_etag(previous, github_repo, "setup.py"),
        )
        if setup_response.not_modified:
            return _source_from_304(
                previous,
                github_repo,
                "setup.py",
                setup_response,
            )
        if setup_response.content is None:
            return None
        content = setup_response.content
        name = parse_setup_py(_decode_setup_py(content))
        metadata_file = "setup.py"
        metadata_etag = setup_response.etag

    if name is None:
        return None
    return PluginSource(
        name=name,
        github_repo=github_repo,
        metadata_file=metadata_file,
        metadata_sha256=hashlib.sha256(content).hexdigest(),
        metadata_etag=metadata_etag,
    )


def latest_pypi_version(name: str, client: HttpClient) -> str | None:
    url = f"{PYPI_API}/{quote(name, safe='')}/json"
    payload = client.get_json(url)
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise FetchError(f"Expected a JSON object from {url}")
    info = payload.get("info")
    if not isinstance(info, Mapping):
        return None
    version = info.get("version")
    return version if isinstance(version, str) and version else None


def parse_package_names(value: str) -> list[str]:
    packages: list[str] = []
    seen: set[str] = set()
    for item in value.split(","):
        name = item.strip()
        if not name:
            continue
        normalized = normalize_package_name(name)
        if normalized not in seen:
            packages.append(normalized)
            seen.add(normalized)
    if not packages:
        raise ValueError("No package names were provided")
    if len(packages) > MAX_NAMED_PACKAGES:
        raise ValueError(
            f"At most {MAX_NAMED_PACKAGES} named packages can be refreshed"
        )
    return packages


def _plugin_record(record: Mapping[str, Any]) -> PluginRecord:
    required = (
        "name",
        "github_repo",
        "metadata_file",
        "metadata_sha256",
    )
    values = {key: record.get(key) for key in required}
    if not all(isinstance(value, str) and value for value in values.values()):
        raise ValueError(f"Invalid plugin record: {record!r}")
    metadata_etag = record.get("metadata_etag")
    latest_version = record.get("latest_version")
    if metadata_etag is not None and not isinstance(metadata_etag, str):
        raise ValueError(f"Invalid plugin metadata ETag: {metadata_etag!r}")
    if latest_version is not None and not isinstance(latest_version, str):
        raise ValueError(f"Invalid plugin version: {latest_version!r}")
    return PluginRecord(
        name=values["name"],
        github_repo=values["github_repo"],
        metadata_file=values["metadata_file"],
        metadata_sha256=values["metadata_sha256"],
        metadata_etag=metadata_etag,
        latest_version=latest_version,
    )


def merge_plugin_records(
    existing: Sequence[Mapping[str, Any]],
    updates: Sequence[PluginRecord],
) -> list[PluginRecord]:
    by_repository = {
        record.github_repo: record for record in map(_plugin_record, existing)
    }
    by_repository.update({record.github_repo: record for record in updates})
    return sorted(
        by_repository.values(),
        key=lambda record: (record.name.casefold(), record.github_repo),
    )


def refresh_named_plugins(
    package_names: Sequence[str],
    previous_records: Sequence[Mapping[str, Any]],
    client: HttpClient,
) -> list[PluginRecord]:
    previous_by_name: dict[str, list[Mapping[str, Any]]] = {}
    for record in previous_records:
        name = record.get("name")
        if isinstance(name, str):
            previous_by_name.setdefault(normalize_package_name(name), []).append(record)

    refreshed: list[PluginRecord] = []
    seen: set[str] = set()
    for raw_name in package_names:
        package = normalize_package_name(raw_name)
        if package in seen:
            continue
        seen.add(package)
        pypi_url = f"{PYPI_API}/{quote(package, safe='')}/json"
        payload = client.get_json(pypi_url)
        if not isinstance(payload, Mapping):
            raise FetchError(f"No released PyPI project found for {package}")
        info = payload.get("info")
        if not isinstance(info, Mapping):
            raise FetchError(f"PyPI returned no project metadata for {package}")
        published_name = info.get("name") or package
        version = info.get("version")
        if (
            not isinstance(published_name, str)
            or not isinstance(version, str)
            or not version
        ):
            raise FetchError(f"PyPI returned incomplete project metadata for {package}")
        normalized_name = normalize_package_name(published_name)

        previous_matches = previous_by_name.get(normalized_name, [])
        if previous_matches:
            for previous in previous_matches:
                record = _plugin_record(previous)
                refreshed.append(
                    PluginRecord(
                        name=record.name,
                        github_repo=record.github_repo,
                        metadata_file=record.metadata_file,
                        metadata_sha256=record.metadata_sha256,
                        metadata_etag=record.metadata_etag,
                        latest_version=version,
                    )
                )
            continue

        repository_name = github_repository(info, published_name)
        if repository_name is None:
            raise FetchError(
                f"PyPI metadata for {published_name} has no usable GitHub repository"
            )
        owner, repository = repository_name.split("/", 1)
        repository_url = (
            f"{GITHUB_API}/repos/{quote(owner, safe='')}/"
            f"{quote(repository, safe='')}"
        )
        repository_payload = client.get_json(repository_url, github_api=True)
        if not isinstance(repository_payload, Mapping):
            raise FetchError(f"GitHub repository not found: {repository_name}")
        source = inspect_repository(repository_payload, client)
        if source is None:
            raise FetchError(
                f"{repository_name} does not declare a Datasette plugin entry point"
            )
        if normalize_package_name(source.name) != normalized_name:
            raise FetchError(
                f"PyPI project {published_name} does not match repository project "
                f"{source.name}"
            )
        refreshed.append(
            PluginRecord(
                name=source.name,
                github_repo=source.github_repo,
                metadata_file=source.metadata_file,
                metadata_sha256=source.metadata_sha256,
                metadata_etag=source.metadata_etag,
                latest_version=version,
            )
        )

    return sorted(
        refreshed,
        key=lambda record: (record.name.casefold(), record.github_repo),
    )


def load_previous_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as ex:
        raise ValueError(f"Could not read existing {path}: {ex}") from ex
    if not isinstance(payload, list) or not all(
        isinstance(item, dict) for item in payload
    ):
        raise ValueError(f"Expected {path} to contain a JSON array of objects")
    return payload


def add_versions(
    sources: Sequence[PluginSource],
    previous_records: Sequence[Mapping[str, Any]],
    client: HttpClient,
    *,
    workers: int = 16,
    refresh_pypi: bool = False,
) -> list[PluginRecord]:
    """Use packaging hashes to avoid unnecessary PyPI API requests."""

    previous_by_repo = {
        item["github_repo"]: item
        for item in previous_records
        if isinstance(item.get("github_repo"), str)
    }
    versions: dict[PluginSource, str | None] = {}
    to_fetch: list[PluginSource] = []

    for source in sources:
        previous = previous_by_repo.get(source.github_repo)
        unchanged = (
            previous is not None
            and previous.get("metadata_file") == source.metadata_file
            and previous.get("metadata_sha256") == source.metadata_sha256
        )
        if unchanged and not refresh_pypi:
            cached_version = previous.get("latest_version")
            versions[source] = (
                cached_version if isinstance(cached_version, str) else None
            )
        else:
            to_fetch.append(source)

    if workers == 1:
        for source in to_fetch:
            versions[source] = latest_pypi_version(source.name, client)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_sources = {
                executor.submit(latest_pypi_version, source.name, client): source
                for source in to_fetch
            }
            for future in as_completed(future_sources):
                source = future_sources[future]
                versions[source] = future.result()

    return [
        PluginRecord(
            name=source.name,
            github_repo=source.github_repo,
            metadata_file=source.metadata_file,
            metadata_sha256=source.metadata_sha256,
            metadata_etag=source.metadata_etag,
            latest_version=versions[source],
        )
        for source in sources
    ]


def discover_sources(
    owners: Sequence[str],
    client: HttpClient,
    previous_records: Sequence[Mapping[str, Any]] = (),
    *,
    workers: int = 16,
) -> list[PluginSource]:
    previous_by_repo = {
        item["github_repo"]: item
        for item in previous_records
        if isinstance(item.get("github_repo"), str)
    }
    repositories: dict[str, dict[str, Any]] = {}
    for owner in owners:
        owner_repositories = list_public_repositories(owner, client)
        print(
            f"{owner}: found {len(owner_repositories)} public repositories",
            file=sys.stderr,
        )
        for repository in owner_repositories:
            full_name = repository.get("full_name")
            name = repository.get("name")
            if not isinstance(name, str) and isinstance(full_name, str):
                name = full_name.rsplit("/", 1)[-1]
            if (
                isinstance(full_name, str)
                and isinstance(name, str)
                and name.startswith("datasette-")
            ):
                repositories[full_name] = repository

    print(
        f"Inspecting {len(repositories)} datasette-* repositories",
        file=sys.stderr,
    )
    sources: list[PluginSource] = []
    repository_values = list(repositories.values())
    if workers == 1:
        for repository in repository_values:
            source = inspect_repository(
                repository,
                client,
                previous_by_repo.get(repository.get("full_name")),
            )
            if source is not None:
                sources.append(source)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    inspect_repository,
                    repository,
                    client,
                    previous_by_repo.get(repository.get("full_name")),
                ): repository
                for repository in repository_values
            }
            for future in as_completed(futures):
                source = future.result()
                if source is not None:
                    sources.append(source)
    return sorted(sources, key=lambda item: (item.name.casefold(), item.github_repo))


def write_plugins_json(records: Sequence[PluginRecord], output: Path) -> None:
    ordered = sorted(records, key=lambda item: (item.name.casefold(), item.github_repo))
    document = json.dumps([asdict(record) for record in ordered], indent=2) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(document)
            temporary_name = temporary.name
        os.replace(temporary_name, output)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--owner",
        action="append",
        dest="owners",
        metavar="USER_OR_ORG",
        help="GitHub owner to scan; repeat to scan several (defaults to the built-in set)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("plugins.json"),
        help="JSON file to update (default: plugins.json next to this script)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=16,
        help="Maximum concurrent raw GitHub and PyPI requests (default: 16)",
    )
    parser.add_argument(
        "--refresh-pypi",
        action="store_true",
        help="Refresh every PyPI version even when packaging content is unchanged",
    )
    parser.add_argument(
        "--package-names",
        default="",
        help=(
            "Refresh only these comma-separated PyPI packages, adding new "
            f"plugins from PyPI metadata (maximum {MAX_NAMED_PACKAGES})"
        ),
    )
    parser.add_argument(
        "--selected-output",
        type=Path,
        help="Write the targeted records to this artifact for a later exact merge",
    )
    parser.add_argument(
        "--merge-records",
        type=Path,
        help="Merge records from this JSON artifact into --output without fetching",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    previous_records = load_previous_records(args.output)

    if args.merge_records:
        if args.package_names or args.selected_output or args.owners:
            raise SystemExit(
                "--merge-records cannot be combined with --package-names, "
                "--selected-output, or --owner"
            )
        updates = [
            _plugin_record(record)
            for record in load_previous_records(args.merge_records)
        ]
        records = merge_plugin_records(previous_records, updates)
        write_plugins_json(records, args.output)
        print(
            f"Merged {len(updates)} targeted records into {args.output}",
            file=sys.stderr,
        )
        return 0

    client = HttpClient(github_token=os.environ.get("GITHUB_TOKEN"))
    if args.package_names:
        if args.owners or args.refresh_pypi:
            raise SystemExit(
                "--package-names cannot be combined with --owner or --refresh-pypi"
            )
        packages = parse_package_names(args.package_names)
        updates = refresh_named_plugins(packages, previous_records, client)
        records = merge_plugin_records(previous_records, updates)
        write_plugins_json(records, args.output)
        if args.selected_output:
            write_plugins_json(updates, args.selected_output)
        print(
            f"Refreshed {len(packages)} named packages in {args.output}",
            file=sys.stderr,
        )
        return 0
    if args.selected_output:
        raise SystemExit("--selected-output requires --package-names")

    owners = args.owners or list(DEFAULT_OWNERS)
    sources = discover_sources(
        owners,
        client,
        previous_records,
        workers=args.workers,
    )
    records = add_versions(
        sources,
        previous_records,
        client,
        workers=args.workers,
        refresh_pypi=args.refresh_pypi,
    )
    write_plugins_json(records, args.output)
    changed_count = sum(
        1
        for record in records
        if not any(
            previous.get("github_repo") == record.github_repo
            and previous.get("metadata_file") == record.metadata_file
            and previous.get("metadata_sha256") == record.metadata_sha256
            for previous in previous_records
        )
    )
    print(
        f"Wrote {len(records)} plugins to {args.output} "
        f"({changed_count} new or changed)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
