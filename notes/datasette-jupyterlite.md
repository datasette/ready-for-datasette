# datasette-jupyterlite

Investigated 2026-07-27.

## Recorded result

- Tested release: `0.1a1` from Git tag `0.1a1`
- Datasette: `1.0a37`
- Run: `20260716T105652Z-gh-29492614433-a1`
- Recorded outcome: `install_error`

Datasette failed while importing the plugin:

```text
IndexError: list index out of range
```

The failing module-level expression is:

```python
list(files("jupyterlite").glob("*.tgz"))[0]
```

## Root cause

The plugin has an unbounded `jupyterlite` dependency and assumes that package
contains a prebuilt `jupyterlite-app-*.tgz` archive. Current local resolution
selects JupyterLite 0.8.1, whose Python package contains no `.tgz` file.

The archive exists in JupyterLite 0.1.0b16 through 0.1.0b18. It is absent
starting with 0.1.0b19 and in the subsequent stable versions tested. The plugin
therefore depends on a beta-era JupyterLite distribution layout that changed
shortly after this plugin's November 2021 release.

With JupyterLite forced to 0.1.0b18, the exact plugin checkout and its complete
test extra pass on Datasette 1.0a37:

```text
2 passed in 0.08s
```

This confirms that the recorded failure is dependency asset-layout drift, not
a Datasette 1.0 API problem.

## Readiness checker

`uvx ready-for-datasette` reported 7 failures and skipped all 8 build and sdist
checks:

- no `pyproject.toml` and obsolete `setup.py` remains
- HTTPS rather than SSH Git origin
- Python matrix only covers 3.7-3.10
- checkout and setup-python Actions are still v2
- release workflow uses a PyPI token and twine rather than trusted publishing
- workflow cache paths still reference `setup.py`

Workflow YAML parsing passed.

## Suggested remediation

Build a JupyterLite site using the current JupyterLite toolchain and package
those static assets inside `datasette-jupyterlite`, rather than reading a
private archive from the dependency at import time. A pin to 0.1.0b18 would
only be a short-term compatibility workaround. Then migrate packaging and
publishing workflows and release a new version.
