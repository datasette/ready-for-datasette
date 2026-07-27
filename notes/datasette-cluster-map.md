# datasette-cluster-map

Investigated 2026-07-27.

## Recorded result

- Tested release: `0.18.2` from Git tag `0.18.2`
- Datasette: `1.0a37`
- Run: `20260714T164658Z-local-40bad8`
- Recorded outcome: `install_error`

The released tests stopped while loading `tests/conftest.py`:

```text
ModuleNotFoundError: No module named 'datasette_test'
```

The `0.18.2` tag's legacy `setup.py` does declare `datasette-test` in its
`test` extra. The recorded environment did not install that extra, so the
failure is missing test dependency discovery rather than a plugin import or
Datasette API failure.

## Current main

Commit `d6b2362` migrated the project to `pyproject.toml` on 2026-07-16, after
the recorded run. The current metadata declares `datasette-test` in both the
`test` optional extra and the default dev dependency group, along with the
other required test tools.

Running `uvx ready-for-datasette` on current main passed all 19 checks:

- Datasette 1.0a37: 29 passed, 5 skipped
- Datasette 0.65.2: 29 passed, 5 skipped
- clean build, current metadata, current Actions, SSH origin, and trusted
  publishing all passed

The local checkout has an uncommitted JavaScript modification and an untracked
`uv.lock`; those files were left untouched. The dependency declarations and
committed migration are sufficient to explain why the current check succeeds.

## Conclusion

The recorded PyPI release produced an incomplete compatibility verdict because
its test extra was not installed. Current main appears ready for both Datasette
versions.

## Suggested remediation

Publish the pyproject migration as a new package version (the current
pyproject still says `0.18.2`, which is already released), then rerun the new
sdist through the scoreboard. Do not infer a plugin code fix from the old
missing-`datasette_test` result.
