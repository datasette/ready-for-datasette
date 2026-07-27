# datasette-import

Investigated 2026-07-27.

## Recorded result

- Tested release: `0.1a6` from Git tag `0.1a6`
- Datasette: `1.0a37`
- Run: `20260715T214248Z-gh-29452881266-a1`
- Recorded outcome: `install_error`

The environment could not be resolved because release 0.1a6 has an exact
runtime pin:

```toml
datasette==1.0a19
```

That requirement directly conflicts with the compatibility runner's
`datasette==1.0a37`. The exact release still passes its one test when installed
with its intended Datasette 1.0a19 version, but it cannot be tested against any
other Datasette version.

## In-progress local migration

The local checkout has pre-existing uncommitted changes to the package,
permission API usage, and test; they were inspected but left untouched. They:

- replace the exact pin with `datasette>=1.0a21`
- use `DatabaseResource`, `TableResource`, and `datasette.allowed()`
- enable the root actor explicitly in the test
- update the license metadata and minimum Python version

An isolated run of this working tree with its full test extra and Datasette
1.0a37 completed with:

```text
1 passed in 0.06s
```

The changes on disk therefore resolve the package's Datasette compatibility
problem, although they are not committed or released in that checkout.

## Readiness checker

`uvx ready-for-datasette` evaluated the modified working tree and reported 2
failures and 1 skip:

- checkout Actions are v5 rather than v7
- the sdist test command omitted the declared `test` extra and could not import
  pytest
- stable-Datasette testing was skipped because this is an alpha release

All packaging, build, metadata, sdist-content, Python 3.10-3.14 matrix, SSH
origin, and trusted-publishing checks passed.

## Suggested remediation

Complete and commit the existing migration, update checkout Actions, and
publish a new alpha. The compatibility runner should install the package's test
extra when testing its sdist.
