# datasette-hashed-urls

Investigated 2026-07-27.

## Recorded result

- Tested release: `0.4` from Git tag `0.4`
- Datasette: `1.0a37`
- Run: `20260715T184431Z-gh-29441753325-a1`
- Recorded outcome: `runner_error`

Pytest stopped while importing the test module:

```text
ModuleNotFoundError: No module named 'pytest_asyncio'
```

The release declares pytest-asyncio, pytest, and sqlite-utils in its `test`
extra. The recorded environment did not install that extra, so the reported
error is a test-runner dependency problem.

## Release and current-main reproductions

Running the exact `0.4` tag in an isolated environment with its full test extra
and Datasette 1.0a37 produced:

```text
5 failed, 24 passed
```

Those five failures reflect Datasette's newer redirect to the `/-/query` view
for SQL query URLs. The expected responses in the old tests do not account for
that extra redirect.

Current main contains a post-release commit specifically updating the tests for
this Datasette 1.0 behavior. A clean isolated run of current main with
Datasette 1.0a37 produced:

```text
29 passed in 0.80s
```

The current plugin code and updated tests therefore work, but the fix has not
been released.

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

Publish the existing test compatibility update as a new release after migrating
to pyproject-only packaging and modernizing the workflows. The compatibility
runner should install the package's declared test extra so that it reaches the
tests instead of failing on pytest-asyncio.
