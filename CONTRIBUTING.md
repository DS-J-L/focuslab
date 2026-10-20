# Contributing

Read the [development plan](DEVELOPMENT_PLAN.md) and [privacy principles](PRIVACY.md) first. The project is a developer prototype; field validation, threshold tuning, and a distributable installer remain separate work packages.

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

## Workflow

1. Describe scope and privacy impact in an issue.
2. Implement one purpose on a `feat/<scope>` or `fix/<scope>` branch.
3. Sensors publish observations only. Keep them separate from judgments, UI, and storage. Test the recorder with scripted probes and a fake clock rather than live OS activity (`tests/unit/test_recorder.py`).
4. Record lint, test, and applicable real-Windows validation results in the PR.
5. Confirm the PR base is `main` for final integration, then merge after validation and review. When using stacked branches, merging into a parent feature branch alone does not integrate the changes into `main`.
6. After a remote merge, update your local `main` with `git pull --ff-only` after saving ongoing work.

Use synthetic observations (`focuslab.mock_sources`, `focuslab --seed-demo`) as default test data. Do not commit raw camera footage, personal records, or secrets. Verify new dependencies on Windows Python 3.11 and update `uv.lock` and third-party notices together.

## Documentation and translations

All repository documentation and PR templates are maintained in English. The application supports English and Korean. New user-visible messages must use the localization helpers, with Korean entries in the catalog; do not translate database identifiers or user-entered text. See [the localization guide](docs/internationalization.md) for conventions and validation.
