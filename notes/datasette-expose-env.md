# datasette-expose-env

Investigated 2026-07-27.

## Recorded result

- Tested release: `0.2` from Git tag `0.2`
- Datasette: `1.0a37`
- Run: `20260715T102157Z-gh-29407843265-a1`
- Recorded outcome: `runner_error`

Pytest stopped while importing the test module:

```text
ModuleNotFoundError: No module named 'datasette_test'
```

The release declares `datasette-test` in its legacy `test` extra. The recorded
environment did not install that extra, so this was a test-environment failure,
not evidence of a plugin compatibility problem.

## Clean reproduction

Current main is clean, matches the `0.2` release, and is synchronized with
origin. An isolated run that explicitly installed `datasette-expose-env[test]`
alongside Datasette 1.0a37 completed with:

```text
5 passed in 0.06s
```

No plugin code problem was reproduced.

## Readiness checker

`uvx ready-for-datasette` reported 6 failures and skipped all 8 build and sdist
checks because the project still uses `setup.py`:

- no `pyproject.toml` and obsolete `setup.py` remains
- HTTPS rather than SSH Git origin
- Python matrix covers 3.8-3.12 rather than 3.10-3.14
- checkout and setup-python Actions are behind the requested versions
- workflow cache paths still reference `setup.py`

Trusted publishing and workflow YAML checks passed.

## Suggested remediation

Treat the recorded error as a runner bug and ensure the release test extra is
installed by the compatibility job. Separately migrate the project to
pyproject-only packaging, update the Python matrix and Actions versions, and
change the cache dependency paths to `pyproject.toml`.
