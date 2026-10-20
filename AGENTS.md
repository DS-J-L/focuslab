# FocusLab agent instructions

These instructions apply to every coding agent working in this repository.

## PR safety: mandatory

The default integration branch is **main**. Historical mistakes: PR #5 and #6 targeted other feature branches and appeared merged but did not reach main; later commits on a branch after PR #14 merged were not part of PR #14.

1. Before changing files, fetch the current origin/main HEAD and start an isolated work branch **from main**. Never base a new feature PR on another feature branch.
2. Each PR **must** target main. Never change the PR base to another development branch to work around conflicts or speed up integration.
3. Before PR creation, commit and push every file intended for that PR. Record the branch HEAD SHA, PR head SHA, and target base. These must agree; identify the exact key files and behavior expected in main.
4. If any commit is added, the PR head changes, or the base changes, discard earlier test/approval evidence and rerun validation on the new SHA. **No edits to a branch after its PR has been merged**; create a fresh PR from main.
5. Do not merge until the PR's checks are successful for the **locked head SHA**. Use merge-commit method with `expected_head_sha` (or GitHub equivalent) to prevent a stale-head merge; stop on mismatch. Never bypass failing checks.
6. After GitHub reports a merge, fetch main again and prove that:
   - main is at the new merge SHA;
   - the locked PR head is an ancestor of main (merge-commit method);
   - expected changed files and representative implementation are actually present **in main**, not just the work branch;
   - GitHub Actions' **main push** CI for the final main SHA succeeds.
7. Report exact PR URL, locked PR head SHA, main merge SHA, checks, and any limitations. If any post-merge check fails, **say the task is incomplete** and open a recovery PR. Do not state “merged successfully” solely based on PR status.
8. Execute PRs sequentially: one feature/change → tests → CI → merge → post-merge audit → next branch. Stop if another agent or concurrent merge moved main unexpectedly.

Never force-push or rewrite main history. Do not use `update_ref(force=true)` to make PRs seem merged. Respect consent, local-only privacy defaults, and source/license requirements.

Full process and commands: [docs/merge-policy.md](docs/merge-policy.md).
