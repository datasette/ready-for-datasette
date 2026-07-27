# datasette-indieauth

Investigated 2026-07-27.

## Recorded result

- Tested release: `1.2.2` from Git tag `1.2.2`
- Datasette: `1.0a37`
- Run: `20260714T164703Z-local-659f18`
- Recorded outcome: `runner_error`

Pytest stopped while importing the test module:

```text
ModuleNotFoundError: No module named 'mf2py'
```

The release declares mf2py in its `test` extra. The recorded environment did
not install that extra, so this error is a runner dependency problem.

## Full test result and root causes

Current main is clean, matches release 1.2.2, and is synchronized with origin.
An isolated run with the complete test extra and Datasette 1.0a37 reached the
suite and produced:

```text
18 failed, 49 passed, 9 errors
```

The errors fall into four main groups:

1. `datasette.metadata()` no longer exists. `indieauth_page()` calls it for
   every rendered login or error page, causing 500 responses and cascading
   unused HTTP-mock teardown errors. Instance metadata is now obtained
   asynchronously with `await datasette.get_instance_metadata()`.
2. The `permission_allowed()` plugin hook has been removed. As a result,
   `restrict_access` no longer restricts the instance. The plugin needs the
   `permission_resources_sql()` hook and `PermissionSQL` responses. Its test
   must also move plugin configuration from the obsolete `metadata=` argument
   to `config=`.
3. The flow tests read and submit the removed `ds_csrftoken` cookie. Datasette
   1.0a37 now uses same-origin request-header CSRF checks, so those tests need
   to stop using the legacy cookie/token sequence or send browser-like
   same-origin headers.
4. One redirect-loop utility test assumes a pytest-httpx response can match
   repeatedly. Current pytest-httpx consumes a mock once by default, so the
   test gets an unmatched second request instead of the expected
   `TooManyRedirects`. Mark that response reusable or configure reusable
   responses for the test.

The nine teardown errors are mostly downstream effects of earlier page-render
failures: registered HTTP responses are never requested.

## Readiness checker

`uvx ready-for-datasette` reported 7 failures and skipped all 8 build and sdist
checks:

- no `pyproject.toml` and obsolete `setup.py` remains
- HTTPS rather than SSH Git origin
- Python matrix only covers 3.7-3.11
- checkout and setup-python Actions are several versions behind
- release workflow uses a PyPI token and twine rather than trusted publishing
- workflow cache paths still reference `setup.py`

Workflow YAML parsing passed.

## Suggested remediation

Port metadata, permissions, configuration, and CSRF tests to the Datasette 1.0
APIs; update the reusable redirect mock; then migrate to pyproject-only
packaging and modern publishing workflows before releasing a new version.
