// FocusLab Activity Bridge service worker.
//
// Reports which site is in the active tab of the focused browser window, as a hostname only,
// to the FocusLab desktop app through Chrome Native Messaging. Background tabs, unfocused
// windows and private windows are never reported. Nothing is stored in the browser.

import {
  HEARTBEAT_MINUTES,
  HOST_NAME,
  browserName,
  reconnectDelay,
  sameState,
  stateMessage,
  stateOf,
} from "./logic.js";

const BROWSER = browserName(globalThis.navigator?.userAgent);
const INSTANCE = crypto.randomUUID(); // a new worker restarts the sequence safely
let port = null;
let seq = 0;
let last = null;
let attempts = 0;
let reconnectTimer = null;

function connect() {
  if (port) return port;
  try {
    port = chrome.runtime.connectNative(HOST_NAME);
  } catch {
    port = null;
    scheduleReconnect();
    return null;
  }
  port.onDisconnect.addListener(() => {
    void chrome.runtime.lastError; // read it so Chrome does not log it as unchecked
    port = null;
    last = null; // resend the current state after reconnecting
    scheduleReconnect();
  });
  port.onMessage.addListener((message) => {
    if (message && message.type === "ack") attempts = 0;
  });
  return port;
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  const delay = reconnectDelay(attempts++);
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    void report("reconnect");
  }, delay);
}

async function currentState() {
  let window = null;
  try {
    window = await chrome.windows.getLastFocused({ populate: false });
  } catch {
    return { focused: false, domain: null };
  }
  if (!window || !window.focused || window.incognito) return stateOf(window, null);
  const [tab] = await chrome.tabs.query({ active: true, windowId: window.id });
  return stateOf(window, tab);
}

export async function report(reason) {
  const state = await currentState();
  if (reason !== "heartbeat" && reason !== "reconnect" && sameState(state, last)) return;
  const target = connect();
  if (!target) return;
  last = state;
  try {
    target.postMessage(
      stateMessage(state, { browser: BROWSER, instance: INSTANCE, seq: ++seq, now: Date.now() }),
    );
  } catch {
    port = null;
    scheduleReconnect();
  }
}

chrome.tabs.onActivated.addListener(() => void report("tab"));
chrome.tabs.onUpdated.addListener((tabId, change, tab) => {
  if (tab.active && (change.url || change.status === "complete")) void report("navigate");
});
chrome.tabs.onRemoved.addListener(() => void report("tab-closed"));
chrome.windows.onFocusChanged.addListener(() => void report("focus"));
chrome.windows.onRemoved.addListener(() => void report("window-closed"));
chrome.alarms.create("focuslab-heartbeat", { periodInMinutes: HEARTBEAT_MINUTES });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "focuslab-heartbeat") void report("heartbeat");
});
chrome.runtime.onStartup.addListener(() => void report("startup"));
chrome.runtime.onInstalled.addListener(() => void report("installed"));
void report("worker-start");
