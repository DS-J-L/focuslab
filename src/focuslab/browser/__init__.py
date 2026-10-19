"""Browser extension bridge: Chrome/Edge report the active tab's hostname over Native Messaging.

The extension in ``browser_extension/`` ships a fixed public ``key`` so that its unpacked ID is
stable; only that origin may launch the native host.
"""

HOST_NAME = "com.focuslab.activity"
EXTENSION_ID = "eaiehgkiplofmpbkbiaecknfdaklglfp"
EXTENSION_ORIGIN = f"chrome-extension://{EXTENSION_ID}/"

# Foreground executable -> the browser name the extension reports.
BROWSER_EXES = {"chrome.exe": "chrome", "msedge.exe": "edge"}

# A browser that has not reported for this long is "detail unknown" (heartbeat is 30 s).
STATE_TTL_MS = 75_000
