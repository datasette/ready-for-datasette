# datasette-edit-templates

Investigated 2026-07-27.

## Recorded stable-release result

- Tested release: `0.4.3` from Git tag `0.4.3`
- Datasette: `1.0a37`
- Run: `20260714T232953Z-gh-29376290428-a1`
- Recorded outcome: `install_error`

The released tests stopped while loading `tests/conftest.py`:

```text
ModuleNotFoundError: No module named 'datasette_test'
```

The `0.4.3` tag declares `datasette-test>=0.2` in its legacy `test` extra. The
recorded environment did not install that extra, so this error is initially a
test-dependency discovery failure.

## Current alpha reproduction

Current main is clean at version `0.5a0` and requires Datasette 1.0a21 or later.
A dependency-clean run with its full `test` extra and Datasette 1.0a37
completed with:

```text
2 failed, 8 passed, 4 skipped
```

Both failures are tests that try to read the obsolete `ds_csrftoken` response
cookie before posting an edited or new template. The plugin's form template
already renders the current hidden token using `{{ csrftoken() }}`. This points
to updating those two tests to extract the hidden form value rather than a
plugin implementation change.

The four skips are Playwright tests whose separate optional dependency was not
requested.

## Readiness checker

`uvx ready-for-datasette` could not build the project because it still uses
`setup.py`. It reported 5 failures and 8 skips:

- no `pyproject.toml` and obsolete `setup.py` remains
- HTTPS rather than SSH Git origin
- checkout Actions are v4 rather than v7
- workflow cache paths still reference `setup.py`
- all build and sdist checks were skipped

The Python 3.10-3.14 matrix and trusted publishing checks passed. A pre-existing
untracked `build/` directory was left untouched.

## Suggested remediation

Update the two CSRF tests to read the rendered hidden form token, complete the
pyproject migration and workflow modernization, then publish the 0.5 series as
a new release. The stable 0.4.3 run should not be treated as a plugin failure
until its declared test extra is installed.
