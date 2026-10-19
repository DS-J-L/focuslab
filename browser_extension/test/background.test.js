import assert from "node:assert/strict";
import { test } from "node:test";

// A tiny fake of the chrome.* APIs the worker uses.
function event() {
  const listeners = [];
  return {
    addListener: (fn) => listeners.push(fn),
    fire: (...args) => listeners.forEach((fn) => fn(...args)),
  };
}

function fakeChrome() {
  const sent = [];
  const world = { window: { id: 1, focused: true, incognito: false },
    tab: { url: "https://github.com/a/b", incognito: false }, hostMissing: false };
  const ports = [];
  const chrome = {
    runtime: {
      lastError: undefined,
      onStartup: event(),
      onInstalled: event(),
      connectNative: (name) => {
        assert.equal(name, "com.focuslab.activity");
        const port = { onDisconnect: event(), onMessage: event(),
          postMessage: (m) => sent.push(m) };
        ports.push(port);
        if (world.hostMissing) queueMicrotask(() => port.onDisconnect.fire());
        return port;
      },
    },
    windows: { onFocusChanged: event(), onRemoved: event(),
      getLastFocused: async () => world.window },
    tabs: { onActivated: event(), onUpdated: event(), onRemoved: event(),
      query: async () => [world.tab] },
    alarms: { onAlarm: event(), created: [], create(name, info) { this.created.push([name, info]); } },
  };
  return { chrome, sent, world, ports };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 10));

test("reports the focused tab's hostname, dedupes, and hides private or unfocused windows",
  async () => {
    const fake = fakeChrome();
    globalThis.chrome = fake.chrome;
    await import(`../background.js?case=${Math.random()}`);
    await settle();
    assert.equal(fake.sent.length, 1);
    assert.equal(fake.sent[0].domain, "github.com");
    assert.equal(fake.sent[0].seq, 1);
    assert.deepEqual(fake.chrome.alarms.created, [["focuslab-heartbeat", { periodInMinutes: 0.5 }]]);

    fake.chrome.tabs.onActivated.fire({}); // same tab again: nothing new to say
    await settle();
    assert.equal(fake.sent.length, 1);

    fake.world.tab = { url: "https://www.youtube.com/watch?v=private", incognito: false };
    fake.chrome.tabs.onUpdated.fire(7, { url: "x" }, { active: true });
    await settle();
    assert.equal(fake.sent.at(-1).domain, "youtube.com");

    fake.chrome.tabs.onUpdated.fire(8, { url: "x" }, { active: false }); // background tab
    await settle();
    assert.equal(fake.sent.length, 2);

    fake.world.window = { id: 2, focused: true, incognito: true };
    fake.chrome.windows.onFocusChanged.fire(2);
    await settle();
    assert.deepEqual([fake.sent.at(-1).focused, fake.sent.at(-1).domain], [false, null]);

    fake.chrome.alarms.onAlarm.fire({ name: "focuslab-heartbeat" }); // heartbeat always sends
    await settle();
    assert.equal(fake.sent.length, 4);
    assert.deepEqual(fake.sent.map((m) => m.seq), [1, 2, 3, 4]);
    assert.ok(fake.sent.every((m) => !JSON.stringify(m).includes("watch")));
  });

test("a missing host is retried with backoff instead of throwing", async () => {
  const fake = fakeChrome();
  fake.world.hostMissing = true;
  globalThis.chrome = fake.chrome;
  const timers = [];
  const realSetTimeout = globalThis.setTimeout;
  globalThis.setTimeout = (fn, ms) => timers.push([fn, ms]); // run reconnects by hand
  try {
    await import(`../background.js?case=${Math.random()}`);
    for (let i = 0; i < 5; i++) await Promise.resolve();
    await new Promise((resolve) => realSetTimeout(resolve, 10));
    assert.equal(fake.ports.length, 1);
    assert.deepEqual(timers.map(([, ms]) => ms), [1000]);
    timers.shift()[0]();
    await new Promise((resolve) => realSetTimeout(resolve, 10));
    assert.equal(fake.ports.length, 2);
    assert.deepEqual(timers.map(([, ms]) => ms), [2000]); // backing off
    fake.world.hostMissing = false; // FocusLab installed: the next retry stays connected
    timers.shift()[0]();
    await new Promise((resolve) => realSetTimeout(resolve, 10));
    assert.equal(fake.ports.length, 3);
    assert.equal(timers.length, 0);
    assert.equal(fake.sent.at(-1).domain, "github.com");
  } finally {
    globalThis.setTimeout = realSetTimeout;
  }
});
