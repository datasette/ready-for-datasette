# datasette-enrichments-opencage

Investigated 2026-07-27.

## Recorded result

- Tested release: `0.1.1` from Git tag `0.1.1`
- Datasette: `1.0a37`
- Run: `20260715T000009Z-gh-29377747648-a1`
- Recorded outcome: `collection_error`

All four parameterized test cases fail at the same line:

```text
KeyError: 'ds_csrftoken'
```

Each case obtains the token from a `ds_csrftoken` cookie on the enrichment form
response before it posts the form. The four accompanying `pytest-httpx`
teardown errors are a consequence: execution never reaches the mocked OpenCage
request, so the registered mock remains unused.

## Root cause

Datasette 1.0a37 replaced token-and-cookie CSRF enforcement with
same-origin request-header checks. It retains the `csrftoken()` template helper
for plugin compatibility, but no longer issues a `ds_csrftoken` response
cookie. The tests therefore fail before exercising the plugin.

This is a test compatibility problem. A client POST with neither an `Origin`
nor a `Sec-Fetch-Site` header is treated as a non-browser request and does not
need the old cookie or form token. A browser-like test can instead send
same-origin headers. The unused HTTP mock errors should disappear once the POST
is reached.

## Current checkout and readiness checker

Current main is clean, matches the `0.1.1` release, and declares pytest,
pytest-asyncio, and pytest-httpx in its `test` extra.

`uvx ready-for-datasette` reported 7 failures:

- deprecated table-form project license
- HTTPS rather than SSH Git origin
- Python matrix covers 3.8-3.11 rather than 3.10-3.14
- checkout and setup-python Actions are behind the requested versions
- release workflow uses token/twine publishing rather than trusted publishing
- both sdist test checks omitted the declared `test` extra and failed to
  import pytest

The project built successfully and its metadata and sdist contents passed.
The two checker sdist failures are checker-environment failures, distinct from
the recorded test incompatibility above.

## Suggested remediation

Remove the obsolete CSRF cookie/token setup from the test and exercise the POST
as a non-browser client, or supply appropriate same-origin headers. Then
modernize the packaging metadata and workflows and publish a new release.
