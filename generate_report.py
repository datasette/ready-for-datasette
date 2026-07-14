#!/usr/bin/env python3
"""Generate the Ready for Datasette progress report and flat plugin JSON."""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from run_plugin_tests import normalize_package_name

DEFAULT_REPOSITORY_URL = "https://github.com/datasette/ready-for-datasette"
STATUS_LABELS = {
    "ready": "Ready",
    "not_ready": "Tests failing",
    "test_error": "Test environment error",
    "no_tests": "No tests found",
    "outdated": "Retest needed",
    "untested": "Not tested",
    "unreleased": "Not released",
}
STATUS_DESCRIPTIONS = {
    "ready": "The latest release passed against the tested Datasette alpha.",
    "not_ready": "The latest release completed its suite with test failures.",
    "test_error": "The suite could not produce a reliable compatibility verdict.",
    "no_tests": "Pytest did not discover any tests in the released source.",
    "outdated": "A previous release was tested; the current release still needs a run.",
    "untested": "The released package has not reached the scoreboard yet.",
    "unreleased": "The repository does not currently have a PyPI release.",
}
STATUS_ORDER = tuple(STATUS_LABELS)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as ex:
        raise ValueError(f"Could not read {path}: {ex}") from ex


def _object(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _integer(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _number(value: Any) -> int | float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _natural_key(value: str) -> tuple[Any, ...]:
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", value)
    )


def _completed_at(result: Mapping[str, Any]) -> str:
    return _string(_object(result.get("run")).get("completed_at")) or ""


def _result_name(result: Mapping[str, Any]) -> str | None:
    name = _string(_object(result.get("package")).get("name"))
    if name is None:
        return None
    try:
        return normalize_package_name(name)
    except ValueError:
        return None


def _status(
    latest_version: str | None,
    result: Mapping[str, Any] | None,
) -> str:
    if latest_version is None:
        return "unreleased"
    if result is None:
        return "untested"
    package_version = _string(_object(result.get("package")).get("version"))
    if package_version != latest_version:
        return "outdated"
    if result.get("passed") is True:
        return "ready"
    outcome = _string(result.get("outcome"))
    if outcome == "test_failures":
        return "not_ready"
    if outcome == "no_tests":
        return "no_tests"
    return "test_error"


def load_history(results_dir: Path) -> list[Mapping[str, Any]]:
    history: list[Mapping[str, Any]] = []
    if not results_dir.exists():
        return history
    for path in sorted(results_dir.glob("*/datasette-*/runs/*/result.json")):
        payload = _read_json(path)
        if not isinstance(payload, Mapping):
            raise ValueError(f"Expected an object in {path}")
        history.append(payload)
    return history


def load_latest_results(results_dir: Path) -> list[Mapping[str, Any]]:
    index_path = results_dir / "index.json"
    if not index_path.exists():
        return []
    payload = _read_json(index_path)
    if not isinstance(payload, Mapping) or not isinstance(payload.get("results"), list):
        raise ValueError(f"Expected {index_path} to contain a results array")
    results = payload["results"]
    if not all(isinstance(item, Mapping) for item in results):
        raise ValueError(f"Expected every result in {index_path} to be an object")
    return list(results)


def build_plugin_rows(
    plugins: Sequence[Mapping[str, Any]],
    latest_results: Sequence[Mapping[str, Any]],
    history: Sequence[Mapping[str, Any]],
    *,
    repository_url: str = DEFAULT_REPOSITORY_URL,
) -> list[dict[str, Any]]:
    latest_by_name: dict[str, Mapping[str, Any]] = {}
    for result in latest_results:
        name = _result_name(result)
        if name is None:
            continue
        previous = latest_by_name.get(name)
        if previous is None or _completed_at(result) > _completed_at(previous):
            latest_by_name[name] = result

    history_by_name: dict[str, list[Mapping[str, Any]]] = {}
    for result in history:
        name = _result_name(result)
        if name is not None:
            history_by_name.setdefault(name, []).append(result)

    rows: list[dict[str, Any]] = []
    seen_plugin_ids: set[str] = set()
    repository_url = repository_url.rstrip("/")
    for plugin in plugins:
        raw_name = _string(plugin.get("name"))
        if raw_name is None:
            raise ValueError("Every plugin must have a non-empty name")
        name = normalize_package_name(raw_name)
        github_repo = _string(plugin.get("github_repo"))
        plugin_id = github_repo or name
        if plugin_id in seen_plugin_ids:
            raise ValueError(f"Duplicate plugin identifier: {plugin_id}")
        seen_plugin_ids.add(plugin_id)
        page_anchor = "plugin-" + re.sub(
            r"[^a-z0-9]+", "-", plugin_id.casefold()
        ).strip("-")
        owner = (
            github_repo.split("/", 1)[0] if github_repo and "/" in github_repo else None
        )
        latest_version = _string(plugin.get("latest_version"))
        result = latest_by_name.get(name)
        plugin_history = history_by_name.get(name, [])
        package = _object(result.get("package")) if result else {}
        datasette = _object(result.get("datasette")) if result else {}
        run = _object(result.get("run")) if result else {}
        counts = _object(result.get("counts")) if result else {}
        source = _object(package.get("source"))
        test_suite = _object(package.get("test_suite"))
        inventory = _object(result.get("test_inventory")) if result else {}
        test_environment = _object(result.get("test_environment")) if result else {}
        artifacts = _object(result.get("artifacts")) if result else {}
        failing_tests = _string_list(result.get("failing_tests")) if result else []
        error_tests = _string_list(result.get("error_tests")) if result else []
        result_warnings = result.get("warnings") if result else []
        warnings = (
            [item for item in result_warnings if isinstance(item, Mapping)]
            if isinstance(result_warnings, list)
            else []
        )
        output_path = _string(artifacts.get("pytest_output"))
        output_url = (
            f"{repository_url}/blob/main/{quote(output_path, safe='/')}"
            if output_path
            else None
        )
        datasette_versions = sorted(
            {
                version
                for historical in plugin_history
                if (
                    version := _string(
                        _object(historical.get("datasette")).get("requested_version")
                    )
                )
            },
            key=_natural_key,
        )
        tested_package_version = _string(package.get("version"))
        tested_latest_release = bool(
            latest_version and result and tested_package_version == latest_version
        )
        status = _status(latest_version, result)
        row: dict[str, Any] = {
            "plugin_id": plugin_id,
            "page_anchor": page_anchor,
            "name": name,
            "owner": owner,
            "github_repo": github_repo,
            "github_url": f"https://github.com/{github_repo}" if github_repo else None,
            "pypi_url": f"https://pypi.org/project/{quote(name, safe='-')}/",
            "metadata_file": _string(plugin.get("metadata_file")),
            "metadata_sha256": _string(plugin.get("metadata_sha256")),
            "metadata_etag": _string(plugin.get("metadata_etag")),
            "released": latest_version is not None,
            "latest_version": latest_version,
            "status": status,
            "status_label": STATUS_LABELS[status],
            "status_description": STATUS_DESCRIPTIONS[status],
            "tested": result is not None,
            "tested_latest_release": tested_latest_release,
            "passed": (
                result.get("passed")
                if result and isinstance(result.get("passed"), bool)
                else None
            ),
            "runner_version": (
                _integer(result.get("runner_version"))
                if result and result.get("runner_version") is not None
                else None
            ),
            "outcome": _string(result.get("outcome")) if result else None,
            "tested_package_version": tested_package_version,
            "datasette_version": _string(datasette.get("requested_version")),
            "installed_datasette_version": _string(datasette.get("installed_version")),
            "datasette_versions_tested": ", ".join(datasette_versions),
            "test_runs": len(plugin_history),
            "run_id": _string(run.get("id")),
            "started_at": _string(run.get("started_at")),
            "last_tested_at": _string(run.get("completed_at")),
            "duration_seconds": _number(run.get("duration_seconds")),
            "python_version": _string(run.get("python_version")),
            "platform": _string(run.get("platform")),
            "pytest_exit_code": (
                _integer(run.get("pytest_exit_code"))
                if run.get("pytest_exit_code") is not None
                else None
            ),
            "collected": _integer(counts.get("collected")),
            "tests_passed": _integer(counts.get("passed")),
            "tests_failed": _integer(counts.get("failed")),
            "test_errors": _integer(counts.get("errors")),
            "skipped": _integer(counts.get("skipped")),
            "xfailed": _integer(counts.get("xfailed")),
            "xpassed": _integer(counts.get("xpassed")),
            "deselected": _integer(counts.get("deselected")),
            "pytest_warnings": _integer(counts.get("warnings")),
            "failing_test_count": len(failing_tests),
            "failing_tests": "\n".join(failing_tests),
            "error_test_count": len(error_tests),
            "error_tests": "\n".join(error_tests),
            "result_warning_codes": ", ".join(
                code for warning in warnings if (code := _string(warning.get("code")))
            ),
            "result_warning_messages": "\n".join(
                message
                for warning in warnings
                if (message := _string(warning.get("message")))
            ),
            "test_package_extra": _string(test_environment.get("package_extra")),
            "test_dependency_source": _string(
                test_environment.get("dependency_source")
            ),
            "test_dependencies": "\n".join(
                _string_list(test_environment.get("dependencies"))
            ),
            "detail": _string(result.get("detail")) if result else None,
            "test_suite_type": _string(test_suite.get("type")),
            "test_suite_repository": _string(test_suite.get("repository")),
            "test_suite_ref": _string(test_suite.get("ref")),
            "test_suite_git_sha": _string(test_suite.get("git_sha")),
            "sdist_url": _string(source.get("url")),
            "sdist_sha256": _string(source.get("sha256")),
            "sdist_test_files": _integer(inventory.get("pypi_sdist")),
            "release_tag_test_files": _integer(inventory.get("release_tag")),
            "pytest_output_path": output_path,
            "pytest_output_url": output_url,
        }
        if any(isinstance(value, (dict, list, tuple, set)) for value in row.values()):
            raise AssertionError(f"Generated nested value for {name}")
        rows.append(row)
    return sorted(rows, key=lambda item: (str(item["name"]), str(item["plugin_id"])))


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _percent(numerator: int, denominator: int) -> str:
    return f"{(100 * numerator / denominator):.1f}" if denominator else "0.0"


def _format_timestamp(value: str | None) -> str:
    if not value:
        return "Not yet"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _test_list(value: Any) -> str:
    tests = str(value or "").splitlines()
    if not tests:
        return ""
    return (
        '<ul class="test-list">'
        + "".join(f"<li><code>{_e(test)}</code></li>" for test in tests)
        + "</ul>"
    )


def _plugin_table_row(row: Mapping[str, Any]) -> str:
    tested = bool(row["tested"])
    counts = (
        f'<span class="count pass">{row["tests_passed"]} pass</span>'
        f'<span class="count fail">{row["tests_failed"]} fail</span>'
        f'<span class="count error">{row["test_errors"]} error</span>'
        if tested
        else '<span class="muted">—</span>'
    )
    links = (
        [f'<a href="{_e(row["github_url"])}">GitHub</a>'] if row["github_url"] else []
    )
    links.append(f'<a href="{_e(row["pypi_url"])}">PyPI</a>')
    if row["pytest_output_url"]:
        links.append(f'<a href="{_e(row["pytest_output_url"])}">pytest output</a>')
    details: list[str] = []
    if row["failing_tests"]:
        details.append(
            f'<div class="detail-block"><h4>Failing tests</h4>{_test_list(row["failing_tests"])}</div>'
        )
    if row["error_tests"]:
        details.append(
            f'<div class="detail-block"><h4>Collection / setup errors</h4>{_test_list(row["error_tests"])}</div>'
        )
    if row["result_warning_messages"]:
        details.append(
            f'<div class="detail-block warning-copy"><h4>Runner warnings</h4><p>{_e(row["result_warning_messages"])}</p></div>'
        )
    if row["test_dependencies"]:
        details.append(
            f'<div class="detail-block"><h4>Installed test dependencies</h4>{_test_list(row["test_dependencies"])}</div>'
        )
    if row["detail"]:
        details.append(
            f'<div class="detail-block"><h4>Runner detail</h4><p>{_e(row["detail"])}</p></div>'
        )
    details_html = (
        "".join(details)
        or '<p class="muted detail-empty">No failure details recorded.</p>'
    )
    search = " ".join(
        str(row.get(key) or "")
        for key in (
            "name",
            "owner",
            "latest_version",
            "status_label",
            "outcome",
            "failing_tests",
            "error_tests",
        )
    ).casefold()
    latest_version = row["latest_version"] or "—"
    datasette_version = row["datasette_version"] or "—"
    tested_version = row["tested_package_version"]
    version_note = (
        f'<span class="subtle">tested {_e(tested_version)}</span>'
        if tested_version and tested_version != row["latest_version"]
        else ""
    )
    return f"""
      <tr id="{_e(row['page_anchor'])}" data-status="{_e(row['status'])}" data-owner="{_e(row['owner'] or '')}"
          data-search="{_e(search)}" data-name="{_e(row['name'])}"
          data-date="{_e(row['last_tested_at'] or '')}">
        <td class="plugin-cell">
          <a class="plugin-name" href="{_e(row['github_url'] or row['pypi_url'])}">{_e(row['name'])}</a>
          <span class="owner">{_e(row['github_repo'] or 'Repository unavailable')}</span>
        </td>
        <td><span class="status status-{_e(row['status'])}"><span></span>{_e(row['status_label'])}</span></td>
        <td class="version-cell"><strong>{_e(latest_version)}</strong>{version_note}</td>
        <td><strong>{_e(datasette_version)}</strong></td>
        <td><div class="counts">{counts}</div></td>
        <td><time datetime="{_e(row['last_tested_at'] or '')}">{_e(_format_timestamp(row['last_tested_at']))}</time></td>
        <td class="details-cell">
          <details>
            <summary>Inspect</summary>
            <div class="details-panel">
              <p class="status-explanation">{_e(row['status_description'])}</p>
              <dl>
                <div><dt>Outcome</dt><dd>{_e(row['outcome'] or '—')}</dd></div>
                <div><dt>Test runs</dt><dd>{_e(row['test_runs'])}</dd></div>
                <div><dt>Collected</dt><dd>{_e(row['collected'])}</dd></div>
                <div><dt>Skipped</dt><dd>{_e(row['skipped'])}</dd></div>
                <div><dt>Warnings</dt><dd>{_e(row['pytest_warnings'])}</dd></div>
                <div><dt>Duration</dt><dd>{_e(row['duration_seconds']) + 's' if row['duration_seconds'] is not None else '—'}</dd></div>
                <div><dt>Python</dt><dd>{_e(row['python_version'] or '—')}</dd></div>
                <div><dt>Test source</dt><dd>{_e(row['test_suite_type'] or '—')}</dd></div>
                <div><dt>Dependency source</dt><dd>{_e(row['test_dependency_source'] or row['test_package_extra'] or '—')}</dd></div>
                <div><dt>sdist tests</dt><dd>{_e(row['sdist_test_files'])}</dd></div>
                <div><dt>Tag tests</dt><dd>{_e(row['release_tag_test_files'])}</dd></div>
              </dl>
              {details_html}
              <div class="detail-links">{' · '.join(links)}</div>
            </div>
          </details>
        </td>
      </tr>"""


def render_html(rows: Sequence[Mapping[str, Any]], generated_at: datetime) -> str:
    total = len(rows)
    released = sum(bool(row["released"]) for row in rows)
    tested_latest = sum(bool(row["tested_latest_release"]) for row in rows)
    ready = sum(row["status"] == "ready" for row in rows)
    status_counts = Counter(str(row["status"]) for row in rows)
    versions = sorted(
        {str(row["datasette_version"]) for row in rows if row["datasette_version"]},
        key=_natural_key,
    )
    target_version = versions[-1] if versions else "Awaiting first run"
    owners = sorted({str(row["owner"]) for row in rows if row["owner"]})
    table_rows = "".join(_plugin_table_row(row) for row in rows)
    owner_options = "".join(
        f'<option value="{_e(owner)}">{_e(owner)}</option>' for owner in owners
    )
    status_options = "".join(
        f'<option value="{status}">{_e(STATUS_LABELS[status])} ({status_counts[status]})</option>'
        for status in STATUS_ORDER
    )
    legend = "".join(
        f'<button type="button" class="legend-item" data-filter-status="{status}">'
        f'<span class="legend-dot status-{status}"></span>'
        f"<span><strong>{status_counts[status]}</strong>{_e(STATUS_LABELS[status])}</span></button>"
        for status in STATUS_ORDER
    )
    progress_segments = "".join(
        f'<span class="progress-segment status-{status}" style="width:{_percent(status_counts[status], total)}%" '
        f'title="{_e(STATUS_LABELS[status])}: {status_counts[status]}"></span>'
        for status in STATUS_ORDER
        if status_counts[status]
    )
    recent_rows = sorted(
        (row for row in rows if row["last_tested_at"]),
        key=lambda row: str(row["last_tested_at"]),
        reverse=True,
    )[:6]
    recent = (
        "".join(
            f'<li><span class="status status-{_e(row["status"])}"><span></span>{_e(row["status_label"])}</span>'
            f'<a href="#{_e(row["page_anchor"])}">{_e(row["name"])}</a>'
            f'<time>{_e(_format_timestamp(row["last_tested_at"]))}</time></li>'
            for row in recent_rows
        )
        or '<li class="muted">No test runs have landed yet.</li>'
    )
    generated_text = generated_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")

    replacements = {
        "@@TOTAL@@": str(total),
        "@@RELEASED@@": str(released),
        "@@TESTED_LATEST@@": str(tested_latest),
        "@@READY@@": str(ready),
        "@@COVERAGE@@": _percent(tested_latest, released),
        "@@READINESS@@": _percent(ready, released),
        "@@TARGET@@": _e(target_version),
        "@@GENERATED@@": _e(generated_text),
        "@@TABLE_ROWS@@": table_rows,
        "@@OWNER_OPTIONS@@": owner_options,
        "@@STATUS_OPTIONS@@": status_options,
        "@@LEGEND@@": legend,
        "@@PROGRESS_SEGMENTS@@": progress_segments,
        "@@RECENT@@": recent,
    }
    rendered = HTML_TEMPLATE
    for marker, value in replacements.items():
        rendered = rendered.replace(marker, value)
    return rendered


def generate_report(
    plugins_path: Path,
    results_dir: Path,
    output_dir: Path,
    *,
    repository_url: str = DEFAULT_REPOSITORY_URL,
    generated_at: datetime | None = None,
) -> list[dict[str, Any]]:
    plugins = _read_json(plugins_path)
    if not isinstance(plugins, list) or not all(
        isinstance(item, Mapping) for item in plugins
    ):
        raise ValueError(f"Expected {plugins_path} to contain an array of objects")
    latest_results = load_latest_results(results_dir)
    history = load_history(results_dir)
    rows = build_plugin_rows(
        plugins,
        latest_results,
        history,
        repository_url=repository_url,
    )
    generated_at = datetime.now(UTC) if generated_at is None else generated_at
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=UTC)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "plugins.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "index.html").write_text(
        render_html(rows, generated_at),
        encoding="utf-8",
    )
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugins", type=Path, default=Path("plugins.json"))
    parser.add_argument("--results", type=Path, default=Path("results"))
    parser.add_argument("--output", type=Path, default=Path("site"))
    parser.add_argument("--repository-url", default=DEFAULT_REPOSITORY_URL)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rows = generate_report(
        args.plugins,
        args.results,
        args.output,
        repository_url=args.repository_url,
    )
    print(f"Generated report for {len(rows)} plugins in {args.output}")
    return 0


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="A continuously updated compatibility scoreboard for Datasette plugins and Datasette 1.0.">
  <title>Ready for Datasette 1.0?</title>
  <style>
    :root {
      --ink: #111a35;
      --muted: #526475;
      --paper: #f8fafb;
      --panel: #ffffff;
      --line: #d8e6f5;
      --blue: #276890;
      --blue-light: #6090ad;
      --blue-pale: #eef6ff;
      --blue-dark: #194f70;
      --green: #18794e;
      --red: #c8302c;
      --orange: #b75b00;
      --purple: #7157c8;
      --grey: #77766f;
      --shadow: 0 12px 32px rgba(39, 104, 144, 0.09);
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      color: var(--ink);
      background: var(--paper);
      font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
      line-height: 1.5;
      letter-spacing: 0.012em;
    }
    a { color: var(--blue); text-underline-offset: 0.16em; }
    a:hover { text-decoration-thickness: 2px; }
    button, input, select { font: inherit; }
    .hero {
      position: relative;
      overflow: hidden;
      color: #fff;
      background: linear-gradient(180deg, var(--blue-light) 0%, var(--blue) 55%, var(--blue-dark) 100%);
      border-bottom: 7px solid var(--blue-pale);
    }
    .hero::after {
      content: "";
      position: absolute;
      width: 520px;
      height: 520px;
      right: -180px;
      top: -250px;
      border: 70px solid rgba(255, 255, 255, 0.1);
      border-radius: 50%;
    }
    .wrap { width: min(1440px, calc(100% - 40px)); margin: 0 auto; }
    .topbar {
      position: relative;
      z-index: 1;
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 22px 0;
      border-bottom: 1px solid rgba(255,255,255,0.16);
    }
    .brand { display: flex; align-items: center; gap: 12px; color: #fff; text-decoration: none; font-weight: 800; }
    .brand-mark {
      display: grid;
      place-items: center;
      width: 38px;
      height: 38px;
      color: var(--blue);
      background: #fff;
      border-radius: 7px 7px 7px 1px;
      font: 900 13px/1 ui-monospace, SFMono-Regular, Menlo, monospace;
      transform: rotate(-2deg);
    }
    .top-links { display: flex; gap: 22px; }
    .top-links a { color: #fff; font-size: 14px; font-weight: 700; }
    .hero-content { position: relative; z-index: 1; max-width: 1000px; padding: 70px 0 76px; }
    .eyebrow { margin: 0 0 14px; color: #fff; font: 800 12px/1.2 ui-monospace, monospace; letter-spacing: .16em; text-transform: uppercase; }
    h1 { margin: 0; max-width: 900px; font-size: clamp(48px, 8vw, 106px); line-height: 1; letter-spacing: .005em; }
    h1 span { color: #fff; }
    .lede { max-width: 760px; margin: 28px 0 0; color: rgba(255,255,255,.9); font-size: clamp(18px, 2vw, 24px); letter-spacing: .018em; }
    .hero-facts { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 36px; }
    .hero-facts span { padding: 8px 11px; border: 1px solid rgba(255,255,255,.38); border-radius: 7px; color: #fff; background: rgba(17,26,53,.12); font: 650 13px/1.2 ui-monospace, monospace; letter-spacing: .02em; }
    main { padding: 42px 0 80px; }
    .metrics { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 14px; }
    .metric { min-height: 145px; padding: 22px; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; box-shadow: var(--shadow); }
    .metric strong { display: block; margin: 8px 0 4px; font-size: clamp(30px, 4vw, 51px); line-height: 1; letter-spacing: .01em; }
    .metric .label { color: var(--muted); font-size: 13px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
    .metric small { color: var(--muted); }
    .metric-highlight { color: #fff; background: var(--blue); border-color: var(--blue-dark); }
    .metric-highlight .label, .metric-highlight small { color: rgba(255,255,255,.86); }
    .section { margin-top: 22px; padding: 26px; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; box-shadow: var(--shadow); }
    .section-heading { display: flex; justify-content: space-between; align-items: end; gap: 20px; margin-bottom: 22px; }
    .section-heading h2 { margin: 0; font-size: 27px; letter-spacing: .01em; }
    .section-heading p { max-width: 670px; margin: 5px 0 0; color: var(--muted); }
    .section-heading .kicker { color: var(--blue); font: 800 11px/1.3 ui-monospace, monospace; letter-spacing: .12em; text-transform: uppercase; }
    .progress-track { display: flex; height: 20px; overflow: hidden; background: var(--blue-pale); border: 2px solid var(--blue); border-radius: 999px; }
    .progress-segment { display: block; min-width: 3px; }
    .progress-copy { display: flex; justify-content: space-between; margin-top: 10px; color: var(--muted); font-size: 13px; }
    .legend { display: grid; grid-template-columns: repeat(7, minmax(95px, 1fr)); gap: 8px; margin-top: 22px; }
    .legend-item { display: flex; gap: 9px; align-items: center; padding: 10px; text-align: left; color: var(--muted); background: var(--blue-pale); border: 1px solid var(--line); border-radius: 8px; cursor: pointer; }
    .legend-item:hover { border-color: var(--blue); }
    .legend-item strong { display: block; color: var(--ink); font-size: 19px; line-height: 1; }
    .legend-item span:last-child { font-size: 11px; }
    .legend-dot { flex: 0 0 10px; width: 10px; height: 10px; border-radius: 50%; }
    .status-ready, .legend-dot.status-ready, .progress-segment.status-ready { --status: var(--green); }
    .status-not_ready, .legend-dot.status-not_ready, .progress-segment.status-not_ready { --status: var(--red); }
    .status-test_error, .legend-dot.status-test_error, .progress-segment.status-test_error { --status: var(--orange); }
    .status-no_tests, .legend-dot.status-no_tests, .progress-segment.status-no_tests { --status: var(--purple); }
    .status-outdated, .legend-dot.status-outdated, .progress-segment.status-outdated { --status: #147a91; }
    .status-untested, .legend-dot.status-untested, .progress-segment.status-untested { --status: #9b998f; }
    .status-unreleased, .legend-dot.status-unreleased, .progress-segment.status-unreleased { --status: #d4d1c4; }
    .legend-dot, .progress-segment { background: var(--status); }
    .two-up { display: grid; grid-template-columns: 1.15fr .85fr; gap: 22px; }
    .method-note { background: var(--blue-pale); border-color: #bfd6ea; }
    .method-note p { margin: 0; }
    .method-note strong { color: #123da6; }
    .recent { list-style: none; margin: 0; padding: 0; }
    .recent li { display: grid; grid-template-columns: 148px 1fr auto; gap: 12px; align-items: center; padding: 10px 0; border-top: 1px solid var(--line); }
    .recent li:first-child { border-top: 0; }
    .recent a { min-width: 0; overflow: hidden; color: var(--ink); font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }
    .recent time { color: var(--muted); font-size: 11px; }
    .status { display: inline-flex; gap: 6px; align-items: center; width: max-content; padding: 4px 8px; color: var(--status); background: color-mix(in srgb, var(--status) 10%, white); border: 1px solid color-mix(in srgb, var(--status) 35%, white); border-radius: 999px; font-size: 11px; font-weight: 800; white-space: nowrap; }
    .status > span { width: 7px; height: 7px; background: var(--status); border-radius: 50%; }
    .filters { display: grid; grid-template-columns: minmax(240px, 2fr) repeat(3, minmax(145px, .7fr)) auto; gap: 10px; margin-bottom: 16px; }
    .control { width: 100%; min-height: 42px; padding: 8px 11px; color: var(--ink); background: #fff; border: 1px solid #aaa79b; border-radius: 7px; }
    .control:focus { outline: 3px solid rgba(39,104,144,.2); border-color: var(--blue); }
    .clear { padding: 8px 14px; color: #fff; background: var(--blue); border: 1px solid var(--blue); border-radius: 7px; cursor: pointer; }
    .result-count { margin: 0 0 10px; color: var(--muted); font-size: 13px; }
    .table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 9px; }
    table { width: 100%; min-width: 1080px; border-collapse: collapse; background: #fff; }
    th { position: sticky; top: 0; z-index: 2; padding: 11px 13px; text-align: left; color: var(--ink); background: var(--blue-pale); border-bottom: 1px solid var(--line); font-size: 11px; letter-spacing: .08em; text-transform: uppercase; }
    td { padding: 13px; vertical-align: top; border-bottom: 1px solid var(--line); font-size: 13px; }
    tr:last-child td { border-bottom: 0; }
    tbody tr:hover { background: #f8fbff; }
    .plugin-cell { min-width: 225px; }
    .plugin-name { display: block; color: var(--ink); font-size: 14px; font-weight: 820; }
    .owner, .subtle { display: block; margin-top: 3px; color: var(--muted); font: 11px/1.3 ui-monospace, monospace; }
    .version-cell strong { font-family: ui-monospace, monospace; }
    .counts { display: flex; flex-wrap: wrap; gap: 4px; min-width: 125px; }
    .count { padding: 2px 5px; border-radius: 4px; font: 700 10px/1.3 ui-monospace, monospace; }
    .count.pass { color: var(--green); background: #e5f5ed; }
    .count.fail { color: var(--red); background: #feeae8; }
    .count.error { color: var(--orange); background: #fff0dc; }
    td time { color: var(--muted); font-size: 11px; white-space: nowrap; }
    details { position: relative; }
    summary { color: var(--blue); font-weight: 750; cursor: pointer; }
    .details-cell { min-width: 90px; }
    .details-panel { min-width: 570px; max-width: 680px; margin-top: 10px; padding: 17px; background: var(--blue-pale); border: 1px solid var(--line); border-radius: 8px; }
    .status-explanation { margin: 0 0 13px; font-weight: 650; }
    dl { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin: 0; }
    dl div { padding: 7px; background: #fff; border: 1px solid var(--line); border-radius: 5px; }
    dt { color: var(--muted); font-size: 9px; font-weight: 800; letter-spacing: .05em; text-transform: uppercase; }
    dd { margin: 3px 0 0; font: 700 11px/1.3 ui-monospace, monospace; overflow-wrap: anywhere; }
    .detail-block { margin-top: 14px; }
    .detail-block h4 { margin: 0 0 6px; font-size: 12px; }
    .detail-block p { margin: 0; white-space: pre-line; }
    .warning-copy { padding: 10px; background: #fff1db; border-left: 3px solid var(--orange); }
    .test-list { max-height: 190px; overflow: auto; margin: 0; padding-left: 20px; }
    .test-list li { margin: 3px 0; }
    code { font: 11px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; overflow-wrap: anywhere; }
    .detail-links { margin-top: 14px; }
    .detail-empty, .muted { color: var(--muted); }
    .empty { padding: 35px; text-align: center; color: var(--muted); }
    footer { padding: 25px 0 50px; color: var(--muted); border-top: 1px solid var(--line); font-size: 13px; }
    footer .wrap { display: flex; justify-content: space-between; gap: 20px; }
    @media (max-width: 1050px) {
      .metrics { grid-template-columns: repeat(3, 1fr); }
      .legend { grid-template-columns: repeat(4, 1fr); }
      .two-up { grid-template-columns: 1fr; }
      .filters { grid-template-columns: 2fr 1fr 1fr; }
      .filters .sort, .filters .clear { grid-column: auto; }
    }
    @media (max-width: 700px) {
      .wrap { width: min(100% - 24px, 1440px); }
      .top-links a:first-child { display: none; }
      .hero-content { padding: 52px 0 58px; }
      .metrics { grid-template-columns: 1fr 1fr; }
      .metric { min-height: 125px; }
      .section { padding: 18px; }
      .section-heading { align-items: start; flex-direction: column; }
      .legend { grid-template-columns: 1fr 1fr; }
      .recent li { grid-template-columns: 135px 1fr; }
      .recent time { grid-column: 2; }
      .filters { grid-template-columns: 1fr 1fr; }
      .filters .search { grid-column: 1 / -1; }
      footer .wrap { flex-direction: column; }
    }
  </style>
</head>
<body>
  <header class="hero">
    <div class="wrap">
      <nav class="topbar" aria-label="Main navigation">
        <a class="brand" href="./"><span class="brand-mark">DS</span><span>ready-for-datasette</span></a>
        <div class="top-links"><a href="#scoreboard">Scoreboard</a><a href="plugins.json">Download flat JSON</a></div>
      </nav>
      <div class="hero-content">
        <p class="eyebrow">The community compatibility scoreboard</p>
        <h1>Ready for <span>Datasette 1.0?</span></h1>
        <p class="lede">Tracking every known Datasette plugin, one released package and one repeatable pytest run at a time.</p>
        <div class="hero-facts"><span>Target: Datasette @@TARGET@@</span><span>Generated @@GENERATED@@</span><span>Source: released PyPI artifacts</span></div>
      </div>
    </div>
  </header>

  <main class="wrap">
    <section class="metrics" aria-label="Progress summary">
      <article class="metric"><span class="label">Known plugins</span><strong>@@TOTAL@@</strong><small>Across the tracked GitHub owners</small></article>
      <article class="metric"><span class="label">Released</span><strong>@@RELEASED@@</strong><small>Have a current PyPI release</small></article>
      <article class="metric metric-highlight"><span class="label">Ready</span><strong>@@READY@@</strong><small>Latest release passes</small></article>
      <article class="metric"><span class="label">Latest tested</span><strong>@@TESTED_LATEST@@</strong><small>Current release has a verdict</small></article>
      <article class="metric"><span class="label">Coverage</span><strong>@@COVERAGE@@%</strong><small>Of released plugins attempted</small></article>
    </section>

    <section class="section" aria-labelledby="progress-title">
      <div class="section-heading"><div><span class="kicker">Progress at a glance</span><h2 id="progress-title">From discovery to a green suite</h2><p>Colors describe the latest known state for each plugin. Click a category to filter the full scoreboard.</p></div><strong>@@READINESS@@% ready</strong></div>
      <div class="progress-track" aria-label="Plugin statuses">@@PROGRESS_SEGMENTS@@</div>
      <div class="progress-copy"><span>0 plugins</span><span>@@TOTAL@@ tracked</span></div>
      <div class="legend">@@LEGEND@@</div>
    </section>

    <div class="two-up">
      <section class="section method-note">
        <div class="section-heading"><div><span class="kicker">How to read this</span><h2>Verdicts and test health are separate</h2></div></div>
        <p><strong>Ready</strong> means the latest PyPI release completed a passing suite against the shown Datasette alpha. <strong>Tests failing</strong> is a compatibility signal. <strong>Test environment error</strong> means missing dependencies, collection problems, or runner failures prevented a trustworthy verdict. Historical runs remain immutable and linked from each row.</p>
      </section>
      <section class="section">
        <div class="section-heading"><div><span class="kicker">Newest evidence</span><h2>Recent activity</h2></div></div>
        <ul class="recent">@@RECENT@@</ul>
      </section>
    </div>

    <section class="section" id="scoreboard" aria-labelledby="scoreboard-title">
      <div class="section-heading"><div><span class="kicker">All plugins</span><h2 id="scoreboard-title">Compatibility scoreboard</h2><p>Search package names, failures, owners, and outcomes. Open “Inspect” for test sources, exact failures, warning counts, and raw pytest output.</p></div><a href="plugins.json">Download flat JSON →</a></div>
      <div class="filters">
        <input class="control search" id="search" type="search" placeholder="Search @@TOTAL@@ plugins" aria-label="Search plugins">
        <select class="control" id="status-filter" aria-label="Filter by status"><option value="">Every status</option>@@STATUS_OPTIONS@@</select>
        <select class="control" id="owner-filter" aria-label="Filter by owner"><option value="">Every owner</option>@@OWNER_OPTIONS@@</select>
        <select class="control sort" id="sort" aria-label="Sort plugins"><option value="name">Package name</option><option value="status">Status</option><option value="recent">Most recently tested</option></select>
        <button class="clear" type="button" id="clear">Reset</button>
      </div>
      <p class="result-count" id="result-count">Showing @@TOTAL@@ of @@TOTAL@@ plugins</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Plugin</th><th>Status</th><th>Latest release</th><th>Datasette</th><th>Test counts</th><th>Last checked</th><th>Evidence</th></tr></thead>
          <tbody id="plugin-rows">@@TABLE_ROWS@@</tbody>
        </table>
        <div class="empty" id="empty" hidden>No plugins match these filters.</div>
      </div>
    </section>
  </main>

  <footer><div class="wrap"><span>Built from public PyPI releases and immutable pytest logs.</span><span><a href="plugins.json">Flat plugin data</a> · <a href="https://github.com/datasette/ready-for-datasette">Source on GitHub</a></span></div></footer>
  <script>
    const body = document.getElementById("plugin-rows");
    const rows = Array.from(body.querySelectorAll("tr"));
    const search = document.getElementById("search");
    const statusFilter = document.getElementById("status-filter");
    const ownerFilter = document.getElementById("owner-filter");
    const sort = document.getElementById("sort");
    const resultCount = document.getElementById("result-count");
    const empty = document.getElementById("empty");
    const statusOrder = {test_error: 0, not_ready: 1, no_tests: 2, outdated: 3, ready: 4, untested: 5, unreleased: 6};

    function refresh() {
      const query = search.value.trim().toLowerCase();
      const status = statusFilter.value;
      const owner = ownerFilter.value;
      let visible = rows.filter(row => {
        const show = (!query || row.dataset.search.includes(query)) && (!status || row.dataset.status === status) && (!owner || row.dataset.owner === owner);
        row.hidden = !show;
        return show;
      });
      visible.sort((a, b) => {
        if (sort.value === "recent") return (b.dataset.date || "").localeCompare(a.dataset.date || "") || a.dataset.name.localeCompare(b.dataset.name);
        if (sort.value === "status") return statusOrder[a.dataset.status] - statusOrder[b.dataset.status] || a.dataset.name.localeCompare(b.dataset.name);
        return a.dataset.name.localeCompare(b.dataset.name);
      });
      visible.forEach(row => body.appendChild(row));
      resultCount.textContent = `Showing ${visible.length} of ${rows.length} plugins`;
      empty.hidden = visible.length !== 0;
    }
    [search, statusFilter, ownerFilter, sort].forEach(control => control.addEventListener("input", refresh));
    document.getElementById("clear").addEventListener("click", () => { search.value = ""; statusFilter.value = ""; ownerFilter.value = ""; sort.value = "name"; refresh(); search.focus(); });
    document.querySelectorAll("[data-filter-status]").forEach(button => button.addEventListener("click", () => { statusFilter.value = button.dataset.filterStatus; refresh(); document.getElementById("scoreboard").scrollIntoView(); }));
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
