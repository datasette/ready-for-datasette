# datasette-edit-schema

Investigated 2026-07-27.

## Recorded stable-release result

- Tested release: `0.7.1` from Git tag `0.7.1`
- Datasette: `1.0a37`
- Run: `20260714T232954Z-gh-29376290428-a1`
- Recorded outcome: `runner_error`

Collection stopped because `tests/test_edit_schema.py` imports
`BeautifulSoup`:

```text
ModuleNotFoundError: No module named 'bs4'
```

The `0.7.1` tag declares `beautifulsoup4` and `html5lib` in its legacy `test`
extra. The recorded environment did not install that extra. The stable-release
result is therefore an incomplete verdict caused by test-dependency discovery.

## Current alpha reproduction

Current main is version `0.8a5`, depends on Datasette 1.0a21 or later, and
declares pytest, pytest-asyncio, beautifulsoup4, and html5lib in its `test`
extra. A clean manual run that installed that package extra and pinned
Datasette 1.0a37 completed with:

```text
55 failed, 25 passed
```

The failures cluster around real Datasette 1.0 changes:

- many tests expect a `ds_csrftoken` response cookie that is no longer set
- table-action links expected by the plugin tests are absent
- a CSRF-required POST expects 403 but receives 405
- most schema-changing POST tests cascade from the missing cookie assumption

The alpha therefore needs test and likely plugin updates for the current CSRF
and action/route behavior even though the older scoreboard run did not get far
enough to show them.

## Readiness checker

`uvx ready-for-datasette` reported 3 failures and 1 skip:

- HTTPS rather than SSH Git origin
- checkout Actions are v5 rather than v7
- the checker did not install the declared `test` extra and could not import
  pytest for its sdist run
- stable testing was skipped because 0.8a5 is an alpha

The checkout otherwise passed metadata, build, Python matrix, and trusted
publishing checks. It has a pre-existing untracked `build/` directory, which
was left untouched.

## Suggested remediation

Update the 0.8 series for Datasette's current CSRF token flow, then investigate
the table-action and route-status differences. Rerun the complete 80-test suite
until it passes, modernize the origin and checkout Actions, and publish a new
stable release so the scoreboard no longer selects 0.7.1.
