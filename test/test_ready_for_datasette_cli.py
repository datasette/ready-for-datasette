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
