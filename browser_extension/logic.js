// Pure helpers shared by the service worker and the tests. No chrome.* access here.

export const HOST_NAME = "com.focuslab.activity";
export const PROTOCOL_VERSION = 1;
export const HEARTBEAT_MINUTES = 0.5; // the desktop app treats >75 s without news as stale

// Only the hostname of http(s) pages ever leaves the browser. Paths, queries, fragments,
// credentials and ports are dropped here; internal pages (chrome://, edge://, file://,
// extensions, new tab) report no domain at all.
export function hostnameOf(url) {
  if (typeof url !== "string" || url.length === 0) return null;
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
  let host = parsed.hostname.toLowerCase().replace(/\.$/, "");
  if (host.startsWith("www.")) host = host.slice(4);
  if (host.startsWith("[") || /^\d{1,3}(\.\d{1,3}){3}$/.test(host)) return "local-address";
  if (host === "localhost" || host.endsWith(".localhost")) return "localhost";
  return /^[a-z0-9.-]{1,253}$/.test(host) ? host : null;
}

// Titles are optional, never sent before the desktop host grants the title setting.
// Avoid capturing private/internal pages, URL-like titles or obvious account/mail pages.
export function safeTitle(title, domain) {
  if (!domain || domain === "localhost" || domain === "local-address" ||
      /(^|\.)((accounts|mail)\.google\.com|outlook\.live\.com|login\.microsoftonline\.com)$/.test(domain)) return null;
  if (typeof title !== "string") return null;
  const cleaned = title.replace(/[\x00-\x1f\x7f]/g, " ").replace(/\s+/g, " ").trim();
  if (!cleaned || /https?:\/\/|[?][a-z]+=/.test(cleaned)) return null;
  return cleaned.slice(0, 160).trim() || null;
}

export function browserName(userAgent) {
  return /\bEdg\//.test(userAgent || "") ? "edge" : "chrome";
}

// What the user is looking at in this browser right now. A private window, an unfocused
// browser or an internal page all mean "no domain".
export function stateOf(window, tab, includeTitle = false) {
  if (!window || !window.focused || window.incognito) return { focused: false, domain: null };
  if (!tab || tab.incognito) return { focused: true, domain: null };
  const domain = hostnameOf(tab.url || tab.pendingUrl || "");
  const title = includeTitle ? safeTitle(tab.title, domain) : null;
  return { focused: true, domain, ...(title ? { title } : {}) };
}

export function sameState(a, b) {
  return !!a && !!b && a.focused === b.focused && a.domain === b.domain && a.title === b.title;
}

export function stateMessage(state, { browser, instance, seq, now }) {
  return {
    v: PROTOCOL_VERSION,
    type: "state",
    browser,
    instance,
    seq,
    ts: now,
    focused: state.focused,
    domain: state.domain,
    ...(state.title ? { title: state.title } : {}),
  };
}

// Exponential reconnect delay after the native host disconnects (FocusLab not installed,
// host replaced, browser waking up): 1 s, 2 s, 4 s ... capped at 5 minutes.
export function reconnectDelay(attempt) {
  return Math.min(1000 * 2 ** Math.max(0, attempt), 5 * 60 * 1000);
}
