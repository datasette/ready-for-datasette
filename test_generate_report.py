import json
from datetime import UTC, datetime

import generate_report


def make_result(
    package,
    package_version,
    datasette_version,
    outcome,
    completed_at,
    *,
    passed=False,
    run_id="run-1",
):
    return {
        "schema_version": 1,
        "runner_version": 2,
        "package": {
            "name": package,
            "version": package_version,
            "repository": "example/example",
            "source": {
                "type": "pypi_sdist",
                "url": "https://files.pythonhosted.org/example.tar.gz",
                "sha256": "abc123",
            },
            "test_suite": {
                "type": "github_release_tag",
                "repository": "example/example",
                "ref": package_version,
                "git_sha": "deadbeef",
            },
        },
        "datasette": {
            "requested_version": datasette_version,
            "installed_version": datasette_version,
        },
        "run": {
            "id": run_id,
            "started_at": completed_at,
            "completed_at": completed_at,
            "duration_seconds": 3.5,
            "python_version": "3.13",
            "platform": "test-platform",
            "pytest_exit_code": 0 if passed else 1,
        },
        "passed": passed,
        "outcome": outcome,
        "test_environment": {
            "package_extra": None,
            "dependency_source": "dependency-groups.dev",
            "dependencies": ["pytest", "pytest-asyncio"],
        },
        "counts": {
            "collected": 3,
            "passed": 2 if passed else 1,
            "failed": 0 if passed else 2,
            "errors": 0,
            "skipped": 0,
            "xfailed": 0,
            "xpassed": 0,
            "deselected": 0,
            "warnings": 1,
        },
        "failing_tests": [] if passed else ["tests/test_plugin.py::test_failure"],
        "error_tests": [],
        "test_inventory": {"pypi_sdist": 1, "release_tag": 2},
        "warnings": [{"code": "example_warning", "message": "Example warning"}],
        "artifacts": {
            "pytest_output": f"results/{package}/datasette-{datasette_version}/pytest.txt"
        },
    }


def test_build_plugin_rows_has_one_flat_object_per_plugin():
    plugins = [
        {
            "name": "Datasette.Example",
            "github_repo": "example/datasette-example",
            "latest_version": "2.0",
            "metadata_file": "pyproject.toml",
            "metadata_sha256": "metadata-hash",
            "metadata_etag": '"etag"',
        },
        {
            "name": "datasette-untested",
            "github_repo": "example/datasette-untested",
            "latest_version": "1.0",
        },
        {
            "name": "datasette-unreleased",
            "github_repo": "example/datasette-unreleased",
            "latest_version": None,
        },
    ]
    older = make_result(
        "datasette_example",
        "1.0",
        "1.0a35",
        "test_failures",
        "2026-07-12T10:00:00Z",
        run_id="old-run",
    )
    latest = make_result(
        "datasette-example",
        "2.0",
        "1.0a36",
        "passed",
        "2026-07-13T10:00:00Z",
        passed=True,
        run_id="latest-run",
    )

    rows = generate_report.build_plugin_rows(
        plugins,
        [latest],
        [older, latest],
        repository_url="https://github.com/datasette/ready-for-datasette",
    )

    assert [row["name"] for row in rows] == [
        "datasette-example",
        "datasette-unreleased",
        "datasette-untested",
    ]
    assert rows[0]["status"] == "ready"
    assert rows[0]["tested_latest_release"] is True
    assert rows[0]["test_runs"] == 2
    assert rows[0]["runner_version"] == 2
    assert rows[0]["test_dependency_source"] == "dependency-groups.dev"
    assert rows[0]["test_dependencies"] == "pytest\npytest-asyncio"
    assert rows[0]["datasette_versions_tested"] == "1.0a35, 1.0a36"
    assert rows[0]["failing_tests"] == ""
    assert rows[0]["pytest_output_url"].startswith(
        "https://github.com/datasette/ready-for-datasette/blob/main/results/"
    )
    assert rows[1]["status"] == "unreleased"
    assert rows[2]["status"] == "untested"
    assert all(
        value is None or isinstance(value, (str, int, float, bool))
        for row in rows
        for value in row.values()
    )


def test_build_plugin_rows_marks_an_old_release_for_retesting():
    plugin = {
        "name": "datasette-example",
        "github_repo": "example/datasette-example",
        "latest_version": "2.0",
    }
    result = make_result(
        "datasette-example",
        "1.0",
        "1.0a36",
        "passed",
        "2026-07-13T10:00:00Z",
        passed=True,
    )

    row = generate_report.build_plugin_rows([plugin], [result], [result])[0]

    assert row["status"] == "outdated"
    assert row["tested_latest_release"] is False


def test_build_plugin_rows_preserves_duplicate_projects_from_different_repositories():
    plugins = [
        {
            "name": "datasette-example",
            "github_repo": "first/datasette-example",
            "latest_version": "1.0",
        },
        {
            "name": "datasette-example",
            "github_repo": "second/datasette-example",
            "latest_version": "1.0",
        },
    ]

    rows = generate_report.build_plugin_rows(plugins, [], [])

    assert len(rows) == 2
    assert [row["plugin_id"] for row in rows] == [
        "first/datasette-example",
        "second/datasette-example",
    ]


def test_generate_report_writes_flat_json_and_information_rich_html(tmp_path):
    plugins_path = tmp_path / "plugins.json"
    results_dir = tmp_path / "results"
    output_dir = tmp_path / "site"
    plugin = {
        "name": "datasette-example",
        "github_repo": "example/datasette-example",
        "latest_version": "2.0",
        "metadata_file": "pyproject.toml",
    }
    result = make_result(
        "datasette-example",
        "2.0",
        "1.0a36",
        "test_failures",
        "2026-07-13T10:00:00Z",
    )
    plugins_path.write_text(json.dumps([plugin]))
    results_dir.mkdir()
    (results_dir / "index.json").write_text(
        json.dumps({"schema_version": 1, "results": [result]})
    )
    run = results_dir / "datasette-example" / "datasette-1.0a36" / "runs" / "run-1"
    run.mkdir(parents=True)
    (run / "result.json").write_text(json.dumps(result))

    rows = generate_report.generate_report(
        plugins_path,
        results_dir,
        output_dir,
        generated_at=datetime(2026, 7, 13, 12, 0, tzinfo=UTC),
    )

    assert len(rows) == 1
    combined = json.loads((output_dir / "plugins.json").read_text())
    assert combined[0]["name"] == "datasette-example"
    assert combined[0]["failing_tests"] == "tests/test_plugin.py::test_failure"
    assert not any(isinstance(value, (dict, list)) for value in combined[0].values())
    html = (output_dir / "index.html").read_text()
    assert "Ready for Datasette 1.0?" in html
    assert "Download flat JSON" in html
    assert 'data-status="not_ready"' in html
    assert "tests/test_plugin.py::test_failure" in html
    assert "Search 1 plugin" in html
    assert "--blue: #276890" in html
    assert "--blue-light: #6090ad" in html
    assert 'font-family: "Helvetica Neue", Helvetica, Arial, sans-serif' in html
    assert "letter-spacing: -." not in html
    assert (output_dir / ".nojekyll").exists()
