#!/usr/bin/env bash
set -u -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATASSETTE_VERSION="${DATASSETTE_VERSION:-1.0a35}"
PYTHON_VERSION="${PYTHON_VERSION:-3.13}"
CHECKOUTS_DIR="${CHECKOUTS_DIR:-$ROOT/checkouts}"

usage() {
  cat <<'EOF'
Usage:
  ./test-plugin.sh PACKAGE [PYTEST_ARGS...]

Environment:
  DATASSETTE_VERSION  Datasette version to test against (default: 1.0a35)
  PYTHON_VERSION      Python version passed to uv (default: 3.13)
  CHECKOUTS_DIR       Directory for cached GitHub checkouts (default: ./checkouts)
EOF
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 2
fi

PLUGIN="$1"
shift
PYTEST_ARGS=("$@")

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$CHECKOUTS_DIR/_runs/$PLUGIN/$RUN_ID"
mkdir -p "$RUN_DIR"

CHECKOUT_DIR=""

log() {
  printf '%s\n' "$*"
}

finish() {
  local result_code="$1"
  local result="$2"
  local detail="$3"
  local exit_code="$4"

  printf '\nRESULT: %s\n' "$result"
  printf 'RESULT_CODE: %s\n' "$result_code"
  printf 'DETAIL: %s\n' "$detail"
  printf 'LOG_DIR: %s\n' "$RUN_DIR"
  if [[ -n "$CHECKOUT_DIR" ]]; then
    printf 'CHECKOUT: %s\n' "$CHECKOUT_DIR"
  fi
  exit "$exit_code"
}

run_logged() {
  local logfile="$1"
  shift
  {
    printf '$'
    printf ' %q' "$@"
    printf '\n'
  } | tee -a "$logfile"
  "$@" 2>&1 | tee -a "$logfile"
  local status="${PIPESTATUS[0]}"
  printf 'exit status: %s\n' "$status" >> "$logfile"
  return "$status"
}

run_in_checkout() {
  local logfile="$1"
  shift
  (
    cd "$CHECKOUT_DIR" || exit 1
    run_logged "$logfile" "$@"
  )
}

field_from_file() {
  local key="$1"
  local file="$2"
  awk -F '\t' -v key="$key" '$1 == key {print substr($0, length($1) + 2); exit}' "$file"
}

discover_from_installed_metadata() {
  local outfile="$1"
  local errfile="$2"
  uv run \
    --isolated \
    --python "$PYTHON_VERSION" \
    --prerelease allow \
    --with "$PLUGIN" \
    --no-progress \
    python - "$PLUGIN" >"$outfile" 2>"$errfile" <<'PY'
import importlib.metadata as metadata
import re
import sys
from urllib.parse import urlparse

package = sys.argv[1]


def github_clone_url(raw_url):
    if not raw_url:
        return None
    url = raw_url.strip()
    if url.startswith("git+"):
        url = url[4:]
    ssh_match = re.search(r"github\.com[:/]([^/\s]+)/([^/\s#?]+)", url)
    if ssh_match:
        owner, repo = ssh_match.groups()
    else:
        parsed = urlparse(url)
        if parsed.netloc.lower() != "github.com":
            return None
        bits = [bit for bit in parsed.path.split("/") if bit]
        if len(bits) < 2:
            return None
        owner, repo = bits[0], bits[1]
    repo = repo.removesuffix(".git")
    return f"https://github.com/{owner}/{repo}.git"


dist = metadata.distribution(package)
meta = dist.metadata
urls = []
for value in meta.get_all("Project-URL", []):
    if "," in value:
        label, url = value.split(",", 1)
    else:
        label, url = "Project-URL", value
    urls.append((label.strip(), url.strip()))
for key in ("Home-page", "Download-URL"):
    value = meta.get(key)
    if value:
        urls.append((key, value.strip()))

package_normalized = package.lower().replace("_", "-")
candidates = []
for label, url in urls:
    clone_url = github_clone_url(url)
    if not clone_url:
        continue
    repo = clone_url.rsplit("/", 1)[-1].removesuffix(".git").lower()
    label_lower = label.lower()
    score = 0
    if repo == package_normalized:
        score += 30
    if package_normalized in clone_url.lower():
        score += 10
    if label_lower in {"source", "source code", "repository", "homepage", "home-page"}:
        score += 5
    if label_lower in {"issues", "ci", "changelog", "documentation"}:
        score -= 5
    candidates.append((score, clone_url))

candidates.sort(reverse=True)
entry_points = sorted(ep.name for ep in dist.entry_points if ep.group == "datasette")

print(f"github_url\t{candidates[0][1] if candidates else ''}")
print(f"is_datasette_plugin\t{'yes' if entry_points else 'no'}")
print(f"datasette_entry_points\t{','.join(entry_points)}")
PY
}

discover_from_pypi_json() {
  local outfile="$1"
  local errfile="$2"
  uv run \
    --no-project \
    --python "$PYTHON_VERSION" \
    --no-progress \
    python - "$PLUGIN" >"$outfile" 2>"$errfile" <<'PY'
import json
import re
import sys
from urllib.parse import urlparse
from urllib.request import urlopen

package = sys.argv[1]


def github_clone_url(raw_url):
    if not raw_url:
        return None
    url = raw_url.strip()
    if url.startswith("git+"):
        url = url[4:]
    ssh_match = re.search(r"github\.com[:/]([^/\s]+)/([^/\s#?]+)", url)
    if ssh_match:
        owner, repo = ssh_match.groups()
    else:
        parsed = urlparse(url)
        if parsed.netloc.lower() != "github.com":
            return None
        bits = [bit for bit in parsed.path.split("/") if bit]
        if len(bits) < 2:
            return None
        owner, repo = bits[0], bits[1]
    repo = repo.removesuffix(".git")
    return f"https://github.com/{owner}/{repo}.git"


with urlopen(f"https://pypi.org/pypi/{package}/json", timeout=30) as response:
    payload = json.load(response)

info = payload.get("info") or {}
urls = []
for label, url in (info.get("project_urls") or {}).items():
    urls.append((label, url))
for key in ("home_page", "download_url"):
    value = info.get(key)
    if value:
        urls.append((key, value))

package_normalized = package.lower().replace("_", "-")
candidates = []
for label, url in urls:
    clone_url = github_clone_url(url)
    if not clone_url:
        continue
    repo = clone_url.rsplit("/", 1)[-1].removesuffix(".git").lower()
    label_lower = label.lower()
    score = 0
    if repo == package_normalized:
        score += 30
    if package_normalized in clone_url.lower():
        score += 10
    if label_lower in {"source", "source code", "repository", "homepage", "home-page"}:
        score += 5
    if label_lower in {"issues", "ci", "changelog", "documentation"}:
        score -= 5
    candidates.append((score, clone_url))

candidates.sort(reverse=True)
print(f"github_url\t{candidates[0][1] if candidates else ''}")
print("is_datasette_plugin\tunknown")
print("datasette_entry_points\t")
PY
}

check_datasette_plugin_in_env() {
  local env_dir="$1"
  local outfile="$2"
  local errfile="$3"
  (
    cd "$CHECKOUT_DIR" || exit 1
    export VIRTUAL_ENV="$env_dir"
    uv run --active --no-sync --no-progress python - "$PLUGIN" >"$outfile" 2>"$errfile" <<'PY'
import importlib.metadata as metadata
import sys

package = sys.argv[1]
dist = metadata.distribution(package)
entry_points = sorted(ep.name for ep in dist.entry_points if ep.group == "datasette")
print(",".join(entry_points))
raise SystemExit(0 if entry_points else 1)
PY
  )
}

datasette_version_in_env() {
  local env_dir="$1"
  (
    cd "$CHECKOUT_DIR" || exit 1
    export VIRTUAL_ENV="$env_dir"
    uv run --active --no-sync --no-progress python -c 'import datasette; print(datasette.__version__)'
  )
}

dependency_groups_for_checkout() {
  if [[ ! -f "$CHECKOUT_DIR/pyproject.toml" ]]; then
    return 0
  fi
  uv run \
    --no-project \
    --python "$PYTHON_VERSION" \
    --no-progress \
    python - "$CHECKOUT_DIR/pyproject.toml" <<'PY'
import sys
import tomllib

with open(sys.argv[1], "rb") as fp:
    pyproject = tomllib.load(fp)

groups = set((pyproject.get("dependency-groups") or {}).keys())
groups.update(
    (pyproject.get("tool", {}).get("uv", {}).get("dependency-groups") or {}).keys()
)
for group in sorted(groups):
    print(group)
PY
}

install_environment() {
  local case_name="$1"
  local env_dir="$2"
  local override_file="${3:-}"
  local prerelease_mode="${4:-if-necessary-or-explicit}"
  local logfile="$RUN_DIR/$case_name-install.log"
  local pip_args
  pip_args=(uv pip install --python "$env_dir/bin/python" --prerelease "$prerelease_mode")
  if [[ -n "$override_file" ]]; then
    pip_args+=(--overrides "$override_file")
  fi

  : >"$logfile"
  run_logged "$logfile" uv venv --python "$PYTHON_VERSION" --clear "$env_dir" || return 1
  run_in_checkout "$logfile" "${pip_args[@]}" -e . || return 1

  local extra
  for extra in test tests dev; do
    run_in_checkout "$logfile" "${pip_args[@]}" -e ".[${extra}]" || true
  done

  local groups=()
  local discovered_group
  while IFS= read -r discovered_group; do
    case "$discovered_group" in
      test|tests|dev)
        groups+=("$discovered_group")
        ;;
    esac
  done < <(dependency_groups_for_checkout || true)

  local group
  if [[ ${#groups[@]} -gt 0 ]]; then
    for group in "${groups[@]}"; do
      run_in_checkout "$logfile" "${pip_args[@]}" --group "$group" || true
    done
  fi

  local req
  for req in test-requirements.txt requirements-test.txt requirements-dev.txt dev-requirements.txt requirements.txt; do
    if [[ -f "$CHECKOUT_DIR/$req" ]]; then
      run_in_checkout "$logfile" "${pip_args[@]}" -r "$req" || return 1
    fi
  done

  run_in_checkout "$logfile" "${pip_args[@]}" pytest pytest-asyncio pytest-mock pytest-httpx || return 1
}

run_pytest() {
  local case_name="$1"
  local env_dir="$2"
  local logfile="$RUN_DIR/$case_name-pytest.log"

  : >"$logfile"
  (
    cd "$CHECKOUT_DIR" || exit 1
    export VIRTUAL_ENV="$env_dir"
    if [[ ${#PYTEST_ARGS[@]} -gt 0 ]]; then
      run_logged "$logfile" uv run --active --no-sync --no-progress pytest "${PYTEST_ARGS[@]}"
    else
      run_logged "$logfile" uv run --active --no-sync --no-progress pytest
    fi
  )
}

log "Discovering $PLUGIN metadata from PyPI installation"
DISCOVERY_FILE="$RUN_DIR/discovery.tsv"
DISCOVERY_ERR="$RUN_DIR/discovery.err"
if ! discover_from_installed_metadata "$DISCOVERY_FILE" "$DISCOVERY_ERR"; then
  log "Installed metadata discovery failed; falling back to PyPI JSON"
  DISCOVERY_FILE="$RUN_DIR/discovery-pypi-json.tsv"
  DISCOVERY_ERR="$RUN_DIR/discovery-pypi-json.err"
  if ! discover_from_pypi_json "$DISCOVERY_FILE" "$DISCOVERY_ERR"; then
    finish \
      "no-github-repo" \
      "couldn't figure out the GitHub repo" \
      "Could not install $PLUGIN for metadata and could not read useful PyPI JSON. See $DISCOVERY_ERR." \
      10
  fi
fi

GITHUB_URL="$(field_from_file github_url "$DISCOVERY_FILE")"
IS_DATASETTE_PLUGIN="$(field_from_file is_datasette_plugin "$DISCOVERY_FILE")"
ENTRY_POINTS="$(field_from_file datasette_entry_points "$DISCOVERY_FILE")"

if [[ "$IS_DATASETTE_PLUGIN" == "no" ]]; then
  finish \
    "not-datasette-plugin" \
    "turns out it was not actually a Datasette plugin" \
    "$PLUGIN does not declare any entry points in the 'datasette' group." \
    11
fi

if [[ -z "$GITHUB_URL" ]]; then
  finish \
    "no-github-repo" \
    "couldn't figure out the GitHub repo" \
    "No GitHub repository URL was found in $PLUGIN metadata." \
    10
fi

CHECKOUT_DIR="$CHECKOUTS_DIR/$PLUGIN"
mkdir -p "$CHECKOUTS_DIR"

if [[ -d "$CHECKOUT_DIR/.git" ]]; then
  log "Using cached checkout at $CHECKOUT_DIR"
  EXISTING_ORIGIN="$(git -C "$CHECKOUT_DIR" remote get-url origin 2>/dev/null || true)"
  if [[ "$EXISTING_ORIGIN" != "$GITHUB_URL" && "$EXISTING_ORIGIN" != "${GITHUB_URL%.git}" ]]; then
    finish \
      "environment-failure" \
      "tests fail for reasons other than a Datasette 1.0 compatibility problem" \
      "Cached checkout origin is $EXISTING_ORIGIN, expected $GITHUB_URL." \
      20
  fi
  if ! run_logged "$RUN_DIR/git-pull.log" git -C "$CHECKOUT_DIR" pull --ff-only; then
    finish \
      "environment-failure" \
      "tests fail for reasons other than a Datasette 1.0 compatibility problem" \
      "Could not update cached checkout with git pull --ff-only." \
      20
  fi
elif [[ -e "$CHECKOUT_DIR" ]]; then
  finish \
    "environment-failure" \
    "tests fail for reasons other than a Datasette 1.0 compatibility problem" \
    "$CHECKOUT_DIR exists but is not a Git checkout." \
    20
else
  log "Cloning $GITHUB_URL to $CHECKOUT_DIR"
  if ! run_logged "$RUN_DIR/git-clone.log" git clone "$GITHUB_URL" "$CHECKOUT_DIR"; then
    finish \
      "environment-failure" \
      "tests fail for reasons other than a Datasette 1.0 compatibility problem" \
      "git clone failed for $GITHUB_URL." \
      20
  fi
fi

BASELINE_ENV="$CHECKOUT_DIR/.venv-ready-baseline"
DATASSETTE_ENV="$CHECKOUT_DIR/.venv-ready-datasette-$DATASSETTE_VERSION"
OVERRIDE_FILE="$RUN_DIR/datasette-override.txt"
printf 'datasette==%s\n' "$DATASSETTE_VERSION" >"$OVERRIDE_FILE"

log "Installing baseline environment using the plugin's declared dependencies"
if ! install_environment baseline "$BASELINE_ENV"; then
  log "Baseline install failed with conservative prerelease handling; retrying with --prerelease allow"
  if ! install_environment baseline "$BASELINE_ENV" "" "allow"; then
    finish \
      "environment-failure" \
      "tests fail for reasons other than a Datasette 1.0 compatibility problem" \
      "Baseline dependency installation failed before forcing Datasette $DATASSETTE_VERSION." \
      20
  fi
fi

if [[ "$IS_DATASETTE_PLUGIN" == "unknown" ]]; then
  if ! check_datasette_plugin_in_env "$BASELINE_ENV" "$RUN_DIR/entry-points.txt" "$RUN_DIR/entry-points.err"; then
    finish \
      "not-datasette-plugin" \
      "turns out it was not actually a Datasette plugin" \
      "$PLUGIN installed successfully but does not declare any entry points in the 'datasette' group." \
      11
  fi
  ENTRY_POINTS="$(cat "$RUN_DIR/entry-points.txt")"
fi

BASELINE_DATASETTE_VERSION="$(datasette_version_in_env "$BASELINE_ENV" 2>"$RUN_DIR/baseline-datasette-version.err" || true)"
printf '%s\n' "$BASELINE_DATASETTE_VERSION" >"$RUN_DIR/baseline-datasette-version.txt"
log "Baseline Datasette version: ${BASELINE_DATASETTE_VERSION:-not installed}"
if [[ -n "$ENTRY_POINTS" ]]; then
  log "Datasette entry points: $ENTRY_POINTS"
fi

log "Running baseline tests"
if ! run_pytest baseline "$BASELINE_ENV"; then
  if [[ "$BASELINE_DATASETTE_VERSION" == "$DATASSETTE_VERSION" ]]; then
    finish \
      "compatibility-failure" \
      "tests fail indicating datasette 1.0 compatibility bug" \
      "The test run failed with Datasette $DATASSETTE_VERSION; the baseline environment had already resolved to that version." \
      30
  else
    finish \
      "environment-failure" \
      "tests fail for reasons other than a Datasette 1.0 compatibility problem" \
      "The baseline test run failed before forcing Datasette $DATASSETTE_VERSION." \
      20
  fi
fi

if [[ "$BASELINE_DATASETTE_VERSION" == "$DATASSETTE_VERSION" ]]; then
  finish \
    "pass" \
    "tests pass, hooray!" \
    "$PLUGIN passed its tests with Datasette $DATASSETTE_VERSION; no second forced run was needed." \
    0
fi

log "Installing Datasette $DATASSETTE_VERSION environment with dependency override"
if ! install_environment "datasette-$DATASSETTE_VERSION" "$DATASSETTE_ENV" "$OVERRIDE_FILE"; then
  finish \
    "compatibility-failure" \
    "tests fail indicating datasette 1.0 compatibility bug" \
    "Baseline passed, but dependency installation failed with Datasette $DATASSETTE_VERSION forced." \
    30
fi

ACTUAL_DATASETTE_VERSION="$(datasette_version_in_env "$DATASSETTE_ENV" 2>"$RUN_DIR/datasette-version.err" || true)"
printf '%s\n' "$ACTUAL_DATASETTE_VERSION" >"$RUN_DIR/datasette-version.txt"
if [[ "$ACTUAL_DATASETTE_VERSION" != "$DATASSETTE_VERSION" ]]; then
  finish \
    "environment-failure" \
    "tests fail for reasons other than a Datasette 1.0 compatibility problem" \
    "Expected Datasette $DATASSETTE_VERSION but found ${ACTUAL_DATASETTE_VERSION:-nothing}; refusing to run tests." \
    20
fi
log "Confirmed Datasette version: $ACTUAL_DATASETTE_VERSION"

log "Running tests against Datasette $DATASSETTE_VERSION"
if ! run_pytest "datasette-$DATASSETTE_VERSION" "$DATASSETTE_ENV"; then
  finish \
    "compatibility-failure" \
    "tests fail indicating datasette 1.0 compatibility bug" \
    "Baseline passed, but tests failed with Datasette $DATASSETTE_VERSION forced." \
    30
fi

finish \
  "pass" \
  "tests pass, hooray!" \
  "$PLUGIN passed its baseline tests and also passed with Datasette $DATASSETTE_VERSION forced." \
  0
