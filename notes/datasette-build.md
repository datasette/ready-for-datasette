# datasette-build

Investigated 2026-07-27.

## Recorded result

- Tested release: `0.1a0` from Git tag `0.1a0`
- Datasette: `1.0a37`
- Run: `20260714T164652Z-local-12b6ec`
- Recorded outcome: `collection_error`
- Result: 4 collected tests, all 4 errored during fixture setup

Every test shares a session fixture that constructs:

```python
CliRunner(mix_stderr=False)
```

The unbounded `click` dependency resolves a current Click release whose
`CliRunner.__init__()` no longer accepts `mix_stderr`. The resulting
`TypeError` occurs before any plugin or Datasette behavior is exercised.

This is a real released-test incompatibility with current Click, not evidence
of a Datasette 1.0 API break. The likely test update is to construct
`CliRunner()` without `mix_stderr` and continue using the current result output
attributes.

## Packaging and checker findings

The clean local checkout matches release `0.1a0` and declares:

- an unbounded runtime dependency on `click`
- a `test` optional extra containing pytest and pytest-asyncio
- a separate optional `datasette` extra

`uvx ready-for-datasette` reported 6 failures and 1 skip:

- deprecated table-form project license metadata
- HTTPS rather than SSH Git origin
- Python matrices do not cover 3.10-3.14
- obsolete checkout and setup-python Actions
- the test workflow still references `setup.py`
- its sdist test command did not install the declared `test` extra and
  consequently could not import pytest
- stable-Datasette testing was skipped because the package is an alpha

Trusted publishing and the clean build itself passed.

## Suggested remediation

1. Update the CliRunner fixture for current Click and run the four tests.
2. Consider a supported Click range if compatibility with older Click remains
   important.
3. Update the license field, origin, Python matrix, Actions, and stale workflow
   conditions.
4. Ensure readiness tooling installs the sdist's declared test dependencies
   before using its result as a compatibility verdict.
5. Publish and retest a new release against Datasette 1.0.
