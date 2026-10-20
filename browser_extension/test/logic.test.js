import assert from "node:assert/strict";
import { test } from "node:test";

import {
  browserName,
  hostnameOf,
  reconnectDelay,
  sameState,
  stateMessage,
  stateOf,
} from "../logic.js";

test("only the hostname of http(s) pages is kept", () => {
  assert.equal(hostnameOf("https://github.com/DS-J-L/focuslab/pull/4?tab=files#x"), "github.com");
  assert.equal(hostnameOf("https://www.YouTube.com/watch?v=secret"), "youtube.com");
  assert.equal(hostnameOf("http://user:pass@docs.python.org:8080/3/"), "docs.python.org");
  assert.equal(hostnameOf("https://example.com./"), "example.com");
  assert.equal(hostnameOf("https://www.google.com/search?q=private+question"), "google.com");
});

test("internal, local and malformed pages report no real domain", () => {
  for (const url of ["chrome://newtab/", "edge://settings", "file:///C:/Users/me/a.pdf",
    "chrome-extension://abc/page.html", "about:blank", "", "not a url", null, undefined]) {
    assert.equal(hostnameOf(url), null, String(url));
  }
  assert.equal(hostnameOf("http://localhost:3000/admin"), "localhost");
  assert.equal(hostnameOf("http://192.168.0.12/router"), "local-address");
  assert.equal(hostnameOf("http://[::1]:8080/"), "local-address");
});

test("browser name distinguishes Edge from Chrome", () => {
  assert.equal(browserName("Mozilla/5.0 ... Chrome/130.0 Safari/537.36 Edg/130.0"), "edge");
  assert.equal(browserName("Mozilla/5.0 ... Chrome/130.0 Safari/537.36"), "chrome");
  assert.equal(browserName(undefined), "chrome");
});

test("private, unfocused and background states never carry a domain", () => {
  const tab = { url: "https://github.com/x", incognito: false };
  assert.deepEqual(stateOf({ focused: true, incognito: false }, tab),
    { focused: true, domain: "github.com" });
  assert.deepEqual(stateOf({ focused: false, incognito: false }, tab),
    { focused: false, domain: null });
  assert.deepEqual(stateOf({ focused: true, incognito: true }, tab),
    { focused: false, domain: null });
  assert.deepEqual(stateOf({ focused: true }, { ...tab, incognito: true }),
    { focused: true, domain: null });
  assert.deepEqual(stateOf(null, tab), { focused: false, domain: null });
  assert.deepEqual(stateOf({ focused: true }, { pendingUrl: "https://a.org/b" }),
    { focused: true, domain: "a.org" });
});

test("message has exactly the fields the host accepts", () => {
  const msg = stateMessage({ focused: true, domain: "github.com" },
    { browser: "chrome", instance: "i-1", seq: 3, now: 1000 });
  assert.deepEqual(Object.keys(msg).sort(),
    ["browser", "domain", "focused", "instance", "seq", "ts", "type", "v"]);
  assert.equal(JSON.stringify(msg).includes("http"), false);
});

test("state comparison and reconnect backoff", () => {
  assert.equal(sameState({ focused: true, domain: "a" }, { focused: true, domain: "a" }), true);
  assert.equal(sameState({ focused: true, domain: "a" }, { focused: false, domain: "a" }), false);
  assert.equal(sameState(null, { focused: true, domain: "a" }), false);
  assert.deepEqual([0, 1, 2, 20].map(reconnectDelay), [1000, 2000, 4000, 300000]);
});


test("titles are omitted by default and sanitized only when the user opts in", () => {
  const w = { focused: true, incognito: false };
  const tab = { url: "https://youtube.com/watch?v=secret", title: "  Augmented Reality Course\nLesson 1 ", incognito: false };
  assert.deepEqual(stateOf(w, tab), { focused: true, domain: "youtube.com" });
  const titled = stateOf(w, tab, true);
  assert.deepEqual(titled, { focused: true, domain: "youtube.com", title: "Augmented Reality Course Lesson 1" });
  const msg = stateMessage(titled, { browser: "chrome", instance: "x", seq: 1, now: 3 });
  assert.equal(msg.title, "Augmented Reality Course Lesson 1");
  assert.ok(!JSON.stringify(msg).includes("watch?v="));
  assert.equal(sameState(titled, stateOf(w, { ...tab, title: "Different lesson" }, true)), false);
  assert.equal(stateOf(w, { ...tab, url: "https://mail.google.com/mail/u/0/" }, true).title, undefined);
  assert.equal(stateOf(w, { ...tab, title: "https://example.com/private?q=secret" }, true).title, undefined);
  assert.deepEqual(stateOf({ focused: false }, tab, true), { focused: false, domain: null });
});
