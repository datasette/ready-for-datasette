# datasette-ics

Investigated 2026-07-27.

## Recorded result

- Tested release: `0.5.2` from Git tag `0.5.2`
- Datasette: `1.0a37`
- Run: `20260715T204931Z-gh-29449724632-a1`
- Recorded outcome: `install_error`

Datasette failed while importing the plugin's `ics==0.7.2` dependency:

```text
ValueError: Unknown settings for ParserConfig: {'buffer_class'}
```

## Dependency root cause

ics 0.7.2 requires only `tatsu>4.2`, so it resolves to newer incompatible Tatsu
releases. Local resolution currently installs Tatsu 5.24.0 and reproduces the
same import failure. Tatsu 5.18.0 through 5.24.0 reject the `buffer_class`
setting in the parser generated and shipped by ics 0.7.2. Tatsu 5.16.0 imports
that ics release successfully; Tatsu 5.17.0 has a separate undeclared `rich`
import problem in this environment.

This failure occurs below the Datasette plugin itself. The immediate workaround
is a compatible Tatsu upper bound, but the durable fix is to move away from the
old ics 0.7.2 parser stack.

## Datasette 1.0 compatibility

After forcing Tatsu 5.16.0, the exact 0.5.2 release reached pytest but all five
tests failed:

```text
5 failed
```

Four tests still use pre-1.0 query URLs and receive the newer redirects. The
canned-query test still passes query configuration through `metadata` and
receives a 404.

The local checkout has pre-existing uncommitted changes to the plugin and tests
that attempt the Datasette 1.0 migration; they were inspected but left
untouched. With those changes and Tatsu 5.16.0, the result improves to:

```text
1 failed, 4 passed
```

The remaining canned-query test returns 500 because the new code calls
`datasette.get_canned_query()`, which does not exist in Datasette 1.0a37. The
available API is `await datasette.get_query(database, name)`, returning a
`StoredQuery` object.

## Readiness checker

`uvx ready-for-datasette` reported 7 failures and skipped all 8 build and sdist
checks:

- no `pyproject.toml` and obsolete `setup.py` remains
- HTTPS rather than SSH Git origin
- Python matrix only covers 3.7-3.10
- checkout and setup-python Actions are still v3
- release workflow uses a PyPI token and twine rather than trusted publishing
- workflow cache paths still reference `setup.py`

Workflow YAML parsing passed.

## Suggested remediation

Finish the in-progress Datasette 1.0 port by replacing both
`get_canned_query()` calls with the current stored-query API and adapting to its
object attributes. Replace or constrain the incompatible ics/Tatsu dependency,
then migrate packaging and workflows and publish a new release.
