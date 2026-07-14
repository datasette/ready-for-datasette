# ready-for-datasette

Tracking which Datasette plugins are ready for Datasette 1.0 stable.

## Updating the plugin list

`update_plugins.py` scans the public repositories owned by `simonw`, `dogsheep`,
`datasette`, and `asg017`, identifies Datasette plugins from their packaging
entry points, and writes `plugins.json`.

```bash
uv run --no-project python update_plugins.py
```

Each record includes the ETag and SHA-256 of the repository's `pyproject.toml`
or `setup.py`. The ETag enables conditional raw GitHub requests, and an
unchanged SHA-256 reuses the PyPI version already in `plugins.json`, avoiding an
unnecessary API request. Use `--refresh-pypi` to bypass the PyPI cache:

```bash
uv run --no-project python update_plugins.py --refresh-pypi
```

The `Update plugins` GitHub Actions workflow performs a full refresh every day
at 01:30 UTC and can also be run manually using `workflow_dispatch`. It commits
and pushes `plugins.json` when the output changes.

## Testing a released plugin

`run_plugin_tests.py` resolves the latest Datasette 1.0 alpha and the plugin's
latest PyPI release, then writes its test result under `results/`:

```bash
uv run --no-project python run_plugin_tests.py datasette-cluster-map
```

Only released code is tested. The runner downloads and verifies the SHA-256 of
the non-yanked PyPI source distribution. If the repository has a Git tag that
exactly matches that PyPI version, it uses the test suite from that tag;
otherwise it uses only tests included in the source distribution. It never
tests the repository's unreleased default branch. The package installed in the
test environment is always the verified PyPI source distribution; a Git tag
supplies tests only.

Additional pytest arguments follow `--`:

```bash
uv run --no-project python run_plugin_tests.py datasette-cluster-map -- -x
```

Each immutable run contains `pytest.txt` and `result.json`. The newest result
for a package/Datasette pair is copied to `latest.json`, and `results/index.json`
contains all latest results. A failed test suite is successfully recorded and
does not make the runner command itself fail; infrastructure or metadata errors
do.
