# datasette-block

Investigated 2026-07-27.

## Recorded result

- Tested release: `0.1.1` from Git tag `0.1.1`
- Datasette: `1.0a37`
- Run: `20260714T165042Z-gh-29351285530-a1`
- Recorded outcome: `runner_error`

Pytest stopped while importing `tests/test_block.py`:

```text
ModuleNotFoundError: No module named 'asgi_lifespan'
```

The released tag's `setup.py` declares `asgi-lifespan` in its `test` extra,
along with pytest and pytest-asyncio. The recorded environment installed the
base package but did not select that extra. This is a test-dependency discovery
failure, not evidence that the plugin itself is incompatible with Datasette
1.0.

## Local checkout and reproduction

The checkout at `/Users/simon/dev/ecosystem/datasette-block` contains
uncommitted migration work: `setup.py` is deleted, a `pyproject.toml` is
untracked, and tests and `.gitignore` are modified. The new pyproject dev group
does include `asgi-lifespan`, pytest, pytest-asyncio, and httpx.

Running `uvx ready-for-datasette` against those local files built an sdist and
passed both available test cases against:

- Datasette 1.0a37: 2 passed
- Datasette 0.65.2: 2 passed

That confirms the missing test dependency is sufficient to explain the
recorded collection failure, although it tests the local migration rather than
the unchanged release tag.

## Other readiness problems

The readiness checker reported 6 failures in the local migration:

- deprecated table-form project license metadata
- HTTPS rather than SSH Git origin
- Python matrices stop at 3.9 instead of covering 3.10-3.14
- obsolete checkout and setup-python Actions
- token/twine publishing instead of trusted publishing
- workflow cache/build steps still reference `setup.py`

## Suggested remediation

Finish the in-progress pyproject migration, update the license and workflows,
and publish a new release. The released `0.1.1` result can also be corrected by
rerunning it with its declared `test` extra; no plugin code change is indicated
by the recorded error itself.
