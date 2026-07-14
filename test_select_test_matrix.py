import json
from datetime import UTC, datetime, timedelta

import pytest

import run_plugin_tests
import select_test_matrix


def result(
    package,
    package_version,
    datasette_version,
    outcome,
    completed_at="2026-07-13T00:00:00Z",
):
    return {
        "runner_version": run_plugin_tests.RUNNER_VERSION,
        "package": {"name": package, "version": package_version},
        "datasette": {"requested_version": datasette_version},
        "run": {"completed_at": completed_at},
        "outcome": outcome,
    }


def test_released_plugins_deduplicates_names_and_rejects_version_conflicts():
    plugins = [
        {"name": "Datasette.Example", "latest_version": "1.0"},
        {"name": "datasette-example", "latest_version": "1.0"},
        {"name": "datasette-unreleased", "latest_version": None},
    ]

    assert select_test_matrix.released_plugins(plugins) == {
        "datasette-example": "1.0"
    }

    with pytest.raises(ValueError, match="Conflicting latest versions"):
        select_test_matrix.released_plugins(
            plugins
            + [{"name": "datasette_example", "latest_version": "2.0"}]
        )


def test_plugin_repositories_prefers_the_canonical_owner_for_duplicates():
    plugins = [
        {
            "name": "datasette-example",
            "github_repo": "asg017/datasette-example",
        },
        {
            "name": "Datasette.Example",
            "github_repo": "datasette/datasette-example",
        },
    ]

    assert select_test_matrix.plugin_repositories(plugins) == {
        "datasette-example": "datasette/datasette-example"
    }


def test_select_candidates_prioritizes_releases_then_never_tested_then_alpha():
    plugins = {
        "datasette-new-release": "2.0",
        "datasette-never": "1.0",
        "datasette-new-alpha": "3.0",
        "datasette-complete": "1.0",
        "datasette-retry": "1.0",
        "datasette-cooling-down": "1.0",
    }
    history = [
        result("datasette-new-release", "1.0", "1.0a35", "passed"),
        result("datasette-new-alpha", "3.0", "1.0a35", "test_failures"),
        result("datasette-complete", "1.0", "1.0a36", "install_error"),
        result(
            "datasette-retry",
            "1.0",
            "1.0a36",
            "runner_error",
            "2026-07-13T00:00:00Z",
        ),
        result(
            "datasette-cooling-down",
            "1.0",
            "1.0a36",
            "runner_error",
            "2026-07-13T11:00:00Z",
        ),
    ]
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)

    selected = select_test_matrix.select_candidates(
        plugins,
        history,
        "1.0a36",
        limit=5,
        now=now,
        retry_after=timedelta(hours=6),
    )

    assert selected == [
        {
            "package": "datasette-new-release",
            "package_version": "2.0",
            "datasette_version": "1.0a36",
            "reason": "new_release",
        },
        {
            "package": "datasette-never",
            "package_version": "1.0",
            "datasette_version": "1.0a36",
            "reason": "never_tested",
        },
        {
            "package": "datasette-new-alpha",
            "package_version": "3.0",
            "datasette_version": "1.0a36",
            "reason": "new_datasette_alpha",
        },
        {
            "package": "datasette-retry",
            "package_version": "1.0",
            "datasette_version": "1.0a36",
            "reason": "retry_runner_error",
        },
    ]


def test_load_history_reads_only_immutable_run_results(tmp_path):
    run = tmp_path / "pkg" / "datasette-1.0a36" / "runs" / "run-1"
    run.mkdir(parents=True)
    expected = result("pkg", "1.0", "1.0a36", "passed")
    (run / "result.json").write_text(json.dumps(expected))
    (tmp_path / "pkg" / "datasette-1.0a36" / "latest.json").write_text(
        json.dumps({"ignored": True})
    )

    assert select_test_matrix.load_history(tmp_path) == [expected]


def test_write_github_outputs_emits_compact_matrix_and_has_work(tmp_path):
    output = tmp_path / "github-output"
    candidates = [
        {
            "package": "datasette-example",
            "package_version": "1.0",
            "datasette_version": "1.0a36",
            "reason": "never_tested",
        }
    ]

    select_test_matrix.write_github_outputs(candidates, output)

    lines = output.read_text().splitlines()
    assert lines[0] == "has_work=true"
    assert json.loads(lines[1].removeprefix("matrix=")) == {"include": candidates}


def test_select_candidates_never_returns_more_than_five():
    plugins = {f"datasette-example-{number}": "1.0" for number in range(10)}

    selected = select_test_matrix.select_candidates(
        plugins, [], "1.0a36", limit=20
    )

    assert len(selected) == 5


def test_select_candidates_retests_results_from_an_older_runner():
    previous = result("datasette-example", "1.0", "1.0a36", "test_failures")
    previous["runner_version"] = run_plugin_tests.RUNNER_VERSION - 1

    selected = select_test_matrix.select_candidates(
        {"datasette-example": "1.0"},
        [previous],
        "1.0a36",
    )

    assert selected == [
        {
            "package": "datasette-example",
            "package_version": "1.0",
            "datasette_version": "1.0a36",
            "reason": "runner_updated",
        }
    ]


def test_select_candidates_includes_the_known_repository():
    selected = select_test_matrix.select_candidates(
        {"datasette-example": "1.0"},
        [],
        "1.0a36",
        repositories={"datasette-example": "datasette/datasette-example"},
    )

    assert selected[0]["repository"] == "datasette/datasette-example"
