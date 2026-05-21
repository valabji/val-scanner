# Pre-publish checklist

Run through this top-to-bottom before `twine upload`. Tick each item in the PR description for the version bump.

## Code

- [ ] On master, working tree clean: `git status` is empty.
- [ ] Master is up to date with origin: `git pull --ff-only`.
- [ ] `pytest tests/` — green. No new skips compared to the previous release.
- [ ] `pytest tests/gui/` — green (after step 16 lands).
- [ ] `pyright valscanner/` — no new errors.
- [ ] `python -m valscanner.gui.window --db <fixture>.db` launches and the most-changed panel renders without console warnings.

## Version

- [ ] `python scripts/bump_version.py X.Y.Z` ran cleanly.
- [ ] `git diff` after bump touches only the files `scripts/bump_version.py` is meant to touch (pyproject, spec, Inno setup, etc.).
- [ ] No stray edits in the bump commit.

## Notes

- [ ] `release-notes/vX.Y.Z.md` exists and was hand-authored from `release-notes/TEMPLATE.md`.
- [ ] Every merged step since the last release has its bullet present.
- [ ] Upgrade notes section mentions anything migration-related (especially after step 17 / 10).
- [ ] Date in the file matches today.

## Migration safety (only if persistence-touching steps landed)

- [ ] On a workstation with prior ValScanner state, the new build launches and migrates QSettings without losing window geometry, recent DBs, or saved view filters. (Manual; see step 17 verify.)
- [ ] `Keys.SCHEMA_VERSION` matches the constant in the source.

## Build + publish

- [ ] `python -m build` produces a wheel and sdist with no warnings.
- [ ] `twine check dist/*` passes.
- [ ] (If first time on a new machine) `twine upload --repository testpypi dist/*` and a fresh-venv `pip install` smoke-tests the wheel.
- [ ] `twine upload dist/*` to PyPI.
- [ ] Git tag pushed: `git tag vX.Y.Z && git push origin vX.Y.Z`.
- [ ] PyInstaller installers (if part of this release) built via `scripts/build_app.sh` / `.ps1` and attached to the GitHub Releases page.

## Post-publish

- [ ] `pip install --upgrade valscanner` in a fresh venv pulls the new version.
- [ ] Smoke-test the upgraded install: `valscanner --help`, `valscanner-gui --db /tmp/x.db` (then quit).
- [ ] Announce (if applicable).
