import subprocess

import pytest

from ready_for_datasette import cli


def test_test_command_uses_dev_dependency_group(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "example"
version = "1.0"
dependencies = [
    "click>=8",
    "Datasette[rich]>=0.64",
    "sqlite-utils",
]

[dependency-groups]
dev = [
    "pytest",
    "datasette-test",
    "pytest-asyncio",
    {include-group = "frontend"},
]
frontend = ["datasette-vite", "python-ulid"]
""",
        encoding="utf-8",
    )
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    assert cli.main(["test", str(tmp_path)]) == 0
    assert calls == [
        (
            [
                "uv",
                "run",
                "--isolated",
                "--no-project",
                "--with",
                ".",
                "--with",
                "pytest",
                "--with",
                "datasette==1.0a37",
                "--with",
                "datasette-test",
                "--with",
                "pytest-asyncio",
                "--with",
                "datasette-vite",
                "--with",
                "python-ulid",
                "python",
                "-m",
                "pytest",
            ],
            {"cwd": tmp_path.resolve(), "check": False},
        )
    ]


def test_test_command_without_dev_dependency_group(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\n")
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 7)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    assert cli.main(["test", str(tmp_path)]) == 7
    assert calls[0][-9:] == [
        "--with",
        ".",
        "--with",
        "pytest",
        "--with",
        "datasette==1.0a37",
        "python",
        "-m",
        "pytest",
    ]


def test_test_command_requires_pyproject(tmp_path):
    with pytest.raises(SystemExit, match="2"):
        cli.main(["test", str(tmp_path)])


def test_test_command_command_flag_only_prints_command(tmp_path, monkeypatch, capsys):
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "example"
dependencies = ["click", "datasette>=0.64"]

[dependency-groups]
dev = ["pytest-asyncio"]
""",
        encoding="utf-8",
    )

    def unexpected_run(*args, **kwargs):
        pytest.fail("--command should not run a subprocess")

    monkeypatch.setattr(cli.subprocess, "run", unexpected_run)

    assert cli.main(["test", "--command", str(tmp_path)]) == 0
    assert capsys.readouterr().out == (
        "uv run --isolated --no-project --with . --with pytest "
        "--with datasette==1.0a37 --with pytest-asyncio "
        "python -m pytest\n"
    )


def workflow(tmp_path, versions, uses):
    path = tmp_path / ".github" / "workflows" / "test.yml"
    job = {
        "strategy": {"matrix": {"python-version": versions}},
        "steps": [{"uses": use} for use in uses] + [{"run": "pytest"}],
    }
    return [(path, {"jobs": {"test": job}})]


@pytest.mark.parametrize(
    "versions,expected_failures,expected_text",
    [
        (["3.11", "3.12", "3.13", "3.14", "3.15"], 0, "3.11, 3.12, 3.13, 3.14, 3.15"),
        (["3.15"], 0, "3.15"),
        (["3.11", "3.14"], 1, "does not test Python 3.15"),
        (["3.10", "3.15"], 1, "still tests Python 3.10"),
        ([], 1, "no python-version matrix"),
    ],
)
def test_python_matrix_check(
    tmp_path, capsys, versions, expected_failures, expected_text
):
    reporter = cli.Reporter(color=False)
    cli.check_workflow_python_matrix(
        workflow(tmp_path, versions, []), tmp_path, reporter
    )
    assert reporter.failed == expected_failures
    assert reporter.passed == 1 - expected_failures
    assert expected_text in capsys.readouterr().out


def test_parse_action_versions():
    assert cli.parse_action_versions(
        "actions/checkout@v7\n\nnot a version line\nactions/setup-python@v7\n"
    ) == {"actions/checkout": "v7", "actions/setup-python": "v7"}


ACTION_VERSIONS = {
    "actions/checkout": "v7",
    "actions/setup-python": "v7",
    "actions/cache": "v6",
}


@pytest.mark.parametrize(
    "uses,expected_problems",
    [
        (["actions/checkout@v7", "actions/setup-python@v7"], []),
        # Actions missing from versions.txt are ignored
        (
            [
                "actions/checkout@v7",
                "actions/setup-python@v7",
                "pypa/gh-action-pypi-publish@release/v1",
            ],
            [],
        ),
        (
            ["actions/checkout@v7", "actions/setup-python@v6"],
            ["uses actions/setup-python@v6; expected actions/setup-python@v7"],
        ),
        (
            [
                "actions/checkout@v7",
                "actions/setup-python@v7",
                "actions/cache/restore@v4",
            ],
            ["uses actions/cache/restore@v4; expected actions/cache/restore@v6"],
        ),
        (["actions/checkout@v7"], ["actions/setup-python@v7 is not used"]),
    ],
)
def test_action_versions_check(tmp_path, monkeypatch, capsys, uses, expected_problems):
    monkeypatch.setattr(cli, "fetch_action_versions", lambda: ACTION_VERSIONS)
    reporter = cli.Reporter(color=False)
    cli.check_action_versions(workflow(tmp_path, ["3.15"], uses), tmp_path, reporter)
    output = capsys.readouterr().out
    assert reporter.failed == (1 if expected_problems else 0)
    for problem in expected_problems:
        assert problem in output


def test_action_versions_check_fails_when_versions_unavailable(
    tmp_path, monkeypatch, capsys
):
    def broken():
        raise OSError("network down")

    monkeypatch.setattr(cli, "fetch_action_versions", broken)
    reporter = cli.Reporter(color=False)
    cli.check_action_versions(
        workflow(tmp_path, ["3.15"], ["actions/checkout@v7"]), tmp_path, reporter
    )
    assert reporter.failed == 1
    assert "network down" in capsys.readouterr().out
