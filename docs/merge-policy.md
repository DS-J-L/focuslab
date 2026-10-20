# Pull request and merge integrity policy

## Why this exists

In this repository, PRs #5 and #6 targeted feature branches rather than `main`. GitHub marked them “Merged” even while their code was missing from `main`. Separately, the localization/docs commit on the source branch after PR #14's selected head was not covered by the earlier merge. These required repair PRs #8 and #15.

**A green PR or “Merged” badge is not proof the intended code is in main.** The source of truth is the default branch's content, its commit ancestry, and its successful push CI.

## One-way integration only

- Every new PR targets **main**. No stacked/intermediate PRs targeting a feature branch. Dependent work waits for the earlier PR to reach main.
- Branches are created from the latest `origin/main`. Avoid long-lived feature branches.
- Only merge after all intended changes are committed, pushed and reviewed. Record the exact PR head SHA and expected changed paths.
- The CI policy job fails PRs not targeting main. The Windows CI checks the synthetic merge of the declared PR head with its base.
- Prefer a **merge commit** (rather than squash/rebase) so the exact approved head stays reachable for auditing.
- Merge using the exact expected head SHA. Reject if the branch moves; rerun CI on the new SHA.
- A merged branch is retired; any later edits require a *new branch from main* and a new PR.

## Merge acceptance and post-merge audit

For each PR:

1. Verify GitHub PR metadata: base is `main`, head matches the locked SHA, no merge conflicts.
2. Verify **PR targets main** and **Windows Python 3.11** completed successfully for that head; check the Node extension suite if relevant and real Windows hardware testing when possible.
3. Note the **pre-merge main SHA**, merge with the locked PR head, and record the returned **merge SHA**.
4. Fetch `main` from GitHub again. Confirm its head is the expected merge SHA, that the PR head is an ancestor of `main`, and that *specific expected files and code* are present in `main`. A green PR alone is insufficient.
5. Wait for a successful **push-to-main** CI run associated with the verified main SHA.
6. Report the PR URL, locked PR head, merge SHA, verified paths, CI URL and any untested hardware behavior. Only then call the PR **completed**.

### Local audit commands

From a clean clone, or after preserving any local edits:

```powershell
git fetch origin
git switch main
git pull --ff-only origin main
git rev-parse HEAD   # Must equal the GitHub main SHA / expected merge SHA

# Paste the locked 40-character head SHA of the merged PR:
git merge-base --is-ancestor <LOCKED_PR_HEAD_SHA> origin/main
if ($LASTEXITCODE -ne 0) { throw "PR head is not integrated in main" }

# Inspect the actual main files, not the stale feature branch:
git show origin/main:README.md
git diff --name-status <PRE_MERGE_MAIN_SHA> origin/main
```

The ancestry check above assumes the required **merge-commit method**. If someone intentionally chooses squash/rebase, they must instead verify the exact applied patch and file content, not falsely report ancestry success.

### How to recover missing commits

- Do not force-push main or treat a closed PR as containing new commits.
- Compare the branch's current HEAD to the SHA that the merged PR recorded. If they differ, inspect the extra commits.
- Create a fresh branch from current main and port only missing commits; open a new PR **targeting main**.
- After merge, perform the full audit above.

## Repository settings needed

The workflow adds automatic checks but **does not itself block a repository administrator from bypassing or disabling checks**. The owner should verify GitHub **Settings → Rules → Rulesets** (or branch protection) for `main`:

- Require a pull request before merging; no direct pushes.
- Require the **PR targets main** and **Windows Python 3.11** status checks before merge.
- Require up-to-date branches / strict checks, and block force pushes and branch deletion.
- Apply rules to administrators/bypass actors where practical.
- Optional: require at least one approval and dismiss stale approvals on new commits.

These administration-level settings require repository-owner UI/API privileges and are not claimed to have been configured by this documentation change.

## Scope and limitations

The CI policy automatically blocks **non-main PR targets** when its status check is required by branch protection. The **exact merged head** and **file-level main verification** depend on the merge operator's procedure; the workflow cannot retroactively attach commits pushed after a PR has merged. Automated CI tests cannot substitute for a Windows physical-device test.
