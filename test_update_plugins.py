import hashlib
import json
import textwrap

import pytest

import update_plugins


@pytest.mark.parametrize(
    ("document", "expected"),
    (
        (
            """
            [project]
            name = "datasette-one"

            [project.entry-points.datasette]
            one = "datasette_one"
            """,
            "datasette-one",
        ),
        (
            """
            [project]
            name = "datasette-two"
            entry-points = { datasette = { two = "datasette_two" } }
            """,
            "datasette-two",
        ),
        (
            """
            project = { name = "datasette-three", entry-points = { datasette = { three = "datasette_three" } } }
            """,
            "datasette-three",
        ),
    ),
)
def test_parse_pyproject_supports_different_toml_layouts(document, expected):
    assert update_plugins.parse_pyproject(document) == expected


def test_parse_pyproject_rejects_a_non_datasette_project():
    document = """
        [project]
        name = "datasette-in-name-only"

        [project.scripts]
        datasette-in-name-only = "example:cli"
    """

    assert update_plugins.parse_pyproject(document) is None


def test_parse_pyproject_reports_invalid_toml():
    with pytest.raises(
        update_plugins.ProjectParseError, match="Invalid pyproject.toml"
    ):
        update_plugins.parse_pyproject("[project\nname = 'broken'")


@pytest.mark.parametrize(
    ("setup_py", "expected"),
    (
        (
            """
            from setuptools import setup

            setup(
                name="datasette-old-style",
                entry_points={
                    "datasette": [
                        "old_style = datasette_old_style"
                    ]
                },
            )
            """,
            "datasette-old-style",
        ),
        (
            """
            import setuptools

            PACKAGE_NAME = "datasette-static-values"
            ENTRY_POINTS = dict(
                console_scripts=["unrelated = example:cli"],
                datasette=["static_values = datasette_static_values"],
            )
            SETTINGS = {
                "name": PACKAGE_NAME,
                "entry_points": ENTRY_POINTS,
            }

            setuptools.setup(**SETTINGS)
            """,
            "datasette-static-values",
        ),
    ),
)
def test_parse_setup_py_uses_ast_without_caring_about_layout(setup_py, expected):
    assert update_plugins.parse_setup_py(textwrap.dedent(setup_py)) == expected


def test_parse_setup_py_rejects_other_entry_point_groups():
    setup_py = """
        from setuptools import setup
        setup(
            name="datasette-not-really-a-plugin",
            entry_points={"console_scripts": ["example = example:cli"]},
        )
    """

    assert update_plugins.parse_setup_py(textwrap.dedent(setup_py)) is None


def test_parse_setup_py_reports_invalid_python():
    with pytest.raises(update_plugins.ProjectParseError, match="Invalid setup.py"):
        update_plugins.parse_setup_py("setup(name=")


class BytesClient:
    def __init__(self, responses):
        self.responses = responses
        self.requested = []

    def get_raw(self, url, *, etag=None):
        self.requested.append((url, etag))
        return self.responses.get(url)


def test_http_client_sends_if_none_match_and_returns_response_etag(monkeypatch):
    captured = {}

    class Response:
        headers = {"ETag": '"new-etag"'}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"packaging content"

    def fake_urlopen(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(update_plugins, "urlopen", fake_urlopen)
    client = update_plugins.HttpClient(timeout=12)

    result = client.get_raw(
        "https://raw.githubusercontent.com/example", etag='"old-etag"'
    )

    assert captured["request"].get_header("If-none-match") == '"old-etag"'
    assert captured["timeout"] == 12
    assert result == update_plugins.RawResponse(
        content=b"packaging content",
        etag='"new-etag"',
    )


def test_inspect_repository_falls_back_to_setup_py_only_when_pyproject_is_absent():
    repository = {
        "full_name": "simonw/datasette-legacy",
        "default_branch": "main",
    }
    pyproject_url = (
        "https://raw.githubusercontent.com/simonw/datasette-legacy/main/pyproject.toml"
    )
    setup_url = (
        "https://raw.githubusercontent.com/simonw/datasette-legacy/main/setup.py"
    )
    setup_py = textwrap.dedent("""
        from setuptools import setup
        setup(name="datasette-package-name", entry_points={"datasette": []})
        """).encode()
    client = BytesClient(
        {
            pyproject_url: update_plugins.RawResponse(content=None, etag=None),
            setup_url: update_plugins.RawResponse(
                content=setup_py, etag='"setup-etag"'
            ),
        }
    )

    result = update_plugins.inspect_repository(repository, client)

    assert result == update_plugins.PluginSource(
        name="datasette-package-name",
        github_repo="simonw/datasette-legacy",
        metadata_file="setup.py",
        metadata_sha256=hashlib.sha256(setup_py).hexdigest(),
        metadata_etag='"setup-etag"',
    )
    assert client.requested == [(pyproject_url, None), (setup_url, None)]


def test_inspect_repository_does_not_use_setup_py_when_pyproject_exists():
    repository = {
        "full_name": "dogsheep/datasette-not-a-plugin",
        "default_branch": "trunk",
    }
    pyproject_url = "https://raw.githubusercontent.com/dogsheep/datasette-not-a-plugin/trunk/pyproject.toml"
    client = BytesClient(
        {
            pyproject_url: update_plugins.RawResponse(
                content=b"""
                    [project]
                    name = "datasette-not-a-plugin"
                """,
                etag='"pyproject-etag"',
            ),
        }
    )

    assert update_plugins.inspect_repository(repository, client) is None
    assert client.requested == [(pyproject_url, None)]


def test_inspect_repository_reuses_cached_metadata_after_a_304():
    repository = {
        "full_name": "simonw/datasette-cached",
        "default_branch": "main",
    }
    pyproject_url = (
        "https://raw.githubusercontent.com/simonw/datasette-cached/main/pyproject.toml"
    )
    previous = {
        "name": "datasette-cached",
        "github_repo": "simonw/datasette-cached",
        "metadata_file": "pyproject.toml",
        "metadata_sha256": "cached-sha256",
        "metadata_etag": '"cached-etag"',
        "latest_version": "1.0",
    }
    client = BytesClient(
        {
            pyproject_url: update_plugins.RawResponse(
                content=None,
                etag='"cached-etag"',
                not_modified=True,
            )
        }
    )

    result = update_plugins.inspect_repository(repository, client, previous)

    assert result == update_plugins.PluginSource(
        name="datasette-cached",
        github_repo="simonw/datasette-cached",
        metadata_file="pyproject.toml",
        metadata_sha256="cached-sha256",
        metadata_etag='"cached-etag"',
    )
    assert client.requested == [(pyproject_url, '"cached-etag"')]


def test_cached_setup_py_still_checks_for_a_new_pyproject_first():
    repository = {
        "full_name": "simonw/datasette-legacy-cached",
        "default_branch": "main",
    }
    pyproject_url = "https://raw.githubusercontent.com/simonw/datasette-legacy-cached/main/pyproject.toml"
    setup_url = (
        "https://raw.githubusercontent.com/simonw/datasette-legacy-cached/main/setup.py"
    )
    previous = {
        "name": "datasette-legacy-cached",
        "github_repo": "simonw/datasette-legacy-cached",
        "metadata_file": "setup.py",
        "metadata_sha256": "cached-sha256",
        "metadata_etag": '"cached-setup-etag"',
        "latest_version": "1.0",
    }
    client = BytesClient(
        {
            pyproject_url: update_plugins.RawResponse(content=None, etag=None),
            setup_url: update_plugins.RawResponse(
                content=None,
                etag='"cached-setup-etag"',
                not_modified=True,
            ),
        }
    )

    result = update_plugins.inspect_repository(repository, client, previous)

    assert result is not None
    assert result.metadata_file == "setup.py"
    assert client.requested == [
        (pyproject_url, None),
        (setup_url, '"cached-setup-etag"'),
    ]


class JsonClient:
    def __init__(self, responses):
        self.responses = responses
        self.requested = []

    def get_json(self, url, *, github_api=False):
        self.requested.append((url, github_api))
        return self.responses[url]


def test_list_public_repositories_paginates_until_a_short_page():
    first_url = (
        "https://api.github.com/users/simonw/repos?per_page=100&page=1&type=public"
    )
    second_url = (
        "https://api.github.com/users/simonw/repos?per_page=100&page=2&type=public"
    )
    first_page = [
        {"full_name": f"simonw/repository-{number}", "default_branch": "main"}
        for number in range(100)
    ]
    final_repository = {
        "full_name": "simonw/datasette-final",
        "default_branch": "main",
    }
    client = JsonClient({first_url: first_page, second_url: [final_repository]})

    repositories = update_plugins.list_public_repositories("simonw", client)

    assert len(repositories) == 101
    assert repositories[-1] == final_repository
    assert client.requested == [(first_url, True), (second_url, True)]


@pytest.mark.parametrize(
    ("payload", "expected"),
    (
        ({"info": {"version": "1.2.3"}}, "1.2.3"),
        (None, None),
        ({"info": {}}, None),
    ),
)
def test_latest_pypi_version(payload, expected):
    client = JsonClient({"https://pypi.org/pypi/datasette-example/json": payload})

    assert update_plugins.latest_pypi_version("datasette-example", client) == expected


def test_add_versions_reuses_pypi_metadata_when_packaging_hash_is_unchanged():
    source = update_plugins.PluginSource(
        name="datasette-cached",
        github_repo="simonw/datasette-cached",
        metadata_file="pyproject.toml",
        metadata_sha256="same-hash",
        metadata_etag='"same-etag"',
    )
    previous = [
        {
            "name": "datasette-cached",
            "github_repo": "simonw/datasette-cached",
            "metadata_file": "pyproject.toml",
            "metadata_sha256": "same-hash",
            "metadata_etag": '"same-etag"',
            "latest_version": "4.2.0",
        }
    ]
    client = JsonClient({})

    records = update_plugins.add_versions([source], previous, client, workers=1)

    assert records == [
        update_plugins.PluginRecord(
            name="datasette-cached",
            github_repo="simonw/datasette-cached",
            metadata_file="pyproject.toml",
            metadata_sha256="same-hash",
            metadata_etag='"same-etag"',
            latest_version="4.2.0",
        )
    ]
    assert client.requested == []


@pytest.mark.parametrize(
    "refresh_pypi,metadata_sha256",
    ((False, "changed-hash"), (True, "same-hash")),
)
def test_add_versions_fetches_pypi_for_changes_or_an_explicit_refresh(
    refresh_pypi, metadata_sha256
):
    source = update_plugins.PluginSource(
        name="datasette-current",
        github_repo="simonw/datasette-current",
        metadata_file="pyproject.toml",
        metadata_sha256=metadata_sha256,
        metadata_etag='"current-etag"',
    )
    previous = [
        {
            "name": "datasette-current",
            "github_repo": "simonw/datasette-current",
            "metadata_file": "pyproject.toml",
            "metadata_sha256": "same-hash",
            "metadata_etag": '"previous-etag"',
            "latest_version": "1.0",
        }
    ]
    pypi_url = "https://pypi.org/pypi/datasette-current/json"
    client = JsonClient({pypi_url: {"info": {"version": "2.0"}}})

    records = update_plugins.add_versions(
        [source],
        previous,
        client,
        workers=1,
        refresh_pypi=refresh_pypi,
    )

    assert records[0].latest_version == "2.0"
    assert client.requested == [(pypi_url, False)]


def test_write_plugins_json_is_sorted_and_has_a_trailing_newline(tmp_path):
    output = tmp_path / "plugins.json"
    records = [
        update_plugins.PluginRecord(
            name="datasette-zebra",
            github_repo="asg017/datasette-zebra",
            metadata_file="setup.py",
            metadata_sha256="bbb",
            metadata_etag='"etag-bbb"',
            latest_version=None,
        ),
        update_plugins.PluginRecord(
            name="datasette-alpha",
            github_repo="datasette/datasette-alpha",
            metadata_file="pyproject.toml",
            metadata_sha256="aaa",
            metadata_etag='"etag-aaa"',
            latest_version="2.0",
        ),
    ]

    update_plugins.write_plugins_json(records, output)

    assert json.loads(output.read_text()) == [
        {
            "name": "datasette-alpha",
            "github_repo": "datasette/datasette-alpha",
            "metadata_file": "pyproject.toml",
            "metadata_sha256": "aaa",
            "metadata_etag": '"etag-aaa"',
            "latest_version": "2.0",
        },
        {
            "name": "datasette-zebra",
            "github_repo": "asg017/datasette-zebra",
            "metadata_file": "setup.py",
            "metadata_sha256": "bbb",
            "metadata_etag": '"etag-bbb"',
            "latest_version": None,
        },
    ]
    assert output.read_bytes().endswith(b"\n")
