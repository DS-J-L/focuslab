# Changed-file Windows updates

The optional updater compares the installed bundle with the next release's verified
file index. Matching immutable files are reused locally; only changed files' compressed
ZIP entries are requested with HTTP byte ranges. A complete sibling folder is verified
before the existing exit/restart swap. Obsolete bundled files disappear with the old
folder. Records, settings, optional downloaded models and privacy choices stay in the
separate user data folder. Cancellation does not modify the running installation.

The UI reports actual compressed changed-file bytes, with separate comparison and
verification steps. Local hashing and staging still take time even when the network
transfer is small. This is file-level updating: changing FocusLab.exe downloads that
whole file; it does not apply binary patches within a file. Qt/AI runtime changes can
still require a large update.

## Release assets and compatibility

`python scripts/package_release.py --version <version>` creates four assets from
`dist/FocusLab` in `dist/release`:

- `FocusLab-<version>-win64.zip` and `.zip.sha256` (unchanged full-client contract)
- `FocusLab-<version>-win64.manifest.json` and its `.sha256`

The schema-1 index binds the release version, archive name/size/hash, and each file's
Windows-safe relative path, SHA256, uncompressed size, raw compressed-data offset,
compressed size and ZIP compression method. SHA256 detects corruption; authenticity
continues to depend on HTTPS and the trusted GitHub release account, as in the existing
full-ZIP updater. Index parsing rejects aliases, traversal, device/ADS names, invalid
sizes/ranges, duplicate paths, and conflicting file/directory paths. Staging rejects
symlinks/junctions; installed files reached through links are downloaded instead.

Old clients still use the normal ZIP. New clients fall back to a SHA256-verified full
ZIP if a release lacks the index or if metadata/ranges/file verification fail. A server
returning HTTP 200 for a Range request is closed before its body is read. Cancellation
never triggers fallback. Every staged file is verified again before handover.

The tagged release workflow publishes all four assets. Merging this implementation
does not publish a release or replace an installed EXE. A previously released ZIP without
an index still needs a full download. Existing old updater clients need one full client
upgrade before using changed-file transfers on later indexed releases. An explicitly
installed local build can use the new updater immediately once an indexed release exists.

## Verification

`pytest tests/unit/test_incremental_update.py tests/e2e/test_update_dialog.py` exercises
real loopback HTTP transfers, unchanged and damaged local files, hash failures, bad or
ignored ranges, truncated transfers, cancellation, fallback, paths, and UI progress.

`FocusLab.exe --selftest-update-report <absolute-report.json>` runs a synthetic loopback
transfer inside the frozen application. It uses temporary synthetic bundles, never
user data, sensors, the installed bundle or the swap helper. CI runs this in addition
to the existing packaged environment/art smoke. The JSON reports measured compressed
bytes versus a full ZIP; these are test data, not a prediction for every real release.

Windows manual check: update an idle folder build using a newer indexed release, observe
"Downloading changed files", cancel once and verify the old app remains intact, then
retry, finish and verify the restarted build. A release without an index or an HTTP
proxy that strips Range support should use "Downloading full package" instead.

When changed compressed bytes exceed 85% of the full ZIP, the client chooses the
full transfer to avoid hundreds of separate requests. OneDrive cloud placeholders
are supported; directory junctions and symbolic links are rejected for staging.
