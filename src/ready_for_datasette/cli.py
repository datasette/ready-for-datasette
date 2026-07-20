"""Check whether a repository is ready to ship as a Datasette plugin."""

from __future__ import annotations

import argparse
import email.parser
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence

import yaml
from packaging.version import InvalidVersion, Version

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 only
    import tomli as tomllib  # type: ignore[no-redef]


ALPHA_DATASETTE = "1.0a37"
REQUIRED_PYTHON_VERSIONS = {"3.10", "3.11", "3.12", "3.13", "3.14"}
CURRENT_ACTION_REFS = {
    "actions/checkout": "v7",
    "actions/setup-python": "v6",
}
TRUSTED_PUBLISHING_ACTION = "pypa/gh-action-pypi-publish@release/v1"
VERSION_MARKER = "CHECK_DATASETTE_VERSION="


@dataclass
class CommandResult:
    args: list[str]
    cwd: Path
    returncode: int
    output: str

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0


class Reporter:
    def __init__(self, *, verbose: bool = False, color: bool = True) -> None:
        self.verbose = verbose
        self.color = color and sys.stdout.isatty()
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def _paint(self, text: str, code: str) -> str:
        if not self.color:
            return text
        return f"\033[{code}m{text}\033[0m"

    def heading(self, title: str) -> None:
        print(f"\n{self._paint(title, '1')}\n{'=' * len(title)}")

    def progress(self, message: str) -> None:
        print(f"\n[....] {message}", flush=True)

    def pass_(self, title: str, *details: str) -> None:
        self.passed += 1
        print(f"\n{self._paint('[PASS]', '32;1')} {title}")
        self._details(details)

    def fail(self, title: str, reason: str, *, fix: str | None = None) -> None:
        self.failed += 1
        print(f"\n{self._paint('[FAIL]', '31;1')} {title}")
        self._labelled("Reason", reason)
        if fix:
            self._labelled("How to fix", fix)

    def skip(self, title: str, reason: str) -> None:
        self.skipped += 1
        print(f"\n{self._paint('[SKIP]', '33;1')} {title}")
        self._labelled("Reason", reason)

    def command_failure(
        self,
        title: str,
        result: CommandResult,
        *,
        fix: str,
    ) -> None:
        command = " ".join(quote_argument(arg) for arg in result.args)
        output = truncate_output(result.output)
        reason = (
            f"Command: {command}\n"
            f"Working directory: {result.cwd}\n"
            f"Exit code: {result.returncode}\n"
            f"Output:\n{indent(output or '(no output)', 4)}"
        )
        self.fail(title, reason, fix=fix)

    def show_successful_command(self, result: CommandResult) -> None:
        if self.verbose and result.output.strip():
            self._labelled("Command output", truncate_output(result.output))

    def _details(self, details: Iterable[str]) -> None:
        for detail in details:
            if detail:
                print(indent(detail, 2))

    def _labelled(self, label: str, value: str) -> None:
        lines = value.rstrip().splitlines() or [""]
        print(f"  {self._paint(label + ':', '1')} {lines[0]}")
        for line in lines[1:]:
            print(f"  {line}")

    def summary(self) -> int:
        self.heading("Summary")
        total = self.passed + self.failed + self.skipped
        print(
            f"Checked: {total}  "
            f"Passed: {self.passed}  "
            f"Failed: {self.failed}  "
            f"Skipped: {self.skipped}"
        )
        if self.failed:
            print(
                self._paint(
                    f"\nNOT READY: {self.failed} check(s) failed.",
                    "31;1",
                )
            )
            return 1
        print(self._paint("\nREADY: every required check passed.", "32;1"))
        return 0


def indent(value: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line for line in value.rstrip().splitlines())


def quote_argument(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:=@+,-]+", value):
        return value
    return repr(value)


def truncate_output(output: str, *, maximum_lines: int = 100) -> str:
    lines = output.rstrip().splitlines()
    if len(lines) <= maximum_lines:
        return "\n".join(lines)
    omitted = len(lines) - maximum_lines
    return f"... ({omitted} earlier line(s) omitted) ...\n" + "\n".join(
        lines[-maximum_lines:]
    )


def run_command(
    args: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> CommandResult:
    try:
        completed = subprocess.run(
            list(args),
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as ex:
        return CommandResult(list(args), cwd, 127, f"Could not run command: {ex}")
    return CommandResult(list(args), cwd, completed.returncode, completed.stdout)


def read_pyproject(path: Path) -> dict[str, Any]:
    with path.open("rb") as fp:
        return tomllib.load(fp)


def dependency_group_requirements(
    pyproject: dict[str, Any],
    group_name: str,
    resolving: tuple[str, ...] = (),
) -> list[str]:
    groups = pyproject.get("dependency-groups", {})
    if not isinstance(groups, dict):
        raise ValueError("dependency-groups must be a table")

    group = groups.get(group_name)
    if group is None:
        return []
    if not isinstance(group, list):
        raise ValueError(f"dependency-groups.{group_name} must be an array")
    if group_name in resolving:
        cycle = " -> ".join((*resolving, group_name))
        raise ValueError(f"dependency group cycle: {cycle}")

    requirements: list[str] = []
    for item in group:
        if isinstance(item, str):
            requirements.append(item)
        elif (
            isinstance(item, dict)
            and set(item) == {"include-group"}
            and isinstance(item["include-group"], str)
        ):
            requirements.extend(
                dependency_group_requirements(
                    pyproject,
                    item["include-group"],
                    (*resolving, group_name),
                )
            )
        else:
            raise ValueError(
                f"unsupported item in dependency-groups.{group_name}: {item!r}"
            )
    return requirements


def test_command(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="ready-for-datasette test",
        description=(
            f"Run a plugin's tests with Datasette {ALPHA_DATASETTE} and the "
            "dependencies from dependency-groups.dev."
        ),
    )
    parser.add_argument(
        "repository", help="plugin repository containing pyproject.toml"
    )
    parser.add_argument(
        "--command",
        action="store_true",
        help="print the uv command without running it",
    )
    args = parser.parse_args(argv)

    repository = Path(args.repository).expanduser().resolve()
    if not repository.is_dir():
        parser.error(f"not a directory: {repository}")

    pyproject_path = repository / "pyproject.toml"
    if not pyproject_path.is_file():
        parser.error(f"pyproject.toml not found: {pyproject_path}")

    try:
        pyproject = read_pyproject(pyproject_path)
        dev_requirements = dependency_group_requirements(pyproject, "dev")
    except (OSError, ValueError, tomllib.TOMLDecodeError) as ex:
        parser.error(f"could not load {pyproject_path}: {ex}")

    requirements = [".", "pytest", f"datasette=={ALPHA_DATASETTE}"]
    for requirement in dev_requirements:
        if requirement not in requirements:
            requirements.append(requirement)

    command = ["uv", "run", "--isolated", "--no-project"]
    for requirement in requirements:
        command.extend(("--with", requirement))
    command.extend(("python", "-m", "pytest"))

    rendered_command = " ".join(quote_argument(argument) for argument in command)
    if args.command:
        print(rendered_command)
        return 0

    print(f"Running tests in {repository}")
    print(rendered_command, flush=True)
    try:
        completed = subprocess.run(command, cwd=repository, check=False)
    except OSError as ex:
        print(f"Could not run uv: {ex}", file=sys.stderr)
        return 127
    return completed.returncode


def check_packaging_files(
    repo: Path, reporter: Reporter
) -> tuple[dict[str, Any] | None, bool]:
    pyproject_path = repo / "pyproject.toml"
    setup_path = repo / "setup.py"
    okay = True

    if not pyproject_path.is_file():
        reporter.fail(
            "Packaging uses pyproject.toml",
            f"Missing required file: {pyproject_path}",
            fix="Migrate the package configuration to pyproject.toml.",
        )
        pyproject = None
        okay = False
    else:
        try:
            pyproject = read_pyproject(pyproject_path)
        except Exception as ex:
            reporter.fail(
                "pyproject.toml is valid TOML",
                f"Could not parse {pyproject_path}: {type(ex).__name__}: {ex}",
                fix="Correct the TOML syntax before running the checker again.",
            )
            pyproject = None
            okay = False
        else:
            reporter.pass_("Packaging uses pyproject.toml", str(pyproject_path))

    if setup_path.exists():
        reporter.fail(
            "Obsolete setup.py has been removed",
            f"Found {setup_path}. This checker requires pyproject.toml-only packaging.",
            fix=(
                "Migrate all remaining metadata and build configuration into "
                "pyproject.toml, update workflows, then delete setup.py."
            ),
        )
        okay = False
    else:
        reporter.pass_("Obsolete setup.py has been removed")

    return pyproject, okay


def check_pyproject_metadata(
    pyproject: dict[str, Any] | None, reporter: Reporter
) -> None:
    if pyproject is None:
        reporter.skip(
            "pyproject.toml metadata uses current formats",
            "pyproject.toml could not be parsed.",
        )
        return

    project = pyproject.get("project")
    if not isinstance(project, dict):
        reporter.fail(
            "pyproject.toml contains a [project] table",
            "No valid [project] table was found.",
            fix="Define the package metadata in a PEP 621 [project] table.",
        )
        return

    problems: list[str] = []
    license_value = project.get("license")
    if isinstance(license_value, dict):
        problems.append(
            "project.license is a deprecated TOML table; use an SPDX string such "
            'as license = "Apache-2.0"'
        )
    if "name" not in project:
        problems.append("project.name is missing")
    if "version" not in project and "version" not in project.get("dynamic", []):
        problems.append("project.version is missing and is not declared dynamic")

    if problems:
        reporter.fail(
            "pyproject.toml metadata uses current formats",
            "\n".join(f"- {problem}" for problem in problems),
            fix="Update the listed [project] fields to current PEP 621 formats.",
        )
    else:
        reporter.pass_("pyproject.toml metadata uses current formats")


def find_warning_blocks(output: str) -> list[str]:
    lines = output.splitlines()
    blocks: list[str] = []
    metadata_terms = (
        "pyproject",
        "project.",
        "license",
        "metadata",
        "classifier",
        "readme",
    )
    for index, line in enumerate(lines):
        if not re.search(r"\bwarning\b", line, re.IGNORECASE):
            continue
        block = "\n".join(lines[index : index + 5]).strip()
        lowered = block.lower()
        if any(term in lowered for term in metadata_terms):
            blocks.append(block)
    return blocks


def workflow_files(repo: Path) -> list[Path]:
    directory = repo / ".github" / "workflows"
    if not directory.is_dir():
        return []
    return sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")])


def load_workflows(
    repo: Path, reporter: Reporter
) -> tuple[list[tuple[Path, dict[str, Any]]], list[Path]]:
    paths = workflow_files(repo)
    if not paths:
        reporter.fail(
            "GitHub Actions workflows exist",
            f"No .yml or .yaml files were found under {repo / '.github/workflows'}.",
            fix="Add test and publishing workflows under .github/workflows/.",
        )
        return [], []

    loaded: list[tuple[Path, dict[str, Any]]] = []
    invalid: list[Path] = []
    for path in paths:
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as ex:
            reporter.fail(
                f"Workflow YAML parses: {path.name}",
                f"{type(ex).__name__}: {ex}",
                fix=f"Correct the YAML syntax in {path}.",
            )
            invalid.append(path)
            continue
        if not isinstance(value, dict):
            reporter.fail(
                f"Workflow YAML parses: {path.name}",
                "The document is not a YAML mapping.",
                fix=f"Correct the workflow structure in {path}.",
            )
            invalid.append(path)
            continue
        loaded.append((path, value))

    if loaded and not invalid:
        reporter.pass_(
            "GitHub Actions workflow YAML parses",
            "\n".join(str(path.relative_to(repo)) for path, _ in loaded),
        )
    return loaded, paths


def iter_jobs(
    workflows: Iterable[tuple[Path, dict[str, Any]]],
) -> Iterable[tuple[Path, str, dict[str, Any], dict[str, Any]]]:
    for path, workflow in workflows:
        jobs = workflow.get("jobs", {})
        if not isinstance(jobs, dict):
            continue
        for job_name, job in jobs.items():
            if isinstance(job, dict):
                yield path, str(job_name), job, workflow


def job_run_text(job: dict[str, Any]) -> str:
    steps = job.get("steps", [])
    if not isinstance(steps, list):
        return ""
    return "\n".join(
        str(step.get("run", ""))
        for step in steps
        if isinstance(step, dict) and "run" in step
    )


def job_uses(job: dict[str, Any]) -> list[str]:
    steps = job.get("steps", [])
    if not isinstance(steps, list):
        return []
    return [
        str(step["uses"]) for step in steps if isinstance(step, dict) and "uses" in step
    ]


def matrix_python_versions(job: dict[str, Any]) -> set[str]:
    strategy = job.get("strategy", {})
    matrix = strategy.get("matrix", {}) if isinstance(strategy, dict) else {}
    if not isinstance(matrix, dict):
        return set()
    values = matrix.get("python-version", [])
    if not isinstance(values, list):
        return set()
    return {str(value).strip() for value in values}


def check_workflow_python_matrix(
    workflows: list[tuple[Path, dict[str, Any]]], repo: Path, reporter: Reporter
) -> None:
    candidates: list[tuple[Path, str, set[str]]] = []
    for path, name, job, _ in iter_jobs(workflows):
        run_text = job_run_text(job)
        if "test" in name.lower() or re.search(r"\bpytest\b", run_text):
            candidates.append((path, name, matrix_python_versions(job)))

    incomplete = [
        candidate
        for candidate in candidates
        if not REQUIRED_PYTHON_VERSIONS.issubset(candidate[2])
    ]
    if candidates and not incomplete:
        details = []
        for path, name, versions in candidates:
            details.append(
                f"{path.relative_to(repo)} job {name!r}: " + ", ".join(sorted(versions))
            )
        reporter.pass_(
            "A test job covers Python 3.10 through 3.14",
            "\n".join(details),
        )
        return

    observed = []
    for path, name, versions in incomplete:
        rendered = (
            ", ".join(sorted(versions)) if versions else "no python-version matrix"
        )
        observed.append(f"{path.relative_to(repo)} job {name!r}: {rendered}")
    reporter.fail(
        "A test job covers Python 3.10 through 3.14",
        (
            "Every test job must have a python-version matrix containing all required "
            "versions: 3.10, 3.11, 3.12, 3.13, and 3.14.\n"
            + (
                "Observed:\n" + indent("\n".join(observed), 2)
                if observed
                else "No test job was found."
            )
        ),
        fix=(
            "Add a test job matrix with quoted version strings "
            '["3.10", "3.11", "3.12", "3.13", "3.14"].'
        ),
    )


def check_action_versions(
    workflows: list[tuple[Path, dict[str, Any]]], repo: Path, reporter: Reporter
) -> None:
    observed: dict[str, list[tuple[Path, str, str]]] = {
        action: [] for action in CURRENT_ACTION_REFS
    }
    for path, job_name, job, _ in iter_jobs(workflows):
        for use in job_uses(job):
            action, separator, ref = use.partition("@")
            if separator and action in observed:
                observed[action].append((path, job_name, ref))

    problems: list[str] = []
    details: list[str] = []
    for action, expected in CURRENT_ACTION_REFS.items():
        uses = observed[action]
        if not uses:
            problems.append(f"{action}@{expected} is not used")
            continue
        for path, job_name, actual in uses:
            location = f"{path.relative_to(repo)} job {job_name!r}"
            details.append(f"{location}: {action}@{actual}")
            if actual != expected:
                problems.append(
                    f"{location} uses {action}@{actual}; expected {action}@{expected}"
                )

    if problems:
        reporter.fail(
            "Core GitHub Actions use current stable versions",
            "\n".join(f"- {problem}" for problem in problems),
            fix=(
                "Update every checkout and setup-python step. The expected current "
                "versions are actions/checkout@v7 and actions/setup-python@v6."
            ),
        )
    else:
        reporter.pass_(
            "Core GitHub Actions use current stable versions",
            "\n".join(details),
        )


def effective_permissions(job: dict[str, Any], workflow: dict[str, Any]) -> Any:
    if "permissions" in job:
        return job["permissions"]
    return workflow.get("permissions", {})


def check_trusted_publishing(
    workflows: list[tuple[Path, dict[str, Any]]], repo: Path, reporter: Reporter
) -> None:
    publishers: list[tuple[Path, str, dict[str, Any], dict[str, Any]]] = []
    for path, name, job, workflow in iter_jobs(workflows):
        if TRUSTED_PUBLISHING_ACTION in job_uses(job):
            publishers.append((path, name, job, workflow))

    problems: list[str] = []
    details: list[str] = []
    if not publishers:
        problems.append(f"No job uses {TRUSTED_PUBLISHING_ACTION}")
    for path, name, job, workflow in publishers:
        permissions = effective_permissions(job, workflow)
        id_token = (
            permissions.get("id-token") if isinstance(permissions, dict) else None
        )
        location = f"{path.relative_to(repo)} job {name!r}"
        if id_token != "write":
            problems.append(f"{location} does not grant permissions.id-token: write")
        else:
            details.append(f"{location}: trusted publisher with id-token: write")

    legacy_patterns = re.compile(
        r"TWINE_PASSWORD|PYPI_TOKEN|twine\s+upload", re.IGNORECASE
    )
    legacy_hits: list[str] = []
    for path, _ in workflows:
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if legacy_patterns.search(line):
                legacy_hits.append(f"{path.relative_to(repo)}:{number}: {line.strip()}")
    if legacy_hits:
        problems.append(
            "Legacy token/twine publishing remains:\n"
            + indent("\n".join(legacy_hits), 2)
        )

    if problems:
        reporter.fail(
            "Publishing uses PyPI trusted publishing",
            "\n".join(f"- {problem}" for problem in problems),
            fix=(
                f"Use {TRUSTED_PUBLISHING_ACTION} in the publish job, grant that "
                "job permissions.id-token: write, and remove token-based twine upload steps."
            ),
        )
    else:
        reporter.pass_("Publishing uses PyPI trusted publishing", "\n".join(details))


def check_workflow_obsolete_references(
    paths: list[Path], repo: Path, reporter: Reporter
) -> None:
    hits: list[str] = []
    for path in paths:
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "setup.py" in line:
                hits.append(f"{path.relative_to(repo)}:{number}: {line.strip()}")
    if hits:
        reporter.fail(
            "Workflows do not reference setup.py",
            "\n".join(hits),
            fix=(
                "Replace setup.py cache paths with pyproject.toml and replace "
                "setup.py build commands with python -m build or uv build."
            ),
        )
    elif paths:
        reporter.pass_("Workflows do not reference setup.py")
    else:
        reporter.skip("Workflows do not reference setup.py", "No workflows were found.")


def check_git_remote(repo: Path, reporter: Reporter) -> None:
    if not (repo / ".git").exists():
        reporter.skip(
            "Git origin uses GitHub SSH URLs",
            "The repository path has no .git directory.",
        )
        return
    fetch = run_command(["git", "remote", "get-url", "origin"], cwd=repo)
    push = run_command(["git", "remote", "get-url", "--push", "origin"], cwd=repo)
    if not fetch.succeeded or not push.succeeded:
        output = "\n".join(part for part in (fetch.output, push.output) if part.strip())
        reporter.fail(
            "Git origin uses GitHub SSH URLs",
            output or "Could not read both fetch and push URLs for origin.",
            fix="Configure an origin remote for the repository.",
        )
        return
    fetch_url = fetch.output.strip()
    push_url = push.output.strip()
    invalid = [
        url for url in (fetch_url, push_url) if not url.startswith("git@github.com:")
    ]
    if invalid:
        reporter.fail(
            "Git origin uses GitHub SSH URLs",
            f"Fetch URL: {fetch_url}\nPush URL:  {push_url}",
            fix=(
                "Change origin to the equivalent git@github.com:OWNER/REPOSITORY.git "
                "URL without changing the owner or repository name."
            ),
        )
    else:
        reporter.pass_(
            "Git origin uses GitHub SSH URLs",
            f"Fetch: {fetch_url}\nPush:  {push_url}",
        )


def wheel_metadata(path: Path) -> tuple[str, str]:
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise ValueError(f"wheel ZIP integrity check failed at {bad_member}")
        metadata_paths = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_paths) != 1:
            raise ValueError(
                f"expected one .dist-info/METADATA file, found {len(metadata_paths)}"
            )
        raw = archive.read(metadata_paths[0]).decode("utf-8", errors="replace")
    message = email.parser.Parser().parsestr(raw)
    name = message.get("Name")
    version = message.get("Version")
    if not name or not version:
        raise ValueError("wheel METADATA is missing Name or Version")
    return name, version


def validate_sdist_members(members: list[tarfile.TarInfo]) -> None:
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe archive path: {member.name}")
        if member.issym() or member.islnk():
            raise ValueError(
                f"archive contains a link, refusing to extract: {member.name}"
            )
        if not (member.isfile() or member.isdir()):
            raise ValueError(
                f"archive contains an unsupported special entry: {member.name}"
            )


def sdist_test_paths(members: list[tarfile.TarInfo]) -> list[str]:
    paths = []
    for member in members:
        path = PurePosixPath(member.name)
        if member.isfile() and path.suffix == ".py" and "tests" in path.parts:
            paths.append(member.name)
    return sorted(paths)


def extract_sdist(path: Path, destination: Path) -> tuple[Path, list[str]]:
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        validate_sdist_members(members)
        tests = sdist_test_paths(members)
        top_levels = {
            PurePosixPath(member.name).parts[0]
            for member in members
            if PurePosixPath(member.name).parts
        }
        if len(top_levels) != 1:
            raise ValueError(
                "source distribution should have one top-level directory; found "
                + ", ".join(sorted(top_levels))
            )
        archive.extractall(destination)
    root = destination / next(iter(top_levels))
    if not (root / "pyproject.toml").is_file():
        raise ValueError(f"extracted sdist has no pyproject.toml at {root}")
    return root, tests


def isolated_environment() -> dict[str, str]:
    env = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX"):
        env.pop(name, None)
    env["UV_NO_PROGRESS"] = "1"
    return env


def remove_lockfile(project: Path) -> None:
    lockfile = project / "uv.lock"
    if lockfile.exists():
        lockfile.unlink()


def pytest_probe(expected_datasette: str) -> str:
    return textwrap.dedent(f"""
        import importlib.metadata
        import sys
        import pytest

        expected = {expected_datasette!r}
        actual = importlib.metadata.version("datasette")
        print("Datasette version under test: " + actual, flush=True)
        if actual != expected:
            print(
                "ERROR: expected Datasette " + expected + " but resolved " + actual,
                file=sys.stderr,
            )
            raise SystemExit(86)
        raise SystemExit(pytest.main())
        """).strip()


def pytest_result_line(output: str) -> str | None:
    for line in reversed(output.splitlines()):
        stripped = line.strip().strip("=").strip()
        if re.search(r"\b\d+ passed\b", stripped):
            return stripped
    return None


def run_isolated_tests(
    project: Path,
    datasette_version: str,
    reporter: Reporter,
    title: str,
) -> bool:
    remove_lockfile(project)
    requirement = f"datasette=={datasette_version}"
    args = [
        "uv",
        "run",
        "--isolated",
        "--with",
        requirement,
        "python",
        "-c",
        pytest_probe(datasette_version),
    ]
    reporter.progress(f"{title}: resolving {requirement} and running the sdist tests")
    result = run_command(args, cwd=project, env=isolated_environment())
    remove_lockfile(project)
    if result.succeeded:
        test_result = pytest_result_line(result.output)
        details = [f"Datasette: {datasette_version}"]
        if test_result:
            details.append(f"Tests: {test_result}")
        reporter.pass_(title, "\n".join(details))
        reporter.show_successful_command(result)
        return True
    reporter.command_failure(
        title,
        result,
        fix=(
            f"Run the shown command in the extracted sdist, fix the test or dependency "
            f"failure against Datasette {datasette_version}, rebuild, and try again."
        ),
    )
    return False


def discover_latest_stable_datasette(cwd: Path, reporter: Reporter) -> str | None:
    code = (
        "import importlib.metadata; "
        f'print("{VERSION_MARKER}" + importlib.metadata.version("datasette"))'
    )
    args = [
        "uv",
        "run",
        "--isolated",
        "--no-project",
        "--prerelease",
        "disallow",
        "--with",
        "datasette",
        "python",
        "-c",
        code,
    ]
    reporter.progress("Discovering the latest stable Datasette release")
    result = run_command(args, cwd=cwd, env=isolated_environment())
    if not result.succeeded:
        reporter.command_failure(
            "Latest stable Datasette can be resolved",
            result,
            fix="Check network/index access and confirm Datasette can be resolved from PyPI.",
        )
        return None
    matches = re.findall(
        rf"^{re.escape(VERSION_MARKER)}(.+)$", result.output, re.MULTILINE
    )
    if len(matches) != 1:
        reporter.fail(
            "Latest stable Datasette can be resolved",
            f"Could not identify the resolved version in output:\n{truncate_output(result.output)}",
            fix="Re-run with --verbose and check uv's resolver output.",
        )
        return None
    version_text = matches[0].strip()
    try:
        parsed = Version(version_text)
    except InvalidVersion:
        reporter.fail(
            "Latest stable Datasette can be resolved",
            f"Resolver returned an invalid version: {version_text!r}",
            fix="Check the Datasette package metadata returned by the configured index.",
        )
        return None
    if parsed.is_prerelease:
        reporter.fail(
            "Latest stable Datasette can be resolved",
            f"Resolver returned prerelease {version_text} despite --prerelease disallow.",
            fix="Check uv's configured package indexes and prerelease settings.",
        )
        return None
    reporter.pass_("Latest stable Datasette can be resolved", version_text)
    return version_text


def package_is_alpha(version_text: str) -> bool:
    parsed = Version(version_text)
    return parsed.pre is not None and parsed.pre[0] == "a"


def check_command(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build and inspect a Datasette plugin, then test its source distribution "
            "in isolated uv environments."
        ),
        epilog=(
            "To run a plugin's tests, use: ready-for-datasette test PATH-TO-PLUGIN"
        ),
    )
    parser.add_argument(
        "repository",
        nargs="?",
        default=".",
        help="repository to check (default: current directory)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="show output from successful build and test commands",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="disable colored status labels",
    )
    args = parser.parse_args(argv)

    reporter = Reporter(verbose=args.verbose, color=not args.no_color)
    repo = Path(args.repository).expanduser().resolve()
    reporter.heading("Datasette plugin readiness check")
    print(f"Repository: {repo}")

    if not repo.is_dir():
        reporter.fail(
            "Repository directory exists",
            f"Not a directory: {repo}",
            fix="Pass the path to a Datasette plugin repository.",
        )
        return reporter.summary()

    if shutil.which("uv") is None:
        reporter.fail(
            "uv is available",
            "Could not find the uv executable on PATH.",
            fix="Install uv and ensure it is available on PATH.",
        )
        return reporter.summary()
    reporter.pass_("uv is available", shutil.which("uv") or "uv")

    pyproject, _ = check_packaging_files(repo, reporter)
    check_pyproject_metadata(pyproject, reporter)
    check_git_remote(repo, reporter)

    workflows, workflow_paths = load_workflows(repo, reporter)
    if workflows:
        check_workflow_python_matrix(workflows, repo, reporter)
        check_action_versions(workflows, repo, reporter)
        check_trusted_publishing(workflows, repo, reporter)
    else:
        reporter.skip(
            "A test job covers Python 3.10 through 3.14", "No valid workflows loaded."
        )
        reporter.skip(
            "Core GitHub Actions use current stable versions",
            "No valid workflows loaded.",
        )
        reporter.skip(
            "Publishing uses PyPI trusted publishing", "No valid workflows loaded."
        )
    check_workflow_obsolete_references(workflow_paths, repo, reporter)

    if pyproject is None:
        reporter.skip("uv build succeeds", "A valid pyproject.toml is required.")
        reporter.skip(
            "Build emits no pyproject metadata warnings", "The build was not run."
        )
        reporter.skip(
            "dist contains a wheel and source distribution", "The build was not run."
        )
        reporter.skip(
            "Source distribution contains tests", "No source distribution was built."
        )
        reporter.skip(
            "Source distribution can be unpacked safely",
            "No source distribution was built.",
        )
        reporter.skip(
            f"Source distribution tests pass with Datasette {ALPHA_DATASETTE}",
            "No source distribution was built.",
        )
        reporter.skip(
            "Source distribution tests pass with latest stable Datasette",
            "Package version is unavailable.",
        )
        return reporter.summary()

    dist = repo / "dist"
    try:
        if dist.exists():
            shutil.rmtree(dist)
    except OSError as ex:
        reporter.fail(
            "Existing dist directory can be removed",
            f"Could not remove {dist}: {type(ex).__name__}: {ex}",
            fix="Correct the permissions or remove the generated dist directory manually.",
        )
        reporter.skip(
            "uv build succeeds",
            "The existing dist directory could not be removed safely.",
        )
        reporter.skip(
            "Build emits no pyproject metadata warnings", "The build was not run."
        )
        reporter.skip(
            "dist contains a wheel and source distribution", "The build was not run."
        )
        reporter.skip(
            "Source distribution contains tests", "No source distribution was built."
        )
        reporter.skip(
            "Source distribution can be unpacked safely",
            "No source distribution was built.",
        )
        reporter.skip(
            f"Source distribution tests pass with Datasette {ALPHA_DATASETTE}",
            "No source distribution was built.",
        )
        reporter.skip(
            "Source distribution tests pass with latest stable Datasette",
            "No source distribution was built.",
        )
        return reporter.summary()
    reporter.progress("Running a clean uv build")
    build = run_command(["uv", "build"], cwd=repo, env=isolated_environment())
    if not build.succeeded:
        reporter.command_failure(
            "uv build succeeds",
            build,
            fix="Correct the pyproject.toml/build backend errors shown above.",
        )
        reporter.skip("Build emits no pyproject metadata warnings", "uv build failed.")
        reporter.skip(
            "dist contains a wheel and source distribution", "uv build failed."
        )
        reporter.skip(
            "Source distribution contains tests",
            "No usable source distribution was built.",
        )
        reporter.skip(
            "Source distribution can be unpacked safely",
            "No usable source distribution was built.",
        )
        reporter.skip(
            f"Source distribution tests pass with Datasette {ALPHA_DATASETTE}",
            "No usable source distribution was built.",
        )
        reporter.skip(
            "Source distribution tests pass with latest stable Datasette",
            "Package version is unavailable.",
        )
        return reporter.summary()
    reporter.pass_("uv build succeeds")
    reporter.show_successful_command(build)

    warning_blocks = find_warning_blocks(build.output)
    if warning_blocks:
        reporter.fail(
            "Build emits no pyproject metadata warnings",
            "\n\n".join(warning_blocks),
            fix=(
                "Update the indicated pyproject.toml metadata. For example, replace "
                "a project.license table with a valid SPDX license string."
            ),
        )
    else:
        reporter.pass_("Build emits no pyproject metadata warnings")

    wheels = sorted(dist.glob("*.whl")) if dist.is_dir() else []
    sdists = sorted(dist.glob("*.tar.gz")) if dist.is_dir() else []
    if len(wheels) != 1 or len(sdists) != 1:
        found = sorted(path.name for path in dist.iterdir()) if dist.is_dir() else []
        reporter.fail(
            "dist contains a wheel and source distribution",
            (
                f"Expected exactly one .whl and one .tar.gz after a clean build; "
                f"found {len(wheels)} wheel(s) and {len(sdists)} source distribution(s).\n"
                f"dist contents: {', '.join(found) if found else '(empty or missing)'}"
            ),
            fix="Configure the build backend so uv build creates both distribution formats.",
        )
        reporter.skip(
            "Source distribution contains tests",
            "There is not exactly one source distribution to inspect.",
        )
        reporter.skip(
            "Source distribution can be unpacked safely",
            "There is not exactly one source distribution to unpack.",
        )
        reporter.skip(
            f"Source distribution tests pass with Datasette {ALPHA_DATASETTE}",
            "There is not exactly one source distribution to test.",
        )
        reporter.skip(
            "Source distribution tests pass with latest stable Datasette",
            "Package version is unavailable.",
        )
        return reporter.summary()
    reporter.pass_(
        "dist contains a wheel and source distribution",
        f"Wheel: {wheels[0].name}\nSource: {sdists[0].name}",
    )

    package_name: str | None = None
    package_version: str | None = None
    try:
        package_name, package_version = wheel_metadata(wheels[0])
        Version(package_version)
    except (OSError, ValueError, zipfile.BadZipFile, InvalidVersion) as ex:
        reporter.fail(
            "Wheel contains valid package metadata",
            f"{type(ex).__name__}: {ex}",
            fix="Correct the wheel/package metadata and rebuild.",
        )
    else:
        reporter.pass_(
            "Wheel contains valid package metadata",
            f"Package: {package_name}\nVersion: {package_version}",
        )

    with tempfile.TemporaryDirectory(prefix="check-datasette-plugin-") as temporary:
        unpack_directory = Path(temporary) / "unpacked"
        unpack_directory.mkdir()
        try:
            extracted_root, tests = extract_sdist(sdists[0], unpack_directory)
        except (OSError, ValueError, tarfile.TarError) as ex:
            reporter.fail(
                "Source distribution can be unpacked safely",
                f"{type(ex).__name__}: {ex}",
                fix="Rebuild a conventional .tar.gz sdist containing one safe top-level directory.",
            )
            reporter.skip(
                "Source distribution contains tests",
                "The source distribution could not be inspected safely.",
            )
            reporter.skip(
                f"Source distribution tests pass with Datasette {ALPHA_DATASETTE}",
                "The source distribution could not be unpacked.",
            )
            reporter.skip(
                "Source distribution tests pass with latest stable Datasette",
                "The source distribution could not be unpacked.",
            )
            return reporter.summary()

        reporter.pass_(
            "Source distribution can be unpacked safely",
            f"Temporary project: {extracted_root}",
        )
        if tests:
            reporter.pass_("Source distribution contains tests", "\n".join(tests))
        else:
            reporter.fail(
                "Source distribution contains tests",
                f"No Python files under tests/ were found in {sdists[0].name}.",
                fix=(
                    "Add tests/ to the build backend's sdist inclusion configuration, "
                    "rebuild, and inspect the archive again."
                ),
            )

        if tests:
            run_isolated_tests(
                extracted_root,
                ALPHA_DATASETTE,
                reporter,
                f"Source distribution tests pass with Datasette {ALPHA_DATASETTE}",
            )
        else:
            reporter.skip(
                f"Source distribution tests pass with Datasette {ALPHA_DATASETTE}",
                "The source distribution contains no test files.",
            )

        if package_version is None:
            reporter.skip(
                "Source distribution tests pass with latest stable Datasette",
                "The package version could not be read from the wheel.",
            )
        else:
            try:
                alpha_package = package_is_alpha(package_version)
            except InvalidVersion:
                reporter.skip(
                    "Source distribution tests pass with latest stable Datasette",
                    f"The package version is invalid: {package_version!r}.",
                )
            else:
                if alpha_package:
                    reporter.skip(
                        "Source distribution tests pass with latest stable Datasette",
                        f"Package {package_name} {package_version} is an alpha release.",
                    )
                elif not tests:
                    reporter.skip(
                        "Source distribution tests pass with latest stable Datasette",
                        "The source distribution contains no test files.",
                    )
                else:
                    stable = discover_latest_stable_datasette(extracted_root, reporter)
                    if stable is not None:
                        run_isolated_tests(
                            extracted_root,
                            stable,
                            reporter,
                            "Source distribution tests pass with latest stable Datasette",
                        )
                    else:
                        reporter.skip(
                            "Source distribution tests pass with latest stable Datasette",
                            "The latest stable Datasette version could not be resolved.",
                        )

    return reporter.summary()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["test"]:
        return test_command(arguments[1:])
    return check_command(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
