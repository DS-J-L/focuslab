# Contributing

Read the [development plan](DEVELOPMENT_PLAN.md), [privacy principles](PRIVACY.md), and [PR merge safety policy](docs/merge-policy.md) first. The project is a developer prototype; field validation, threshold tuning, and a distributable installer remain separate work packages.

## Windows PowerShell setup

Install Python 3.11 and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```powershell
git clone https://github.com/DS-J-L/focuslab.git
cd focuslab
uv sync --locked
uv run focuslab --demo   # Explore the UI with scripted sensors
uv run ruff check .
uv run pytest
node --test "browser_extension/test/*.test.js"
uv build
```

## Development and PR workflow

1. Open a small, scoped issue/PR describing behavior, tests, privacy and performance impact.
2. **Start each work branch from updated `main`**, not a previous feature branch. Use `feat/<scope>`, `fix/<scope>` or `chore/<scope>`. If work depends on another PR, wait until that PR is verified in `main`.
3. Keep sensors separate from judgments, UI, and storage. Test the recorder with scripted probes and a fake clock rather than live OS activity (`tests/unit/test_recorder.py`).
4. **Target `main` directly** in every PR. The CI job **PR targets main** fails for feature-to-feature PRs, which previously appeared merged without reaching the default branch.
5. Finish all intended changes **before** validation. Push the branch, record the *full head SHA*, and wait for both **PR targets main** and **Windows Python 3.11** checks on that SHA. New commits invalidate the old validation; rerun the checks and freeze the new head.
6. Review, then merge using the **merge-commit** method and `expected_head_sha` / GitHub's current PR head SHA. Do not assume an already-merged PR includes later commits pushed to its branch.
7. **Do not declare completion at the merge API response.** Re-fetch `main`, verify the locked PR head is an ancestor of `main`, verify the intended files and important behavior **in `main`**, and wait for the **post-merge main CI** to pass. Put final main SHA, checked paths, and CI URL in the completion report. If verification fails, open a recovery PR.
8. Retire the merged work branch; start subsequent work from the updated `main` rather than continuing to push to a merged branch. After saving uncommitted work, `git switch main; git pull --ff-only origin main`.

See [the complete, reproducible checklist](docs/merge-policy.md). Use synthetic observations (`focuslab.mock_sources`, `focuslab --seed-demo`) as default test data. Do not commit raw camera footage, personal records, or secrets. Verify new dependencies on Windows Python 3.11 and update `uv.lock` and third-party notices together.

## Documentation and translations

All repository documentation and PR templates are maintained in English. The application supports English and Korean. New user-visible messages must use the localization helpers, with Korean entries in the catalog; do not translate database identifiers or user-entered text. See [the localization guide](docs/internationalization.md) for conventions and validation.
