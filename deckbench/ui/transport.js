/* How the page reaches a bench. Three ways, the same page:
 *   - served by the bench itself: the API is at the same address (nothing to set),
 *   - hosted elsewhere (commitcollective.cc/deckbench): the address of a bench on your network, and its token,
 *   - the demo: a bench made of JavaScript in this page, for trying it with no network. */
"use strict";

const transport = (() => {
  const store = {
    get(key) { try { return localStorage.getItem(key); } catch (e) { return null; } },
    set(key, value) { try { if (value == null) localStorage.removeItem(key); else localStorage.setItem(key, value); } catch (e) { /* works without */ } },
  };
  const query = new URLSearchParams(location.search);
  const fragment = new URLSearchParams(location.hash.slice(1));      /* #token=...&bench=... (and a tab's name, which is no pair) */

  const local = /^(localhost|127\.|\[::1\]|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(location.hostname) || location.protocol === "file:";
  const t = {
    demo: query.has("demo"),
    bench: null,                    /* the demo's bench (demo.js sets it) */
    base: "",
    token: fragment.get("token") || query.get("token") || "",
    hosted: !local || query.has("connect"),             /* ?connect shows the dialog from anywhere */
    remembered: false,
  };
  const given = query.get("bench") || fragment.get("bench");
  const remembered = store.get("deckbench.bench");
  if (!t.demo && (given || (t.hosted && remembered))) {
    t.base = normalise(given || remembered);
    t.remembered = !given;
    if (!t.token && !given) t.token = store.get("deckbench.token") || "";
  }

  function normalise(address) {
    let a = String(address || "").trim();
    if (!a) return "";
    if (!/^https?:\/\//.test(a)) a = "http://" + a;
    return a.replace(/\/+$/, "") + "/";
  }

  t.normalise = normalise;
  t.remote = () => !!t.base;
  t.url = (path) => t.base + path + (t.token && !t.demo ? (path.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(t.token) : "");
  t.fetch = (path, options) => (t.demo ? t.bench.fetch(path, options) : fetch(t.url(path), options));
  t.eventSource = (path) => (t.demo ? t.bench.eventSource(path) : new EventSource(t.url(path)));

  /* does a bench answer at this address? Resolves to {ok, message}. */
  t.probe = async (base, token) => {
    const url = base + "api/ready" + (token ? "?token=" + encodeURIComponent(token) : "");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 6000);
    try {
      const r = await fetch(url, {signal: controller.signal});
      if (r.status === 401) return {ok: false, message: "The bench wants its token."};
      if (r.status === 403) return {ok: false, message: "The bench refused this page. Start it with --allow-origin " + location.origin + "."};
      if (!r.ok) return {ok: false, message: "The bench answered " + r.status + "."};
      return {ok: true, info: await r.json()};
    } catch (e) {
      return {ok: false, message: "Nothing answered at " + base + ". Is the bench running, and can this browser reach it? " +
        (location.protocol === "https:" && base.startsWith("http:") ? "A secure page may refuse to call a plain http address that is not on your own network: use the address of the machine (192.168...) or open the page from the bench." : "")};
    }
  };

  /* Keep (or forget) the bench this browser uses. */
  t.remember = (base, token) => { store.set("deckbench.bench", base || null); store.set("deckbench.token", token || null); };
  t.forget = () => t.remember(null, null);
  return t;
})();
