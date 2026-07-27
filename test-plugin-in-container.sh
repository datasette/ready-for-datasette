#!/usr/bin/env bash
set -euo pipefail

DATASSETTE_VERSION="${DATASSETTE_VERSION:-1.0a36}"
CONTAINER_IMAGE="${CONTAINER_IMAGE:-ghcr.io/astral-sh/uv:python3.13-bookworm-slim}"
CPUS="${CPUS:-2}"
MEMORY="${MEMORY:-2G}"

usage() {
  cat <<'EOF'
Usage:
  ./test-plugin-in-container.sh OWNER/REPOSITORY [PYTEST_ARGS...]

Example:
  ./test-plugin-in-container.sh simonw/datasette-cluster-map

The repository's current default branch is downloaded as a fresh GitHub zip.
Tests run as `pytest -vv` with Datasette 1.0a36 in an ephemeral Linux VM.

Environment:
  DATASSETTE_VERSION  Datasette version to test (default: 1.0a36)
  CONTAINER_IMAGE     OCI image with uv and Python
                      (default: ghcr.io/astral-sh/uv:python3.13-bookworm-slim)
  CPUS                VM CPU limit (default: 2)
  MEMORY              VM memory limit (default: 2G)
EOF
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 2
fi

REPOSITORY="$1"
shift

if [[ ! "$REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  printf 'Expected a public GitHub repository in OWNER/REPOSITORY form, got: %s\n' \
    "$REPOSITORY" >&2
  exit 2
fi

if ! command -v container >/dev/null 2>&1; then
  printf 'container is not installed or is not on PATH\n' >&2
  exit 127
fi

RUN_ID="$(date -u +%s)-$$"
NETWORK_NAME="datasette-test-network-$RUN_ID"
CONTAINER_NAME="datasette-test-$RUN_ID"

cleanup() {
  local status="$?"
  trap - EXIT
  container delete --force "$CONTAINER_NAME" >/dev/null 2>&1 || true
  container network delete "$NETWORK_NAME" >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

printf 'Pulling sandbox image: %s\n' "$CONTAINER_IMAGE"
container image pull --progress plain "$CONTAINER_IMAGE"

printf 'Creating one-use NAT network: %s\n' "$NETWORK_NAME"
container network create "$NETWORK_NAME"

printf 'Testing https://github.com/%s with Datasette %s\n' \
  "$REPOSITORY" "$DATASSETTE_VERSION"

# The bootstrap script is sent over stdin. No host files, environment variables,
# credentials, SSH agent, sockets, or ports are exposed to the VM.
container run \
  --rm \
  --init \
  --interactive \
  --name "$CONTAINER_NAME" \
  --network "$NETWORK_NAME" \
  --cap-drop ALL \
  --read-only \
  --tmpfs /tmp \
  --tmpfs /work \
  --workdir /work \
  --cpus "$CPUS" \
  --memory "$MEMORY" \
  --ulimit nofile=1024:1024 \
  --env HOME=/work/home \
  --env UV_CACHE_DIR=/work/uv-cache \
  --env PYTHONDONTWRITEBYTECODE=1 \
  "$CONTAINER_IMAGE" \
  sh -s -- "$REPOSITORY" "$DATASSETTE_VERSION" "$@" <<'CONTAINER_SCRIPT'
set -eu

repository="$1"
datasette_version="$2"
shift 2

archive_url="https://github.com/${repository}/archive/HEAD.zip"
mkdir -p "$HOME" "$UV_CACHE_DIR" /work/source

printf 'Downloading %s\n' "$archive_url"
uv run --no-project --no-progress python - "$archive_url" <<'PYTHON'
import shutil
import sys
import zipfile
from pathlib import Path, PurePosixPath
from urllib.request import Request, urlopen

url = sys.argv[1]
archive_path = Path("/work/repository.zip")
source_path = Path("/work/source")
request = Request(url, headers={"User-Agent": "datasette-plugin-sandbox/1"})

with urlopen(request, timeout=60) as response:
    final_url = response.geturl()
    with archive_path.open("wb") as output:
        shutil.copyfileobj(response, output)

with zipfile.ZipFile(archive_path) as archive:
    roots = set()
    for item in archive.infolist():
        path = PurePosixPath(item.filename)
        if path.is_absolute() or ".." in path.parts:
            raise SystemExit(f"Unsafe path in GitHub archive: {item.filename!r}")
        if path.parts:
            roots.add(path.parts[0])
    if len(roots) != 1:
        raise SystemExit(f"Expected one top-level archive directory, found: {roots}")
    archive.extractall(source_path)

print(f"Downloaded: {final_url}")
print(f"Archive root: {next(iter(roots))}")
PYTHON

project_dir=""
for candidate in /work/source/*; do
  if [ -n "$project_dir" ] || [ ! -d "$candidate" ]; then
    printf 'Could not identify a single extracted repository directory\n' >&2
    exit 1
  fi
  project_dir="$candidate"
done
if [ -z "$project_dir" ]; then
  printf 'Could not identify the extracted repository directory\n' >&2
  exit 1
fi
cd "$project_dir"

printf 'Running tests from %s\n' "$project_dir"
printf 'Requested Datasette version: %s\n' "$datasette_version"

# `--no-project` below deliberately disables dependency groups, so extract a
# conventional test group and pass its requirements into the same isolated
# resolution. Also select a conventional test extra if the package has one.
test_requirements="/work/test-requirements.txt"
package_requirement="$(
  uv run --isolated --no-project --quiet python - "$test_requirements" <<'PYTHON'
import re
import sys
import tomllib
from pathlib import Path


CANDIDATES = ("test", "tests", "testing", "dev")
output_path = Path(sys.argv[1])
pyproject_path = Path("pyproject.toml")


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def named_group(groups):
    by_normalized_name = {
        normalized(name): name for name in groups if isinstance(name, str)
    }
    return next(
        (by_normalized_name[name] for name in CANDIDATES if name in by_normalized_name),
        None,
    )


def expand_group(groups, name, resolving=()):
    if name in resolving:
        raise SystemExit("Dependency group cycle: " + " -> ".join((*resolving, name)))
    value = groups.get(name)
    if not isinstance(value, list):
        raise SystemExit(f"Dependency group {name!r} is not an array")
    dependencies = []
    for item in value:
        if isinstance(item, str):
            dependencies.append(item)
        elif isinstance(item, dict) and isinstance(item.get("include-group"), str):
            included_name = item["include-group"]
            if included_name not in groups:
                by_normalized_name = {
                    normalized(group_name): group_name
                    for group_name in groups
                    if isinstance(group_name, str)
                }
                included_name = by_normalized_name.get(
                    normalized(included_name), included_name
                )
            dependencies.extend(
                expand_group(groups, included_name, (*resolving, name))
            )
        else:
            raise SystemExit(
                f"Unsupported item in dependency group {name!r}: {item!r}"
            )
    return dependencies


if pyproject_path.is_file():
    with pyproject_path.open("rb") as file:
        pyproject = tomllib.load(file)
else:
    pyproject = {}

dependencies = []
groups = pyproject.get("dependency-groups")
if isinstance(groups, dict):
    group_name = named_group(groups)
    if group_name is not None:
        dependencies = expand_group(groups, group_name)

if not dependencies:
    tool = pyproject.get("tool")
    uv = tool.get("uv") if isinstance(tool, dict) else None
    legacy = uv.get("dev-dependencies") if isinstance(uv, dict) else None
    if isinstance(legacy, list) and all(isinstance(item, str) for item in legacy):
        dependencies = legacy

unique_dependencies = list(dict.fromkeys(dependencies))
output_path.write_text(
    "# Generated from the package's test dependency group\n"
    + "".join(f"{dependency}\n" for dependency in unique_dependencies)
)

project = pyproject.get("project")
optional = project.get("optional-dependencies") if isinstance(project, dict) else None
extra = named_group(optional) if isinstance(optional, dict) else None
print(f".[{extra}]" if extra is not None else ".")
PYTHON
)"

printf 'Package requirement: %s\n' "$package_requirement"
printf 'Additional test requirements:\n'
sed 's/^/  /' "$test_requirements"

# The package, its runtime dependencies, the exact Datasette version, and its
# test dependencies are resolved together. There is no lower project
# environment whose stale transitive dependencies can leak into the test run.
uv run \
  --isolated \
  --no-project \
  --prerelease allow \
  --with "$package_requirement" \
  --with pytest \
  --with "datasette==$datasette_version" \
  --with-requirements "$test_requirements" \
  python -m pytest -vv "$@"
CONTAINER_SCRIPT
