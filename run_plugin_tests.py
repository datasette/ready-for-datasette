#!/usr/bin/env python3
"""Run a plugin's tests against the latest Datasette 1.0 alpha."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import secrets
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


PYPI_API = "https://pypi.org/pypi"
USER_AGENT = "ready-for-datasette-test-runner/1.0"
ALPHA_PATTERN = re.compile(r"^1\.0a(\d+)$", re.IGNORECASE)
SAFE_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


@dataclass(frozen=True)
class ResultPaths:
    root: Path
    run_directory: Path
    pytest_output: Path
    result: Path
    latest: Path
    index: Path


@dataclass(frozen=True)
class Sdist:
    url: str
    sha256: str


@dataclass(frozen=True)
class ReleasedSource:
    repository: str | None
    sdist: Sdist
    test_suite: TestSuiteSource


@dataclass(frozen=True)
class TestSuiteSource:
    kind: str
    repository: str | None = None
    ref: str | None = None
    git_sha: str | None = None


def normalize_package_name(name: str) -> str:
    normalized = re.sub(r"[-_.]+", "-", name).lower().strip("-")
    if not normalized or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalized):
        raise ValueError(f"Invalid Python package name: {name!r}")
    return normalized


def _available_release(files: Any) -> bool:
    return isinstance(files, list) and any(
        isinstance(item, Mapping) and not item.get("yanked", False) for item in files
    )


def latest_datasette_alpha(payload: Mapping[str, Any]) -> str:
    releases = payload.get("releases")
    if not isinstance(releases, Mapping):
        raise ValueError("Datasette PyPI response has no releases object")
    candidates: list[tuple[int, str]] = []
    for version, files in releases.items():
        if not isinstance(version, str):
            continue
        match = ALPHA_PATTERN.fullmatch(version)
        if match and _available_release(files):
            candidates.append((int(match.group(1)), version))
    if not candidates:
        raise ValueError("No non-yanked Datasette 1.0 alpha release was found")
    return max(candidates)[1]


def _github_repo_from_url(raw_url: Any) -> str | None:
    if not isinstance(raw_url, str) or not raw_url.strip():
        return None
    url = raw_url.strip()
    if url.startswith("git+"):
        url = url[4:]
    ssh_match = re.search(r"github\.com[:/]([^/\s]+)/([^/\s#?]+)", url)
    if ssh_match:
        owner, repository = ssh_match.groups()
    else:
        parsed = urlparse(url)
        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            return None
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            return None
        owner, repository = parts[:2]
    repository = repository.removesuffix(".git")
    if not owner or not repository:
        return None
    return f"{owner}/{repository}"


def github_repository(info: Mapping[str, Any], package_name: str) -> str | None:
    urls: list[tuple[str, Any]] = []
    project_urls = info.get("project_urls")
    if isinstance(project_urls, Mapping):
        urls.extend((str(label), url) for label, url in project_urls.items())
    for key in ("home_page", "download_url"):
        if info.get(key):
            urls.append((key, info[key]))

    normalized_package = normalize_package_name(package_name)
    candidates: list[tuple[int, str]] = []
    for label, url in urls:
        repository = _github_repo_from_url(url)
        if repository is None:
            continue
        repository_name = normalize_package_name(repository.rsplit("/", 1)[-1])
        label_lower = label.casefold()
        score = 0
        if repository_name == normalized_package:
            score += 30
        if normalized_package in repository.casefold():
            score += 10
        if label_lower in {"source", "source code", "repository", "homepage"}:
            score += 5
        if label_lower in {"issues", "ci", "changelog", "documentation"}:
            score -= 10
        candidates.append((score, repository))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][1]


def select_sdist(payload: Mapping[str, Any]) -> Sdist:
    urls = payload.get("urls")
    if not isinstance(urls, list):
        raise ValueError("PyPI response has no release files")
    for item in urls:
        if (
            not isinstance(item, Mapping)
            or item.get("packagetype") != "sdist"
            or item.get("yanked", False)
        ):
            continue
        url = item.get("url")
        digests = item.get("digests")
        sha256 = digests.get("sha256") if isinstance(digests, Mapping) else None
        if isinstance(url, str) and isinstance(sha256, str) and url and sha256:
            return Sdist(url=url, sha256=sha256)
    raise ValueError("PyPI release has no non-yanked source distribution")


def release_tag_candidates(package_name: str, version: str) -> tuple[str, ...]:
    package_name = normalize_package_name(package_name)
    return version, f"v{version}", f"{package_name}-{version}"


def fetch_json(url: str, *, timeout: float = 30, retries: int = 3) -> Any:
    for attempt in range(retries + 1):
        request = Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as ex:
            retryable = ex.code == 429 or 500 <= ex.code < 600
            if not retryable or attempt == retries:
                raise RuntimeError(f"HTTP {ex.code} fetching {url}") from ex
            retry_after = ex.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else 2**attempt
        except (TimeoutError, URLError, json.JSONDecodeError) as ex:
            if attempt == retries:
                raise RuntimeError(f"Error fetching {url}: {ex}") from ex
            delay = 2**attempt
        time.sleep(min(delay, 30))
    raise AssertionError("retry loop ended unexpectedly")


def pypi_project(package_name: str) -> Mapping[str, Any]:
    normalized = normalize_package_name(package_name)
    payload = fetch_json(f"{PYPI_API}/{quote(normalized, safe='')}/json")
    if not isinstance(payload, Mapping):
        raise ValueError(f"PyPI returned invalid metadata for {package_name}")
    return payload


def _run_git(arguments: Sequence[str], *, cwd: Path | None = None) -> str:
    process = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
        check=False,
    )
    if process.returncode:
        detail = process.stderr.strip() or process.stdout.strip()
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")
    return process.stdout.strip()


def checkout_release_tag(
    repository: str,
    package_name: str,
    version: str,
    destination: Path,
) -> TestSuiteSource | None:
    clone_url = f"https://github.com/{repository}.git"
    candidates = release_tag_candidates(package_name, version)
    patterns = [f"refs/tags/{candidate}" for candidate in candidates]
    output = _run_git(["ls-remote", "--refs", "--tags", clone_url, *patterns])
    available = {
        line.split("\t", 1)[1].removeprefix("refs/tags/")
        for line in output.splitlines()
        if "\trefs/tags/" in line
    }
    tag = next((candidate for candidate in candidates if candidate in available), None)
    if tag is None:
        return None
    _run_git(
        [
            "clone",
            "--quiet",
            "--depth",
            "1",
            "--branch",
            tag,
            clone_url,
            str(destination),
        ]
    )
    git_sha = _run_git(["rev-parse", "HEAD"], cwd=destination)
    return TestSuiteSource(
        kind="github_release_tag",
        repository=repository,
        ref=tag,
        git_sha=git_sha,
    )


def download_sdist(
    sdist: Sdist,
    destination: Path,
    *,
    timeout: float = 60,
    retries: int = 3,
) -> None:
    for attempt in range(retries + 1):
        digest = hashlib.sha256()
        request = Request(sdist.url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=timeout) as response, destination.open(
                "wb"
            ) as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    output.write(chunk)
        except (HTTPError, TimeoutError, URLError, OSError) as ex:
            destination.unlink(missing_ok=True)
            if attempt == retries:
                raise RuntimeError(f"Could not download {sdist.url}: {ex}") from ex
            time.sleep(min(2**attempt, 30))
            continue
        actual_sha256 = digest.hexdigest()
        if actual_sha256.casefold() != sdist.sha256.casefold():
            destination.unlink(missing_ok=True)
            raise RuntimeError(
                f"SHA-256 mismatch for {sdist.url}: "
                f"expected {sdist.sha256}, got {actual_sha256}"
            )
        return


def _archive_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise RuntimeError(f"Unsafe path in source distribution: {name!r}")
    return path


def extract_sdist(archive_path: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    roots: set[str] = set()
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            for item in archive.infolist():
                path = _archive_member_path(item.filename)
                roots.add(path.parts[0])
                mode = item.external_attr >> 16
                if mode and stat.S_ISLNK(mode):
                    raise RuntimeError(
                        f"Symlink in source distribution: {item.filename!r}"
                    )
            archive.extractall(destination)
    elif tarfile.is_tarfile(archive_path):
        with tarfile.open(archive_path) as archive:
            members = archive.getmembers()
            for item in members:
                path = _archive_member_path(item.name)
                roots.add(path.parts[0])
                if not (item.isfile() or item.isdir()):
                    raise RuntimeError(
                        f"Unsupported archive member: {item.name!r}"
                    )
            archive.extractall(destination, members=members)
    else:
        raise RuntimeError(f"Unsupported source distribution archive: {archive_path}")

    if len(roots) != 1:
        raise RuntimeError(
            f"Expected one top-level source directory, found: {sorted(roots)}"
        )
    source = destination / next(iter(roots))
    if not source.is_dir():
        raise RuntimeError("Source distribution root is not a directory")
    return source


def build_pytest_command(
    package_name: str,
    sdist_path: Path,
    datasette_version: str,
    report_path: Path,
    *,
    python_version: str = "3.13",
    pytest_args: Sequence[str] = (),
) -> list[str]:
    return [
        "uv",
        "run",
        "--isolated",
        "--no-project",
        "--python",
        python_version,
        "--prerelease",
        "allow",
        "--no-progress",
        "--with",
        f"{normalize_package_name(package_name)}[test] @ "
        f"{sdist_path.resolve().as_uri()}",
        "--with",
        "pytest",
        "--with",
        "pytest-json-report",
        "--with",
        f"datasette=={datasette_version}",
        "pytest",
        "-vv",
        "--json-report",
        f"--json-report-file={report_path}",
        *pytest_args,
    ]


def run_and_capture(command: Sequence[str], cwd: Path, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUNBUFFERED"] = "1"
    with output.open("wb") as log:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        assert process.stdout is not None
        while True:
            chunk = process.stdout.read(64 * 1024)
            if not chunk:
                break
            log.write(chunk)
            log.flush()
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
        return process.wait()


def load_json_report(path: Path) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _integer(mapping: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return 0


def summarize_pytest_report(
    report: Mapping[str, Any], pytest_exit_code: int
) -> dict[str, Any]:
    summary_value = report.get("summary")
    summary = summary_value if isinstance(summary_value, Mapping) else {}
    tests_value = report.get("tests")
    tests = tests_value if isinstance(tests_value, list) else []
    collectors_value = report.get("collectors")
    collectors = collectors_value if isinstance(collectors_value, list) else []
    warnings_value = report.get("warnings")
    warnings = warnings_value if isinstance(warnings_value, list) else []

    failing_tests = sorted(
        {
            str(test["nodeid"])
            for test in tests
            if isinstance(test, Mapping)
            and test.get("outcome") == "failed"
            and isinstance(test.get("nodeid"), str)
        }
    )
    error_tests = {
        str(collector["nodeid"])
        for collector in collectors
        if isinstance(collector, Mapping)
        and collector.get("outcome") == "failed"
        and isinstance(collector.get("nodeid"), str)
    }
    for test in tests:
        if not isinstance(test, Mapping) or not isinstance(test.get("nodeid"), str):
            continue
        for phase_name in ("setup", "teardown"):
            phase = test.get(phase_name)
            if isinstance(phase, Mapping) and phase.get("outcome") == "failed":
                error_tests.add(str(test["nodeid"]))

    counts = {
        "collected": _integer(summary, "collected", "total") or len(tests),
        "passed": _integer(summary, "passed"),
        "failed": _integer(summary, "failed"),
        "errors": _integer(summary, "errors", "error"),
        "skipped": _integer(summary, "skipped"),
        "xfailed": _integer(summary, "xfailed"),
        "xpassed": _integer(summary, "xpassed"),
        "deselected": _integer(summary, "deselected"),
        "warnings": _integer(summary, "warnings") or len(warnings),
    }
    if pytest_exit_code == 0:
        outcome = "passed"
    elif pytest_exit_code == 5:
        outcome = "no_tests"
    elif pytest_exit_code == 1 and failing_tests:
        outcome = "test_failures"
    elif pytest_exit_code == 1 and counts["errors"]:
        outcome = "collection_error"
    elif pytest_exit_code == 1:
        outcome = "test_failures"
    else:
        outcome = "runner_error"
    return {
        "passed": pytest_exit_code == 0,
        "outcome": outcome,
        "counts": counts,
        "failing_tests": failing_tests,
        "error_tests": sorted(error_tests),
    }


def empty_summary(outcome: str) -> dict[str, Any]:
    return {
        "passed": False,
        "outcome": outcome,
        "counts": {
            "collected": 0,
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "xfailed": 0,
            "xpassed": 0,
            "deselected": 0,
            "warnings": 0,
        },
        "failing_tests": [],
        "error_tests": [],
    }


def make_run_id(
    started: datetime,
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    environment = os.environ if environ is None else environ
    timestamp = started.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    github_run_id = environment.get("GITHUB_RUN_ID")
    if github_run_id:
        attempt = environment.get("GITHUB_RUN_ATTEMPT", "1")
        return f"{timestamp}-gh-{github_run_id}-a{attempt}"
    return f"{timestamp}-local-{secrets.token_hex(3)}"


def _safe_version(version: str) -> str:
    if not SAFE_VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"Unsafe version for a result path: {version!r}")
    return version


def result_paths(
    root: Path,
    package_name: str,
    datasette_version: str,
    run_id: str,
) -> ResultPaths:
    normalized_package = normalize_package_name(package_name)
    safe_datasette_version = _safe_version(datasette_version)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id):
        raise ValueError(f"Unsafe run ID: {run_id!r}")
    root = Path(root)
    pair_directory = root / normalized_package / f"datasette-{safe_datasette_version}"
    run_directory = pair_directory / "runs" / run_id
    return ResultPaths(
        root=root,
        run_directory=run_directory,
        pytest_output=run_directory / "pytest.txt",
        result=run_directory / "result.json",
        latest=pair_directory / "latest.json",
        index=root / "index.json",
    )


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


def _index_results(root: Path) -> list[Mapping[str, Any]]:
    results: list[Mapping[str, Any]] = []
    for latest in root.glob("*/datasette-*/latest.json"):
        try:
            payload = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, Mapping):
            results.append(payload)
    return sorted(
        results,
        key=lambda item: (
            str((item.get("package") or {}).get("name", "")),
            str((item.get("datasette") or {}).get("requested_version", "")),
        ),
    )


def store_result(paths: ResultPaths, result: Mapping[str, Any]) -> None:
    if paths.result.exists():
        raise FileExistsError(f"Refusing to overwrite immutable run {paths.result}")
    _atomic_write_json(paths.result, result)
    _atomic_write_json(paths.latest, result)
    run = result.get("run")
    completed_at = run.get("completed_at") if isinstance(run, Mapping) else None
    index = {
        "schema_version": 1,
        "generated_at": completed_at,
        "results": _index_results(paths.root),
    }
    _atomic_write_json(paths.index, index)


def _isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _artifact_path(paths: ResultPaths) -> str:
    try:
        relative = paths.pytest_output.relative_to(paths.root.parent)
    except ValueError:
        relative = paths.pytest_output
    return relative.as_posix()


def _build_result(
    *,
    package_name: str,
    package_version: str,
    source: ReleasedSource,
    datasette_version: str,
    python_version: str,
    run_id: str,
    started: datetime,
    completed: datetime,
    pytest_exit_code: int | None,
    command: Sequence[str],
    summary: Mapping[str, Any],
    paths: ResultPaths,
    detail: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": 1,
        "package": {
            "name": package_name,
            "version": package_version,
            "repository": source.repository,
            "source": {
                "type": "pypi_sdist",
                "url": source.sdist.url,
                "sha256": source.sdist.sha256,
            },
            "test_suite": {
                "type": source.test_suite.kind,
                "repository": source.test_suite.repository,
                "ref": source.test_suite.ref,
                "git_sha": source.test_suite.git_sha,
            },
        },
        "datasette": {
            "requested_version": datasette_version,
            "installed_version": datasette_version
            if pytest_exit_code is not None and summary.get("outcome") != "install_error"
            else None,
        },
        "run": {
            "id": run_id,
            "started_at": _isoformat(started),
            "completed_at": _isoformat(completed),
            "duration_seconds": round((completed - started).total_seconds(), 3),
            "python_version": python_version,
            "platform": platform.platform(),
            "pytest_exit_code": pytest_exit_code,
            "command": list(command),
        },
        **summary,
        "artifacts": {"pytest_output": _artifact_path(paths)},
    }
    if detail:
        result["detail"] = detail
    return result


def execute(args: argparse.Namespace) -> tuple[dict[str, Any], ResultPaths]:
    started = datetime.now(UTC)
    package_payload = pypi_project(args.package)
    info_value = package_payload.get("info")
    if not isinstance(info_value, Mapping):
        raise ValueError(f"PyPI returned no project information for {args.package}")
    package_name_value = info_value.get("name") or args.package
    package_version = info_value.get("version")
    if not isinstance(package_name_value, str) or not isinstance(package_version, str):
        raise ValueError(f"PyPI returned incomplete project information for {args.package}")
    package_name = normalize_package_name(package_name_value)
    sdist = select_sdist(package_payload)

    if args.datasette_version:
        datasette_version = args.datasette_version
    else:
        datasette_version = latest_datasette_alpha(pypi_project("datasette"))
    _safe_version(datasette_version)

    repository = args.repository or github_repository(info_value, package_name)
    if repository is not None and not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
    ):
        raise ValueError(f"Invalid GitHub repository: {repository!r}")
    source = ReleasedSource(
        repository=repository,
        sdist=sdist,
        test_suite=TestSuiteSource(kind="pypi_sdist"),
    )

    run_id = make_run_id(started)
    paths = result_paths(
        args.results_dir.resolve(), package_name, datasette_version, run_id
    )
    paths.run_directory.mkdir(parents=True, exist_ok=False)
    paths.pytest_output.touch()

    report_path = paths.run_directory / ".pytest-report.json"

    with tempfile.TemporaryDirectory(prefix=f"{package_name}-") as temporary:
        temporary_path = Path(temporary)
        archive_filename = PurePosixPath(urlparse(sdist.url).path).name
        if not archive_filename or archive_filename in {".", ".."}:
            raise ValueError(f"PyPI sdist URL has no safe filename: {sdist.url}")
        archive_path = temporary_path / archive_filename
        command = build_pytest_command(
            package_name,
            archive_path,
            datasette_version,
            report_path,
            python_version=args.python_version,
            pytest_args=args.pytest_args,
        )
        try:
            download_sdist(sdist, archive_path)
            source_directory = extract_sdist(
                archive_path, temporary_path / "unpacked"
            )
        except Exception as ex:
            completed = datetime.now(UTC)
            result = _build_result(
                package_name=package_name,
                package_version=package_version,
                source=source,
                datasette_version=datasette_version,
                python_version=args.python_version,
                run_id=run_id,
                started=started,
                completed=completed,
                pytest_exit_code=None,
                command=command,
                summary=empty_summary("runner_error"),
                paths=paths,
                detail=str(ex),
            )
            store_result(paths, result)
            return result, paths

        if repository is not None:
            try:
                tagged_suite = checkout_release_tag(
                    repository,
                    package_name,
                    package_version,
                    temporary_path / "tagged-source",
                )
            except RuntimeError as ex:
                print(
                    f"Could not inspect the exact release tag; using tests "
                    f"included in the PyPI sdist: {ex}",
                    file=sys.stderr,
                )
            else:
                if tagged_suite is not None:
                    source = ReleasedSource(
                        repository=repository,
                        sdist=sdist,
                        test_suite=tagged_suite,
                    )
                    source_directory = temporary_path / "tagged-source"

        print(
            f"Testing released {package_name} {package_version} "
            f"against Datasette {datasette_version}",
            file=sys.stderr,
        )
        print(f"Source distribution: {sdist.url}", file=sys.stderr)
        if source.test_suite.kind == "github_release_tag":
            print(
                f"Test suite: {source.test_suite.repository}@"
                f"{source.test_suite.ref} ({source.test_suite.git_sha})",
                file=sys.stderr,
            )
        else:
            print("Test suite: files included in the PyPI sdist", file=sys.stderr)
        print("$ " + " ".join(command), file=sys.stderr)
        pytest_exit_code = run_and_capture(
            command, source_directory, paths.pytest_output
        )

    report = load_json_report(report_path)
    if report is None:
        summary = empty_summary("install_error")
        detail = "uv or pytest exited before producing a JSON test report"
    else:
        summary = summarize_pytest_report(report, pytest_exit_code)
        detail = None
    report_path.unlink(missing_ok=True)
    completed = datetime.now(UTC)
    result = _build_result(
        package_name=package_name,
        package_version=package_version,
        source=source,
        datasette_version=datasette_version,
        python_version=args.python_version,
        run_id=run_id,
        started=started,
        completed=completed,
        pytest_exit_code=pytest_exit_code,
        command=command,
        summary=summary,
        paths=paths,
        detail=detail,
    )
    store_result(paths, result)
    return result, paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", help="PyPI name of the Datasette plugin")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path(__file__).with_name("results"),
        help="Result directory (default: results next to this script)",
    )
    parser.add_argument(
        "--python",
        dest="python_version",
        default="3.13",
        help="Python version passed to uv (default: 3.13)",
    )
    parser.add_argument(
        "--datasette-version",
        help="Test a specific version instead of resolving the latest 1.0 alpha",
    )
    parser.add_argument(
        "--repository",
        help="Override informational GitHub repository metadata",
    )
    return parser


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if "--" in arguments:
        separator = arguments.index("--")
        runner_arguments = arguments[:separator]
        pytest_arguments = arguments[separator + 1 :]
    else:
        runner_arguments = arguments
        pytest_arguments = []
    args = build_parser().parse_args(runner_arguments)
    args.pytest_args = pytest_arguments
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_arguments(argv)
    result, paths = execute(args)
    print(
        f"Stored {result['outcome']} result in {paths.result}",
        file=sys.stderr,
    )
    # Plugin test and install failures are successfully recorded compatibility data.
    # Infrastructure failures still produce a result but make the command fail.
    return 1 if result["outcome"] == "runner_error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
