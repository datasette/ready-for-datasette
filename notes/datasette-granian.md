# datasette-granian

Investigated 2026-07-27.

## Recorded result

- Tested release: `0.1` from Git tag `0.1`
- Datasette: `1.0a37`
- Run: `20260715T162148Z-gh-29432058538-a1`
- Recorded outcome: `install_error`

Datasette failed while loading the plugin entry point:

```text
ImportError: cannot import name 'Granian' from 'granian.server'
```

An isolated run with the full test extra reproduced the same failure during
pytest configuration.

## Root cause

The plugin has an unbounded `granian` dependency but implements Granian's
older API. Local resolution currently selects Granian 2.7.9:

- `Granian` is now exported from `granian`, not `granian.server`
- `ThreadModes` no longer exists
- the constructor no longer accepts `threads`, `pthreads`, or
  `threading_mode`; its newer controls include `runtime_threads`,
  `blocking_threads`, and `runtime_mode`

The plugin was released in January 2024 against the older API. Granian 1.0.2
and 1.3.0 have all of the imports and constructor arguments used by the plugin.
By 1.4.2, however, the `pthreads` argument had already been removed. Granian
1.7.6 still provides `Granian` from `granian.server` and `ThreadModes`, but no
longer accepts `pthreads`. An upper bound below 2 would therefore avoid the
current import error but would not fully restore compatibility.

This is Granian API drift caused by the unconstrained dependency, not a direct
Datasette 1.0 regression.

## Readiness checker

`uvx ready-for-datasette` reported 6 failures and skipped all 8 build and sdist
checks:

- no `pyproject.toml` and obsolete `setup.py` remains
- HTTPS rather than SSH Git origin
- Python matrix covers 3.8-3.12 rather than 3.10-3.14
- checkout and setup-python Actions are behind the requested versions
- workflow cache paths still reference `setup.py`

Trusted publishing and workflow YAML checks passed.

## Suggested remediation

Port the server setup to Granian 2's current imports and runtime constructor
options, then add an explicit minimum Granian version matching that
implementation. Pinning to the old 1.3 API would be a short-term alternative,
not a durable fix. Also migrate to pyproject-only packaging and modernize the
test matrix and Actions versions before publishing a new release.
