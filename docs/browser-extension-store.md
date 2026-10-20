# Publishing the browser extension

Windows Chrome and Edge install extensions with one click only from their stores. Until the
FocusLab extension is listed, Settings > **Install in Chrome** guides an unpacked install.
After the listing is published, the same button opens the store page.

## 1. Build the upload package

```powershell
uv run python scripts/package_extension.py
```

This creates `dist\focuslab-extension-<version>.zip`. The script removes the manifest `key`
because both stores assign their own item ID and reject a `key` field. Raise `version` in
`browser_extension/manifest.json` before each new upload.

## 2. Chrome Web Store

1. Register in the [Chrome Web Store Developer Dashboard](https://chrome.google.com/webstore/devconsole). Registration costs a one-time USD 5 fee.
2. Choose **New item** and upload the zip.
3. Fill in the listing:
   - **Single purpose**: tell the FocusLab desktop app on this PC which website is in the active tab, so it can show time per site.
   - **Permission justifications**:
     - `tabs`: read the active tab's URL and keep only its hostname.
     - `nativeMessaging`: send that hostname to the local FocusLab app.
     - `alarms`: send a 30-second heartbeat so the app knows the browser is still active.
   - **Data usage**: the extension handles web browsing activity (the hostname only). The hostname goes only to the FocusLab app on the same PC and is never sent to a server. It is not sold or used for advertising.
   - **Privacy policy**: give a public URL for `PRIVACY.md`, such as the file on GitHub.
   - **Images**: provide the 128 px icon (`browser_extension/icons/icon128.png`), at least one 1280×800 screenshot, and a 440×280 promotional tile.
4. Submit the item for review.

## 3. Microsoft Edge Add-ons

1. Register in [Partner Center](https://partner.microsoft.com/dashboard/microsoftedge/overview). Registration is free.
2. Upload the same zip and reuse the listing text and privacy policy URL.
3. Submit the item for review.

## 4. Connect the published items to the app

After each item is approved, copy its item ID from the store page URL into
`STORE_IDS` in `src/focuslab/browser/__init__.py`:

```python
STORE_IDS = {"chrome": "<Chrome Web Store item ID>", "edge": "<Edge Add-ons item ID>"}
```

Then rebuild `FocusLab.exe`. The install buttons now open the store page. Each button press
also rewrites the native host manifest, so its `allowed_origins` lists both the developer-mode ID
and the store IDs. Keep the `key` in the repository manifest so developer-mode installs keep
their fixed ID.
