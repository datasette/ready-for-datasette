import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

import run_plugin_tests


def release_files(*, yanked=False):
    return [{"filename": "package.whl", "yanked": yanked}]


def test_latest_datasette_alpha_uses_highest_non_yanked_1_0_alpha():
    payload = {
        "releases": {
            "0.65": release_files(),
            "1.0a2": release_files(),
            "1.0a10": release_files(),
            "1.0a11": release_files(yanked=True),
            "1.0b1": release_files(),
            "1.0": release_files(),
            "2.0a1": release_files(),
        }
    }

    assert run_plugin_tests.latest_datasette_alpha(payload) == "1.0a10"


def test_latest_datasette_alpha_rejects_payload_without_an_available_alpha():
    with pytest.raises(ValueError, match="No non-yanked Datasette 1.0 alpha"):
        run_plugin_tests.latest_datasette_alpha(
            {"releases": {"1.0a1": release_files(yanked=True)}}
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("Datasette.Example", "datasette-example"),
        ("datasette_example", "datasette-example"),
        ("datasette---example", "datasette-example"),
    ),
)
def test_normalize_package_name_uses_pypi_normalization(value, expected):
    assert run_plugin_tests.normalize_package_name(value) == expected


def test_github_repository_prefers_the_matching_source_repository():
    info = {
        "project_urls": {
            "Issues": "https://github.com/example/different-project/issues",
            "Source": "https://github.com/simonw/datasette-example.git",
        },
        "home_page": "https://example.com/",
    }

    assert (
        run_plugin_tests.github_repository(info, "datasette-example")
        == "simonw/datasette-example"
    )


def test_github_repository_accepts_a_github_homepage():
    info = {
        "project_urls": {},
        "home_page": "https://github.com/dogsheep/datasette-homepage/",
    }

    assert (
        run_plugin_tests.github_repository(info, "datasette-homepage")
        == "dogsheep/datasette-homepage"
    )


def test_select_sdist_uses_the_non_yanked_pypi_source_distribution():
    payload = {
        "urls": [
            {
                "packagetype": "bdist_wheel",
                "url": "https://files.pythonhosted.org/example.whl",
                "digests": {"sha256": "wheel-sha"},
                "yanked": False,
            },
            {
                "packagetype": "sdist",
                "url": "https://files.pythonhosted.org/yanked.tar.gz",
                "digests": {"sha256": "yanked-sha"},
                "yanked": True,
            },
            {
                "packagetype": "sdist",
                "url": "https://files.pythonhosted.org/released.tar.gz",
                "digests": {"sha256": "released-sha"},
                "yanked": False,
            },
        ]
    }

    assert run_plugin_tests.select_sdist(payload) == run_plugin_tests.Sdist(
        url="https://files.pythonhosted.org/released.tar.gz",
        sha256="released-sha",
    )


def test_select_sdist_refuses_to_test_without_a_released_sdist():
    with pytest.raises(ValueError, match="non-yanked source distribution"):
        run_plugin_tests.select_sdist(
            {
                "urls": [
                    {
                        "packagetype": "bdist_wheel",
                        "url": "https://files.pythonhosted.org/example.whl",
                        "digests": {"sha256": "wheel-sha"},
                        "yanked": False,
                    }
                ]
            }
        )


def test_release_tag_candidates_only_name_the_exact_pypi_version():
    assert run_plugin_tests.release_tag_candidates(
        "datasette-example", "1.2.3"
    ) == ("1.2.3", "v1.2.3", "datasette-example-1.2.3")


def test_download_sdist_verifies_the_published_sha256(tmp_path, monkeypatch):
    content = b"released source distribution"
    sdist = run_plugin_tests.Sdist(
        url="https://files.pythonhosted.org/released.tar.gz",
        sha256=hashlib.sha256(content).hexdigest(),
    )

    class Response:
        def __init__(self):
            self.offset = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size):
            chunk = content[self.offset : self.offset + size]
            self.offset += len(chunk)
            return chunk

    monkeypatch.setattr(run_plugin_tests, "urlopen", lambda request, timeout: Response())
    destination = tmp_path / "release.sdist"

    run_plugin_tests.download_sdist(sdist, destination)

    assert destination.read_bytes() == content


def test_extract_sdist_requires_one_safe_top_level_directory(tmp_path):
    archive_path = tmp_path / "release.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("datasette-example-1.0/pyproject.toml", "[project]")
        archive.writestr("datasette-example-1.0/tests/test_example.py", "")

    source = run_plugin_tests.extract_sdist(archive_path, tmp_path / "source")

    assert source == tmp_path / "source" / "datasette-example-1.0"
    assert (source / "pyproject.toml").read_text() == "[project]"


def test_build_pytest_command_pins_datasette_and_writes_json_report(tmp_path):
    report_path = tmp_path / "pytest-report.json"
    sdist_path = tmp_path / "datasette-example-2.0.tar.gz"

    command = run_plugin_tests.build_pytest_command(
        "datasette-example",
        sdist_path,
        "1.0a36",
        report_path,
        python_version="3.13",
        pytest_args=("tests/test_api.py", "-x"),
    )

    assert command[:2] == ["uv", "run"]
    assert "--no-project" in command
    assert ".[test]" not in command
    assert (
        f"datasette-example[test] @ {sdist_path.resolve().as_uri()}" in command
    )
    assert ["--with", "datasette==1.0a36"] == command[
        command.index("datasette==1.0a36") - 1 : command.index("datasette==1.0a36") + 1
    ]
    assert "pytest-json-report" in command
    assert f"--json-report-file={report_path}" in command
    assert command[-2:] == ["tests/test_api.py", "-x"]


def test_parse_arguments_keeps_runner_options_out_of_pytest_arguments(tmp_path):
    args = run_plugin_tests.parse_arguments(
        [
            "datasette-example",
            "--results-dir",
            str(tmp_path),
            "--python",
            "3.12",
            "--",
            "tests/test_api.py",
            "-x",
        ]
    )

    assert args.package == "datasette-example"
    assert args.results_dir == tmp_path
    assert args.python_version == "3.12"
    assert args.pytest_args == ["tests/test_api.py", "-x"]


def test_summarize_pytest_report_counts_outcomes_and_failure_names():
    report = {
        "summary": {
            "total": 8,
            "passed": 3,
            "failed": 2,
            "error": 1,
            "skipped": 1,
            "xfailed": 1,
            "xpassed": 0,
            "deselected": 2,
        },
        "warnings": [{"message": "one"}, {"message": "two"}],
        "tests": [
            {"nodeid": "tests/test_one.py::test_ok", "outcome": "passed"},
            {"nodeid": "tests/test_one.py::test_bad", "outcome": "failed"},
            {"nodeid": "tests/test_two.py::test_bad", "outcome": "failed"},
        ],
        "collectors": [
            {"nodeid": "tests/test_broken.py", "outcome": "failed"},
        ],
    }

    summary = run_plugin_tests.summarize_pytest_report(report, pytest_exit_code=1)

    assert summary == {
        "passed": False,
        "outcome": "test_failures",
        "counts": {
            "collected": 8,
            "passed": 3,
            "failed": 2,
            "errors": 1,
            "skipped": 1,
            "xfailed": 1,
            "xpassed": 0,
            "deselected": 2,
            "warnings": 2,
        },
        "failing_tests": [
            "tests/test_one.py::test_bad",
            "tests/test_two.py::test_bad",
        ],
        "error_tests": ["tests/test_broken.py"],
    }


def test_summarize_pytest_report_treats_exit_code_five_as_no_tests():
    summary = run_plugin_tests.summarize_pytest_report(
        {"summary": {"total": 0}, "tests": [], "collectors": []},
        pytest_exit_code=5,
    )

    assert summary["passed"] is False
    assert summary["outcome"] == "no_tests"
    assert summary["counts"]["collected"] == 0


def test_result_paths_use_package_and_datasette_as_the_primary_lookup(tmp_path):
    paths = run_plugin_tests.result_paths(
        tmp_path,
        "Datasette.Example",
        "1.0a36",
        "20260713T013041Z-gh-124123456-a1",
    )

    pair_directory = tmp_path / "datasette-example" / "datasette-1.0a36"
    run_directory = (
        pair_directory / "runs" / "20260713T013041Z-gh-124123456-a1"
    )
    assert paths.run_directory == run_directory
    assert paths.pytest_output == run_directory / "pytest.txt"
    assert paths.result == run_directory / "result.json"
    assert paths.latest == pair_directory / "latest.json"
    assert paths.index == tmp_path / "index.json"


def test_make_run_id_uses_github_run_metadata_when_available():
    started = datetime(2026, 7, 13, 1, 30, 41, tzinfo=UTC)

    run_id = run_plugin_tests.make_run_id(
        started,
        environ={"GITHUB_RUN_ID": "124123456", "GITHUB_RUN_ATTEMPT": "2"},
    )

    assert run_id == "20260713T013041Z-gh-124123456-a2"


def test_store_result_writes_immutable_result_latest_copy_and_index(tmp_path):
    paths = run_plugin_tests.result_paths(
        tmp_path,
        "datasette-example",
        "1.0a36",
        "20260713T013041Z-local-abcdef",
    )
    paths.run_directory.mkdir(parents=True)
    paths.pytest_output.write_text("one passed\n")
    result = {
        "schema_version": 1,
        "package": {"name": "datasette-example", "version": "2.0"},
        "datasette": {
            "requested_version": "1.0a36",
            "installed_version": "1.0a36",
        },
        "run": {
            "id": "20260713T013041Z-local-abcdef",
            "completed_at": "2026-07-13T01:31:18Z",
        },
        "passed": True,
        "outcome": "passed",
        "counts": {"passed": 1},
        "failing_tests": [],
        "error_tests": [],
        "artifacts": {
            "pytest_output": str(paths.pytest_output.relative_to(tmp_path.parent))
        },
    }

    run_plugin_tests.store_result(paths, result)

    assert json.loads(paths.result.read_text()) == result
    assert json.loads(paths.latest.read_text()) == result
    index = json.loads(paths.index.read_text())
    assert index["schema_version"] == 1
    assert index["generated_at"] == "2026-07-13T01:31:18Z"
    assert index["results"] == [result]


def test_load_json_report_returns_none_when_uv_failed_before_pytest(tmp_path):
    assert run_plugin_tests.load_json_report(tmp_path / "missing.json") is None

    broken = tmp_path / "broken.json"
    broken.write_text("not json")
    assert run_plugin_tests.load_json_report(broken) is None


@pytest.mark.parametrize(
    ("outcome", "expected_exit_code"),
    (("passed", 0), ("test_failures", 0), ("install_error", 0), ("runner_error", 1)),
)
def test_main_only_fails_for_runner_errors(
    outcome, expected_exit_code, tmp_path, monkeypatch
):
    paths = run_plugin_tests.result_paths(
        tmp_path, "datasette-example", "1.0a36", "run-1"
    )
    monkeypatch.setattr(
        run_plugin_tests,
        "execute",
        lambda args: ({"outcome": outcome}, paths),
    )

    assert run_plugin_tests.main(["datasette-example"]) == expected_exit_code
