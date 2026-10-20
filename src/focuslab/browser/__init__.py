"""Browser extension bridge: Chrome/Edge report the active tab's hostname over Native Messaging.

The extension in ``browser_extension/`` ships a fixed public ``key`` so that its unpacked ID is
stable. Store listings get their own IDs from each store; only these origins may launch the
native host.
"""

HOST_NAME = "com.focuslab.activity"
EXTENSION_ID = "eaiehgkiplofmpbkbiaecknfdaklglfp"  # unpacked (developer mode) install
EXTENSION_ORIGIN = f"chrome-extension://{EXTENSION_ID}/"

# Item IDs assigned by the Chrome Web Store and Edge Add-ons once the listings are published
# (see docs/browser-extension-store.md). While empty, the app guides an unpacked install.
STORE_IDS = {"chrome": "", "edge": ""}
STORE_URLS = {
    "chrome": "https://chromewebstore.google.com/detail/{id}",
    "edge": "https://microsoftedge.microsoft.com/addons/detail/{id}",
}
EXTENSION_ORIGINS = (
    EXTENSION_ORIGIN,
    *(f"chrome-extension://{i}/" for i in dict.fromkeys(STORE_IDS.values()) if i),
)

# Foreground executable -> the browser name the extension reports.
BROWSER_EXES = {"chrome.exe": "chrome", "msedge.exe": "edge"}

# A browser that has not reported for this long is "detail unknown" (heartbeat is 30 s).
STATE_TTL_MS = 75_000
