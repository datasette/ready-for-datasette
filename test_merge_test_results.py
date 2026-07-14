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

    run = (
        results
        / "datasette-example"
        / "datasette-1.0a36"
        / "runs"
        / "run-2"
    )
    assert merged == [run]
    stored = json.loads((run / "result.json").read_text())
    assert stored["artifacts"]["pytest_output"] == (
        "results/datasette-example/datasette-1.0a36/runs/run-2/pytest.txt"
    )
    assert (run / "pytest.txt").read_text() == "pytest output\n"
    assert json.loads(
        (results / "datasette-example" / "datasette-1.0a36" / "latest.json").read_text()
    ) == stored
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
    existing = (
        results
        / "datasette-example"
        / "datasette-1.0a36"
        / "runs"
        / "same-run"
    )
    existing.mkdir(parents=True)
    (existing / "result.json").write_text(json.dumps(payload))
    (existing / "pytest.txt").write_text("different\n")

    with pytest.raises(FileExistsError, match="Conflicting immutable run"):
        merge_test_results.merge_results(incoming, results)
