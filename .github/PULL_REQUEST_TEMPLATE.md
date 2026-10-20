## Problem and expected behavior

## Changes and expected files

<!-- Name key source files/features that MUST appear in main after merge. -->

## Before merge (required)

- [ ] **Base branch is main** (not another feature branch).
- [ ] Branch was created or rebased from the latest main; no unrelated changes.
- [ ] All intended changes are committed and pushed; no further work will be added to this PR after merge.
- [ ] Final PR head SHA (40 characters): `<paste SHA>`
- [ ] Latest PR-head CI: **PR targets main** and **Windows Python 3.11** passed for this exact SHA.
- [ ] `uv run ruff check .`
- [ ] `uv run pytest`
- [ ] `uv build`
- [ ] Real Windows hardware check, if applicable (or explicit reason not run).
- [ ] English and Korean UI verified, if user-visible text changed.
- [ ] Review complete; merge with **expected head SHA** (reject a moving PR).

## Delivery / visible behavior (required)

- [ ] This PR delivers to **source checkout**; key files/feature paths are listed above.
- [ ] New/changed user-facing behavior is covered by automated tests; remaining Windows manual tests are stated.
- [ ] Packaged EXE impact: **none / rebuild required / new versioned release requested separately**.
- [ ] Browser extension impact: **none / extension source changed; user reload required**.
- [ ] Consent / migration / i18n impact and opt-in procedure, if applicable.
- [ ] User instructions distinguish `git pull` from updating a downloaded `FocusLab.exe`.
- [ ] A GitHub Release will **not** be created as part of this PR unless explicitly requested.

## Privacy and performance impact

## Known limitations

## Follow-up work

## After merge (must be reported; do not pre-check)

<!-- After merge, also report whether the new feature is in a published EXE
     release and/or an extension currently installed in the browser. Do not
     present source merge as installed-app update. -->

<!-- In the merge completion report, record: final main SHA, merge SHA,
     evidence that the locked PR head is reachable from main, expected
     file/content checks in main, and successful push-to-main CI URL.
     If any check fails, report INCOMPLETE and open a fix PR. -->
