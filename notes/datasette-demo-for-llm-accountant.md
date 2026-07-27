# datasette-demo-for-llm-accountant

Investigated 2026-07-27.

## Recorded result

- Tested release: `0.1a0` from Git tag `0.1a0`
- Datasette: `1.0a37`
- Run: `20260714T230918Z-gh-29375239846-a1`
- Recorded outcome: `install_error`

Plugin loading failed before pytest collection:

```text
ImportError: cannot import name 'LlmWrapper' from 'datasette_llm_accountant'
```

Both the plugin module and its tests directly import and instantiate
`LlmWrapper`.

## Root cause

The demo declares:

```toml
datasette-llm-accountant>=0.1a0
```

The local history of `datasette-llm-accountant` shows that `LlmWrapper` was
exported in versions 0.1a0 and 0.1a1, but is absent from 0.1a2 and the current
0.1a3. The lower-bound-only requirement therefore permits an incompatible
dependency release. The current accountant API uses the newer hook-based
integration instead of the old wrapper class.

This is dependency API drift in the demo, not a direct Datasette 1.0 failure.

## Readiness checker

The demo checkout is clean on `main` and matches `origin/main`. Running
`uvx ready-for-datasette` reported 3 failures and 1 skip:

- HTTPS rather than SSH Git origin
- checkout Actions are v5 rather than v7
- the sdist test command did not install the declared `test` extra and could
  not import pytest
- stable-Datasette testing was skipped because the demo is an alpha release

The build, package metadata, Python 3.10-3.14 matrix, and trusted publishing
checks passed.

## Suggested remediation

Update the demo to the current `datasette-llm-accountant` hook/API model and
raise its dependency floor to the version providing that API. A temporary
upper bound below 0.1a2 would restore the old wrapper but would leave the demo
on an obsolete integration. After updating the code and tests, publish a new
demo release and rerun its sdist with the test extra installed.
