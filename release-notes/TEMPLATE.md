# ValScanner v{VERSION} — Release Notes

**Release date:** {YYYY-MM-DD}
**Status:** Patch release | Minor release | First public release

---

## Overview

{One paragraph. What changed and why a user should care. Lead with the
most visible change. Avoid implementation jargon — link to a section
below for that.}

---

## User-visible changes

- {Bullet per shipped step, taken verbatim from each step's "Release
  notes (for the PyPI bullet)" section.}
- {Order: most user-visible first. "Internal" / "no user-visible change"
  bullets last.}

---

## Upgrade notes

{Skip this section if no special action is needed. Otherwise:}

- {Settings migration: explain what gets migrated, what to do if it
  doesn't, where the reset action lives. (Step 17.)}
- {Behavioral defaults that may surprise: e.g. theme default = Dark
  preserved on upgrade.}

---

## Fixes

- {Optional. Bug fixes that landed alongside the planned work.}

---

## Internal

- {Optional. Test harness additions, dependency bumps not affecting
  runtime, dev-only changes.}

---

## Known issues

- {Optional. Anything broken that a user might hit; link to the
  tracking issue.}

---

## Upgrading

```bash
pip install --upgrade valscanner
```

{If extras changed:}

```bash
pip install --upgrade "valscanner[rich]"
pip install --upgrade "valscanner[web]"
```

---

## License

MIT — see [LICENSE](../LICENSE).
