// Keeps the crypto pages live (Krypto and pump.fun). Every 15 seconds while the tab is visible it asks the page's
// data-version-url whether the data has changed; if it has, it fetches the page again and swaps every part marked
// data-live. Open tables stay open, the chosen tab and "Vis alle" stay chosen, new cards slide in, changed numbers
// flash, and the ticker tape takes its new items when it comes round, so it never jumps.
(() => {
  const page = document.querySelector("[data-live-page]");
  if (!page) return;
  const POLL_MS = 15000;
  const VERSION_URL = page.dataset.versionUrl || "/pumpfun/version";
  const LIVE_FOR_S = Number(page.dataset.liveFor) || 600;  // the newest data must be younger than this to be "Live"
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const state = { version: page.dataset.version, busy: false, stopped: false, offline: false, showAll: false,
                  population: "all", tape: null };

  // Status pill: "Live · oppdatert for 12 s siden", counted every second.
  const ago = (s) => {
    if (s < 5) return "akkurat nå";
    if (s < 60) return `for ${Math.floor(s)} s siden`;
    if (s < 3600) return `for ${Math.floor(s / 60)} min siden`;
    if (s < 86400) return `for ${Math.floor(s / 3600)} t siden`;
    const days = Math.floor(s / 86400);
    return `for ${days} ${days === 1 ? "dag" : "dager"} siden`;
  };
  const tickStatus = (message) => {
    const el = document.getElementById("pf-status");
    if (!el) return;
    const updated = Date.parse(el.dataset.updated || "");
    const seconds = Number.isNaN(updated) ? Infinity : Math.max(0, (Date.now() - updated) / 1000);
    const live = !state.stopped && !state.offline && seconds < LIVE_FOR_S;
    el.classList.toggle("is-live", live);
    el.classList.toggle("is-stale", !live);
    el.querySelector(".state").textContent = message || (state.stopped ? state.stopped
      : state.offline ? "Frakoblet, prøver igjen" : live ? "Live" : "Ikke live");
    if (Number.isFinite(seconds)) el.querySelector(".age").textContent = `· oppdatert ${ago(seconds)}`;
  };
  const stop = (message) => {
    state.stopped = message;
    tickStatus();
  };

  async function poll() {
    if (state.busy || state.stopped || document.hidden) return;
    state.busy = true;
    try {
      const r = await fetch(VERSION_URL, { cache: "no-store", headers: { Accept: "application/json" } });
      if (r.redirected || !(r.headers.get("content-type") || "").includes("json")) {
        stop("Logget ut: last inn siden på nytt");
        return;
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const { v } = await r.json();
      if (v !== state.version) await refresh();
      state.offline = false;
    } catch (error) {
      state.offline = true;
    } finally {
      state.busy = false;
      tickStatus();
    }
  }

  async function refresh() {
    const r = await fetch(location.href, { cache: "no-store" });
    if (r.redirected && new URL(r.url).pathname === "/login") {
      stop("Logget ut: last inn siden på nytt");
      return;
    }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const doc = new DOMParser().parseFromString(await r.text(), "text/html");
    const fresh = doc.querySelector("[data-live-page]");
    if (!fresh) return;
    const before = remember();
    doc.querySelectorAll("[data-live]").forEach((incoming) => {
      const current = document.getElementById(incoming.id);
      if (!current) return;
      if (incoming.id === "pf-tape") queueTape(current, incoming);
      else current.replaceWith(incoming);
    });
    state.version = fresh.dataset.version;
    window.pfCharts?.init(document);
    restore(before);
  }

  // What the swap must not lose, and what it should animate.
  const accountChart = () => document.querySelector("#pf-account .chart");
  const remember = () => ({
    scroll: (({ scrollLeft, scrollWidth, clientWidth } = accountChart() || {}) => ({
      left: scrollLeft, atEnd: scrollLeft === undefined || scrollLeft + clientWidth >= scrollWidth - 2 }))(),
    ticks: new Map([...document.querySelectorAll("[data-tick]")].map((el) => [el.dataset.tick, Number(el.dataset.value)])),
    mints: new Set([...document.querySelectorAll(".pos[data-mint]")].map((el) => el.dataset.mint)),
    open: new Set([...document.querySelectorAll("details[data-key][open]")].map((el) => el.dataset.key)),
  });
  const restore = ({ scroll, ticks, mints, open }) => {
    document.querySelectorAll("details[data-key]").forEach((el) => { if (open.has(el.dataset.key)) el.open = true; });
    if (!scroll.atEnd && accountChart()) accountChart().scrollLeft = scroll.left;  // looking back: stay there
    applyShowAll();
    applyPopulation();
    if (reduced.matches) return;
    document.querySelectorAll("[data-tick]").forEach((el) => {
      const was = ticks.get(el.dataset.tick);
      const now = Number(el.dataset.value);
      if (was === undefined || Number.isNaN(was) || Number.isNaN(now) || was === now) return;
      el.classList.add(now > was ? "tick-up" : "tick-down");
      setTimeout(() => el.classList.remove("tick-up", "tick-down"), 1600);
    });
    document.querySelectorAll(".pos[data-mint]").forEach((el) => {
      if (!mints.has(el.dataset.mint)) el.classList.add("fresh");
    });
  };

  // The tape restarts its scroll when replaced, so wait until it comes round to its start.
  const queueTape = (current, incoming) => {
    const track = current.querySelector(".tape-track");
    const moving = track && !current.hidden && !reduced.matches && getComputedStyle(track).animationName !== "none";
    if (!moving) {
      current.replaceWith(incoming);
      return;
    }
    const waiting = state.tape !== null;
    state.tape = incoming;
    if (waiting) return;
    track.addEventListener("animationiteration", () => {
      document.getElementById("pf-tape")?.replaceWith(state.tape);
      state.tape = null;
    }, { once: true });
  };

  const applyShowAll = () => {
    document.querySelector(".pos-grid")?.classList.toggle("all", state.showAll);
    const button = document.querySelector("[data-show-all]");
    if (!button) return;
    button.setAttribute("aria-expanded", String(state.showAll));
    button.textContent = state.showAll ? "Vis færre" : `Vis alle ${button.dataset.count}`;
  };
  const applyPopulation = () => {
    document.querySelectorAll("#pf-patterns button[data-population]").forEach((b) => {
      const on = b.dataset.population === state.population;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", String(on));
    });
    document.querySelectorAll("#pf-patterns .pattern[data-population]").forEach((el) => {
      el.hidden = el.dataset.population !== state.population;
    });
  };

  document.addEventListener("click", (event) => {
    const showAll = event.target.closest("[data-show-all]");
    if (showAll) {
      state.showAll = !state.showAll;
      applyShowAll();
      return;
    }
    const population = event.target.closest("#pf-patterns button[data-population]");
    if (population) {
      state.population = population.dataset.population;
      applyPopulation();
      return;
    }
    const periode = event.target.closest("a[data-periode]");
    if (periode && !event.metaKey && !event.ctrlKey && !event.shiftKey) {
      event.preventDefault();
      const url = new URL(location.href);
      url.searchParams.set("periode", periode.dataset.periode);
      history.replaceState(null, "", url);
      document.querySelectorAll("a[data-periode]").forEach((a) => a.classList.toggle("on", a === periode));
      refresh().catch(() => { location.href = url; });
    }
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
  document.addEventListener("animationend", (event) => {
    if (event.animationName === "pos-in") event.target.classList.remove("fresh");
  });

  tickStatus();
  setInterval(tickStatus, 1000);
  setInterval(poll, POLL_MS);
})();
