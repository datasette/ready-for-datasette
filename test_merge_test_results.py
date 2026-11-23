import json

import pytest

import merge_test_results


def make_result(package, version, datasette, run_id, completed_at, outcome="passed"):
    return {
        "schema_version": 1,
        "package": {"name": package, "version": version},
        "datasette": {
            "requested_version": datasette,
            "installed_version": datasette,
        },
        "run": {"id": run_id, "completed_at": completed_at},
        "passed": outcome == "passed",
        "outcome": outcome,
        "counts": {},
        "failing_tests": [],
        "error_tests": [],
        "artifacts": {"pytest_output": "staged-results/old/path/pytest.txt"},
    }


def stage_result(root, result, output="pytest output\n"):
    run = root / "artifact" / "arbitrary" / "runs" / result["run"]["id"]
    run.mkdir(parents=True)
    (run / "result.json").write_text(json.dumps(result))
    (run / "pytest.txt").write_text(output)
    return run


def test_merge_results_installs_run_updates_latest_and_rebuilds_index(tmp_path):
    incoming = tmp_path / "incoming"
    results = tmp_path / "results"
    payload = make_result(
        "Datasette.Example",
        "2.0",
        "1.0a36",
        "run-2",
        "2026-07-13T12:00:00Z",
    )
    stage_result(incoming, payload)

    merged = merge_test_results.merge_results(incoming, results)

    run = results / "datasette-example" / "datasette-1.0a36" / "runs" / "run-2"
    assert merged == [run]
    stored = json.loads((run / "result.json").read_text())
    assert stored["artifacts"]["pytest_output"] == (
        "results/datasette-example/datasette-1.0a36/runs/run-2/pytest.txt"
    )
    assert (run / "pytest.txt").read_text() == "pytest output\n"
    assert (
        json.loads(
            (
                results / "datasette-example" / "datasette-1.0a36" / "latest.json"
            ).read_text()
        )
        == stored
    )
    index = json.loads((results / "index.json").read_text())
    assert index["results"] == [stored]


def test_merge_results_preserves_newer_latest_while_adding_old_run(tmp_path):
    incoming = tmp_path / "incoming"
    results = tmp_path / "results"
    newer = make_result(
        "datasette-example",
        "2.0",
        "1.0a36",
        "run-new",
        "2026-07-13T12:00:00Z",
    )
    latest = results / "datasette-example" / "datasette-1.0a36" / "latest.json"
    latest.parent.mkdir(parents=True)
    latest.write_text(json.dumps(newer))
    older = make_result(
        "datasette-example",
        "2.0",
        "1.0a36",
        "run-old",
        "2026-07-13T11:00:00Z",
    )
    stage_result(incoming, older)

    merge_test_results.merge_results(incoming, results)

    assert json.loads(latest.read_text()) == newer
    assert (
        results
        / "datasette-example"
        / "datasette-1.0a36"
        / "runs"
        / "run-old"
        / "result.json"
    ).exists()


def test_merge_results_refuses_conflicting_immutable_run(tmp_path):
    incoming = tmp_path / "incoming"
    results = tmp_path / "results"
    payload = make_result(
        "datasette-example", "2.0", "1.0a36", "same-run", "2026-07-13T12:00:00Z"
    )
    stage_result(incoming, payload, output="incoming\n")
    existing = results / "datasette-example" / "datasette-1.0a36" / "runs" / "same-run"
    existing.mkdir(parents=True)
    (existing / "result.json").write_text(json.dumps(payload))
    (existing / "pytest.txt").write_text("different\n")

    with pytest.raises(FileExistsError, match="Conflicting immutable run"):
        merge_test_results.merge_results(incoming, results)


def test_main_writes_commit_message_listing_plugins_and_results(tmp_path):
    incoming = tmp_path / "incoming"
    results = tmp_path / "results"
    passing = make_result(
        "datasette-alpha", "1.0", "1.0a44", "run-a", "2026-07-13T12:00:00Z"
    )
    passing["counts"] = {"passed": 12, "skipped": 1}
    failing = make_result(
        "datasette-beta",
        "0.3",
        "1.0a44",
        "run-b",
        "2026-07-13T12:01:00Z",
        outcome="test_failures",
    )
    failing["counts"] = {"passed": 4, "failed": 2}
    failing["failing_tests"] = ["tests/test_beta.py::test_one"]
    failing["warnings"] = [{"code": "x", "message": "Something odd"}]
    stage_result(incoming / "a", passing)
    stage_result(incoming / "b", failing)
    message_path = tmp_path / "message.txt"

    assert (
        merge_test_results.main(
            [
                str(incoming),
                "--results",
                str(results),
                "--commit-message",
                str(message_path),
            ]
        )
        == 0
    )

    assert message_path.read_text() == (
        "Test results: datasette-alpha, datasette-beta\n"
        "\n"
        "2 runs: 1 passed, 1 test failures\n"
        "\n"
        "- datasette-alpha 1.0 on Datasette 1.0a44: passed (12 passed, 1 skipped)\n"
        "- datasette-beta 0.3 on Datasette 1.0a44: test failures"
        " (4 passed, 2 failed)\n"
        "\n"
        "datasette-beta:\n"
        "  - tests/test_beta.py::test_one\n"
        "  - Warning: Something odd\n"
    )


def test_main_succeeds_without_writing_a_message_when_nothing_to_merge(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    message_path = tmp_path / "message.txt"

    assert (
        merge_test_results.main(
            [
                str(incoming),
                "--results",
                str(tmp_path / "results"),
                "--commit-message",
                str(message_path),
            ]
        )
        == 0
    )
    assert not message_path.exists()
    assert not (tmp_path / "results").exists()
