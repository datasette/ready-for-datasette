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
