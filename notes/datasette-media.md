# datasette-media

Investigated 2026-07-27.

## Recorded result

- Tested release: `0.5.1` from Git tag `0.5.1`
- Datasette: `1.0a37`
- Run: `20260717T082954Z-gh-29566605171-a1`
- Recorded outcome: `install_error`

Datasette failed while importing the plugin:

```text
ModuleNotFoundError: No module named 'imghdr'
```

`datasette_media/utils.py` imports `imghdr` at module scope and uses
`imghdr.what()` to identify image bytes. The deprecated standard-library module
was removed in Python 3.13, so the plugin cannot load on any current 3.13 or
3.14 environment.

## Additional test compatibility

An isolated Python 3.12 run avoids the `imghdr` removal and reaches the suite,
but with current HTTPX it produces:

```text
16 failed, 12 passed
```

All 16 failures use the removed `httpx.AsyncClient(app=app)` test shortcut and
raise:

```text
TypeError: AsyncClient.__init__() got an unexpected keyword argument 'app'
```

Forcing HTTPX 0.27.2 on Python 3.12 produces:

```text
28 passed, 16 warnings
```

The warnings already identify the replacement:
`httpx.ASGITransport(app=app)`. This shows that the plugin otherwise works with
Datasette 1.0a37 once the Python and test-client compatibility blockers are
removed.

## Local checkout and readiness checker

The checkout matches release 0.5.1 but has a pre-existing untracked
`pyproject.toml`; it was inspected and left untouched. The file duplicates the
legacy `setup.py` metadata and still uses deprecated table-form license
metadata.

`uvx ready-for-datasette` evaluated that working tree and reported 9 failures:

- obsolete `setup.py` remains beside the untracked pyproject
- the pyproject license uses deprecated table form
- HTTPS rather than SSH Git origin
- Python matrix only covers 3.7-3.11
- checkout and setup-python Actions are behind the requested versions
- release workflow uses a PyPI token and twine rather than trusted publishing
- workflow cache paths still reference `setup.py`
- both sdist test checks omitted the declared `test` extra and could not import
  pytest

The project built successfully from the untracked pyproject and its wheel,
metadata, and sdist contents passed.

## Suggested remediation

Replace `imghdr` with a maintained image-signature implementation or Pillow
inspection, update tests to use `ASGITransport` or `datasette.client`, finish
and commit the pyproject-only migration, modernize the workflows, and publish a
new release.
