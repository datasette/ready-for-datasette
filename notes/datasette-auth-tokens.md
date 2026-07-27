# datasette-auth-tokens

Investigated 2026-07-27.

## Recorded result

- Tested release: `0.3` from Git tag `0.3`
- Datasette: `1.0a37`
- Run: `20260714T164643Z-local-2c1a89`
- Recorded outcome: `collection_error`
- Result: 27 collected tests, all 27 errored during setup

The isolated command installed the base `datasette-auth-tokens` package,
pytest, and Datasette, but no test dependencies. Pytest consequently did not
load `pytest-asyncio`: it warned that every `@pytest.mark.asyncio` mark was
unknown and reported that the async `ds` fixture had no supporting plugin.
The later fixture assertion errors are cascading failures from that first
setup problem.

## Packaging evidence

The `0.3` tag's `setup.py` declares a `test` extra containing:

- `pytest`
- `pytest-asyncio`
- `httpx`
- `sqlite-utils`

The recorded result has `package_extra: null`, no dependency source, and an
empty dependency list. Its command used the base sdist requirement rather than
`datasette-auth-tokens[test]`. This means the run did not install the
dependencies that the released project declares for its tests.

## Local checkout

The checkout at `/Users/simon/dev/ecosystem/datasette-auth-tokens` is on
`main`, ahead of `origin/main`, and contains both tracked and untracked local
changes. It identifies itself as unreleased version `0.4a13` and now declares
its test tools in a `dev` dependency group. Those newer local files were not
used as a substitute for the released `0.3` evidence.

## Conclusion

This result is an incomplete compatibility verdict. The immediate problem is
legacy test-extra discovery in the `ready-for-datasette` runner, not a proven
Datasette 1.0 incompatibility in the plugin.

Retest release `0.3` with its `test` extra (or the four dependencies above)
installed. Only failures remaining after that clean retest should be treated as
plugin compatibility work.
