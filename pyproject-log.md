# Pyproject migration log

Started 2026-07-27.

## Scope

- Source: the 112 repository entries in `plugins.json` whose recorded
  `metadata_file` is `setup.py`
- Local checkouts initially found by exact GitHub origin: 102
- Additional checkouts required: 10
- Required result for each repository:
  - replace legacy packaging with `pyproject.toml`
  - include a `[dependency-groups]` `dev` group
  - replace workflow uses of `pip install .[test]` with
    `pip install . --group dev`
  - run `uv build`
  - inspect the wheel for the expected package files
  - inspect the source distribution and confirm that it contains the tests
  - commit locally without pushing

## Progress

Migration work is complete. Every row was built, inspected, and committed
locally; no commits were pushed.

| Repository | Status | Build | Wheel | Sdist tests | Commit | Notes |
|---|---|---|---|---|---|---|
| `asg017/datasette-app-support` | Complete | Pass | Pass | Pass | `fe0f0dd` | Two workflows updated |
| `asg017/datasette-geojson` | Complete | Pass | Pass | Pass | `674fb28` | Two workflows updated |
| `asg017/datasette-leaflet-geojson` | Complete | Pass | Pass | Pass | `58ea8b5` | Two workflows updated |
| `asg017/datasette-socrata` | Complete | Pass | Pass | Pass | `44965ae` | Two workflows updated |
| `asg017/datasette-upload-csvs` | Complete | Pass | Pass | Pass | `475622b` | Two workflows updated |
| `asg017/datasette-upload-dbs` | Complete | Pass | Pass | Pass | `a50b686` | Two workflows updated |
| `datasette/datasette-import-table` | Complete | Pass | Pass | Pass | `a0afee1` | Two workflows updated |
| `eyeseast/datasette-census-boundaries` | Complete | Pass | Pass | Pass | `eb2148e` | Two workflows updated |
| `eyeseast/datasette-geojson` | Complete | Pass | Pass | Pass | `674fb28` | Two workflows updated |
| `eyeseast/datasette-leaflet` | Complete | Pass | Pass | Pass | `e1e4e9c` | Two workflows updated |
| `eyeseast/datasette-query-files` | Complete | Pass | Pass | Pass | `b9a5b4d` | Two workflows updated |
| `simonw/datasette-app-support` | Complete | Pass | Pass | Pass | `86d6c09` | Two workflows updated |
| `simonw/datasette-auth-existing-cookies` | Complete | Pass | Pass | Pass | `66daeab` | Root-level test included; two workflows updated |
| `simonw/datasette-auth-passwords` | Complete | Pass | Pass | Pass | `473fb4a` | Two workflows updated |
| `simonw/datasette-auth0` | Complete | Pass | Pass | Pass | `45122b7` | Two workflows updated |
| `simonw/datasette-basemap` | Complete | Pass | Pass | Pass | `d1f136c` | Finished an existing partial migration; two workflows updated |
| `simonw/datasette-big-local` | Complete | Pass | Pass | Pass | `2fe5918` | Two workflows updated |
| `simonw/datasette-block` | Complete | Pass | Pass | Pass | `4baf652` | Existing unrelated `tests/test_block.py` edit left unstaged; two workflows updated |
| `simonw/datasette-bplist` | Complete | Pass | Pass | Pass | `6a41d15` | No matching workflow install |
| `simonw/datasette-chatgpt-plugin` | Complete | Pass | Pass | Pass | `47d27c4` | Two workflows updated |
| `simonw/datasette-codespaces` | Complete | Pass | Pass | Pass | `c872f87` | Two workflows updated |
| `simonw/datasette-column-inspect` | Complete | Pass | Pass | Pass | `c0cd9ba` | Version normalized to `0.2a0`; two workflows updated |
| `simonw/datasette-configure-asgi` | Complete | Pass | Pass | Pass | `f0fdb9e` | Single-module setuptools build; no matching workflow install |
| `simonw/datasette-cookies-for-magic-parameters` | Complete | Pass | Pass | Pass | `e208f19` | Two workflows updated |
| `simonw/datasette-copy-to-memory` | Complete | Pass | Pass | Pass | `1263f94` | Two workflows updated |
| `simonw/datasette-copyable` | Complete | Pass | Pass | Pass | `fa21709` | Two workflows updated |
| `simonw/datasette-cors` | Complete | Pass | Pass | Pass | `6725755` | Single-module setuptools build; two workflows updated |
| `simonw/datasette-debug-asgi` | Complete | Pass | Pass | Pass | `6e1342f` | Finished an existing partial migration; two workflows updated |
| `simonw/datasette-rure` | Complete | Pass | Pass | Pass | `86492dc` | No matching workflow install |
| `simonw/datasette-sandstorm-support` | Complete | Pass | Pass | Pass | `febea64` | Two workflows updated |
| `simonw/datasette-saved-queries` | Complete | Pass | Pass | Pass | `38f7e5e` | Two workflows updated |
| `simonw/datasette-schema-versions` | Complete | Pass | Pass | Pass | `7fc3a03` | Two workflows updated |
| `simonw/datasette-seaborn` | Complete | Pass | Pass | Pass | `9f12fdd` | Two workflows updated |
| `simonw/datasette-search-all` | Complete | Pass | Pass | Pass | `75ea631` | No matching workflow install |
| `simonw/datasette-secret-santa` | Complete | Pass | Pass | Pass | `9c174f8` | Two workflows updated |
| `simonw/datasette-sentry` | Complete | Pass | Pass | Pass | `66acb83` | Single-module setuptools build; two workflows updated |
| `simonw/datasette-show-errors` | Complete | Pass | Pass | Pass | `5926449` | Single-module setuptools build; no matching workflow install |
| `simonw/datasette-simple-html` | Complete | Pass | Pass | Pass | `5d52a5c` | Two workflows updated |
| `simonw/datasette-sitemap` | Complete | Pass | Pass | Pass | `167b207` | Two workflows updated |
| `simonw/datasette-socrata` | Complete | Pass | Pass | Pass | `e5c9836` | Two workflows updated |
| `simonw/datasette-spotify-embed` | Complete | Pass | Pass | Pass | `f3eea71` | Two workflows updated |
| `simonw/datasette-sql-scraper` | Complete | Pass | Pass | N/A | `7ccc88b` | Repository has no tests; no matching workflow install |
| `simonw/datasette-sqlite-fts4` | Complete | Pass | Pass | Pass | `632fd21` | Pre-existing generated files left untracked; two workflows updated |
| `simonw/datasette-sqlite-url-lite` | Complete | Pass | Pass | Pass | `82caa99` | Two workflows updated |
| `simonw/datasette-template-request` | Complete | Pass | Pass | Pass | `d285939` | Two workflows updated |
| `simonw/datasette-tiddlywiki` | Complete | Pass | Pass | Pass | `38bd903` | Two workflows updated |
| `simonw/datasette-tiles` | Complete | Pass | Pass | Pass | `8b91d10` | Two workflows updated |
| `simonw/datasette-total-page-time` | Complete | Pass | Pass | Pass | `099ec8d` | Two workflows updated |
| `simonw/datasette-unsafe-expose-env` | Complete | Pass | Pass | Pass | `92158bb` | Two workflows updated |
| `simonw/datasette-upload-csvs` | Complete | Pass | Pass | Pass | `2d6c1f4` | Two workflows updated |
| `simonw/datasette-upload-dbs` | Complete | Pass | Pass | Pass | `3cc3902` | Two workflows updated |
| `simonw/datasette-vega` | Complete | Pass | Pass | Pass | `73010f9` | No matching workflow install |
| `simonw/datasette-verify` | Complete | Pass | Pass | Pass | `2e72d51` | Two workflows updated |
| `simonw/datasette-write` | Complete | Pass | Pass | Pass | `fadb1da` | Finished an existing partial migration; two workflows updated |
| `simonw/datasette-x-forwarded-host` | Complete | Pass | Pass | Pass | `cf41ff2` | Two workflows updated |
| `simonw/datasette-yaml` | Complete | Pass | Pass | Pass | `faa1bec` | Pre-existing generated `build/` left untracked; two workflows updated |
| `simonw/datasette-media` | Complete | Pass | Pass | Pass | `30a0c0b` | Finished an existing partial migration; pre-existing `build/` left untracked; two workflows updated |
| `simonw/datasette-mp3-audio` | Complete | Pass | Pass | Pass | `fd70758` | Two workflows updated |
| `simonw/datasette-multiline-links` | Complete | Pass | Pass | Pass | `62c12f2` | Two workflows updated |
| `simonw/datasette-no-truncate` | Complete | Pass | Pass | Pass | `ccfd251` | Two workflows updated |
| `simonw/datasette-notebook` | Complete | Pass | Pass | Pass | `d7796f3` | Two workflows updated |
| `simonw/datasette-openai` | Complete | Pass | Pass | Pass | `1e09997` | Two workflows updated |
| `simonw/datasette-paste-table` | Complete | Pass | Pass | Pass | `eaf3930` | Two workflows updated |
| `simonw/datasette-permissions-sql` | Complete | Pass | Pass | Pass | `37b4598` | No matching workflow install |
| `simonw/datasette-placekey` | Complete | Pass | Pass | Pass | `8797b06` | Two workflows updated |
| `simonw/datasette-plugin-demos` | Complete | Pass | Pass | Pass | `ced58bf` | Pre-existing cache files left untracked; two workflows updated |
| `simonw/datasette-plugin-template-repository-demo-old` | Complete | Pass | Pass | Pass | `705600f` | No matching workflow install |
| `simonw/datasette-pretty-json` | Complete | Pass | Pass | Pass | `91f4b82` | Two workflows updated |
| `simonw/datasette-psutil` | Complete | Pass | Pass | Pass | `1cd295a` | Two workflows updated |
| `simonw/datasette-publish-azure` | Complete | Pass | Pass | Pass | `32df8b4` | Two workflows updated |
| `simonw/datasette-publish-fly` | Complete | Pass | Pass | Pass | `d71e253` | Two workflows updated |
| `simonw/datasette-publish-vercel` | Complete | Pass | Pass | Pass | `86b5a22` | Two workflows updated |
| `simonw/datasette-pyinstrument` | Complete | Pass | Pass | Pass | `87d1f7a` | Two workflows updated |
| `simonw/datasette-query-links` | Complete | Pass | Pass | Pass | `01b5b37` | Two workflows updated |
| `simonw/datasette-redirect-forbidden` | Complete | Pass | Pass | Pass | `05d5b7a` | Two workflows updated |
| `simonw/datasette-redirect-to-https` | Complete | Pass | Pass | Pass | `7594378` | Two workflows updated |
| `simonw/datasette-remote-metadata` | Complete | Pass | Pass | Pass | `24bcca3` | Two workflows updated |
| `simonw/datasette-render-binary` | Complete | Pass | Pass | Pass | `40b3850` | Two workflows updated |
| `simonw/datasette-render-html` | Complete | Pass | Pass | Pass | `5d90453` | Single module moved into an equivalent package directory; two workflows updated |
| `simonw/datasette-render-image-tags` | Complete | Pass | Pass | Pass | `ad09288` | Two workflows updated |
| `simonw/datasette-render-images` | Complete | Pass | Pass | Pass | `9e35c13` | Single module moved into an equivalent package directory; two workflows updated |
| `simonw/datasette-render-markdown` | Complete | Pass | Pass | Pass | `a153ab5` | Two workflows updated |
| `simonw/datasette-render-timestamps` | Complete | Pass | Pass | Pass | `659a3fc` | No matching workflow install |
| `simonw/datasette-ripgrep` | Complete | Pass | Pass | Pass | `f29c229` | Two workflows updated |
| `simonw/datasette-dns` | Complete | Pass | Pass | Pass | `311268c` | Two workflows updated |
| `simonw/datasette-edit-templates` | Complete | Pass | Pass | Pass | `6b5b7f1` | One workflow install updated; pre-existing `build/` left untracked |
| `simonw/datasette-execute-selected` | Complete | Pass | Pass | Pass | `afb93d9` | Two workflows updated |
| `simonw/datasette-export-notebook` | Complete | Pass | Pass | Pass | `f799605` | Two workflows updated |
| `simonw/datasette-expose-env` | Complete | Pass | Pass | Pass | `aba5618` | Two workflows updated |
| `simonw/datasette-faiss` | Complete | Pass | Pass | Pass | `dd41ce3` | Two workflows updated |
| `simonw/datasette-geojson` | Complete | Pass | Pass | Pass | `5e80199` | Two workflows updated |
| `simonw/datasette-geopackage` | Complete | Pass | Pass | Pass | `3c6c2b0` | Two workflows updated |
| `simonw/datasette-glitch` | Complete | Pass | Pass | Pass | `78acfad` | Two workflows updated |
| `simonw/datasette-granian` | Complete | Pass | Pass | Pass | `8674744` | Two workflows updated |
| `simonw/datasette-gunicorn` | Complete | Pass | Pass | Pass | `ac02404` | Two workflows updated |
| `simonw/datasette-hashed-urls` | Complete | Pass | Pass | Pass | `dc03ebb` | Two workflows updated |
| `simonw/datasette-hello-world` | Complete | Pass | Pass | Pass | `9e31a49` | Two workflows updated |
| `simonw/datasette-hovercards` | Complete | Pass | Pass | Pass | `14905bd` | Two workflows updated |
| `simonw/datasette-ics` | Complete | Pass | Pass | Pass | `95e3ce8` | Existing source/test edits and generated `build/` preserved; two workflows updated |
| `simonw/datasette-indieauth` | Complete | Pass | Pass | Pass | `463de2d` | Pre-existing `build/` left untracked; two workflows updated |
| `simonw/datasette-init` | Complete | Pass | Pass | Pass | `8a6a0b6` | Two workflows updated |
| `simonw/datasette-insert` | Complete | Pass | Pass | Pass | `da9b785` | Two workflows updated |
| `simonw/datasette-insert-unsafe` | Complete | Pass | Pass | Pass | `b7b004a` | Two workflows updated |
| `simonw/datasette-jellyfish` | Complete | Pass | Pass | Pass | `eb6a218` | Two workflows updated |
| `simonw/datasette-jq` | Complete | Pass | Pass | Pass | `612e4af` | CircleCI packaging references migrated; no matching GitHub workflow install |
| `simonw/datasette-json-html` | Complete | Pass | Pass | Pass | `ce9b464` | Two workflows updated |
| `simonw/datasette-json-preview` | Complete | Pass | Pass | Pass | `d9b8e53` | Two workflows updated |
| `simonw/datasette-jupyterlite` | Complete | Pass | Pass | Pass | `42a3312` | Two workflows updated |
| `simonw/datasette-leaflet-freedraw` | Complete | Pass | Pass | Pass | `f29bebb` | Two workflows updated |
| `simonw/datasette-leaflet-geojson` | Complete | Pass | Pass | Pass | `a87566f` | Two workflows updated |
| `simonw/datasette-low-disk-space-hook` | Complete | Pass | Pass | Pass | `ed2f036` | Two workflows updated |
| `simonw/datasette-mask-columns` | Complete | Pass | Pass | Pass | `f5db2fe` | Two workflows updated |

## Final audit

Completed 2026-07-27.

- Repositories migrated and committed locally: 112 of 112
- Successful `uv build --clear` runs: 112
- Wheels inspected successfully: 112, covering 198 tracked package/module/asset
  files
- Source distributions inspected successfully: 112
- Tracked test/fixture files confirmed in source distributions: 176
- Repositories with no tests to include: 1 (`datasette-sql-scraper`)
- GitHub Actions workflow files changed: 202 across 101 repositories
- Legacy `pip install ...[test]` GitHub Actions commands remaining: 0
- Build backends: 82 `uv_build`, 25 `flit_core`, 5 `setuptools`
- Repositories confirmed ahead of their configured upstream: 112
- Pushes performed: 0

`flit_core` was used for 25 projects that still declare or implicitly support
Python 3.6/3.7, because the current `uv_build` backend itself requires Python
3.8 or later. `setuptools` was retained as the backend for five single-module
projects. All builds were still executed through `uv build`.

The final sweep reparsed every `pyproject.toml`, confirmed a populated `dev`
dependency group, confirmed `setup.py` was absent, checked the local commit
subject, independently compared tracked package and asset files with wheel
contents, independently compared tracked tests and fixtures with source
distribution contents, and verified that every repository remained ahead of
its upstream.

Pre-existing unrelated working-tree changes and generated files were preserved
in `datasette-block`, `datasette-edit-templates`, `datasette-ics`,
`datasette-indieauth`, `datasette-media`, `datasette-plugin-demos`,
`datasette-sql-scraper`, `datasette-sqlite-fts4`, and `datasette-yaml`.
