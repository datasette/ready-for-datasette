# datasette-auth0

Investigated 2026-07-27.

## Recorded result

- Tested release: `0.1` from Git tag `0.1`
- Datasette: `1.0a37`
- Run: `20260714T164644Z-local-45e283`
- Recorded outcome: `install_error`
- Pytest did not reach collection or produce a JSON report

Datasette loads plugin entry points during pytest configuration. Importing
`datasette_auth0` immediately failed with:

```text
ModuleNotFoundError: No module named 'baseconv'
```

## Root cause

`datasette_auth0/__init__.py` imports `baseconv` and uses
`baseconv.base62.encode()`, but release `0.1` declares only `datasette` as a
runtime dependency. The plugin was relying on an incidental transitive
dependency of older Datasette releases. Datasette 1.0a37 does not install
`baseconv`, exposing the undeclared dependency.

The release also declares pytest, pytest-asyncio, and pytest-httpx in a legacy
`test` extra. The recorded runner did not select that extra, so after the
runtime import is fixed the released test suite still needs to be rerun with
its declared test dependencies.

## Readiness checker

Running `uvx ready-for-datasette` in the clean local checkout reported 7
failures:

- packaging still uses `setup.py` and has no `pyproject.toml`
- the Git origin uses HTTPS rather than SSH
- the test matrices cover Python 3.7-3.10 rather than 3.10-3.14
- checkout and setup-python Actions are obsolete
- publishing uses a PyPI token and twine rather than trusted publishing
- workflows still reference `setup.py`
- build and sdist test checks were skipped because there is no pyproject file

## Local checkout

`/Users/simon/dev/ecosystem/datasette-auth0` is clean on `main` and matches
`origin/main`. Its latest commit and release date from 2022.

## Suggested remediation

1. Declare `baseconv` as a runtime dependency (and audit the other direct
   imports, including `httpx`).
2. Migrate packaging and test dependencies to `pyproject.toml`.
3. Modernize the Python matrix, Actions, SSH origin, and trusted publishing.
4. Release a new version and retest its sdist against Datasette 1.0 in a
   dependency-clean environment.
