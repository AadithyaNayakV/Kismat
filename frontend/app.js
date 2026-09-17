// Job Radar — loads jobs.json and does all filtering client-side. No build step, no deps.
(() => {
  "use strict";

  const PAGE_SIZE = 60;
  const JOB_TYPES = ["tech", "non-tech", "internship", "remote"];
  const DEFAULTS = { q: "", window: "48", skills: [], types: [], loc: "", source: "", sort: "newest", expired: false };

  const $ = (id) => document.getElementById(id);
  const el = {
    updated: $("updated"), badge: $("count-badge"), q: $("q"), location: $("location"),
    source: $("source"), sort: $("sort"), expired: $("expired"), skillChips: $("skill-chips"),
    typeChips: $("type-chips"), grid: $("grid"), empty: $("empty"), sentinel: $("sentinel"),
    resultLine: $("result-line"), healthBody: $("health-body"), filters: $("filters"),
    filtersToggle: $("filters-toggle"), filtersCount: $("filters-count"),
    template: $("card-template"),
  };

  let data = null;       // parsed jobs.json
  let jobs = [];         // enriched job list
  let results = [];      // current filtered + sorted list
  let rendered = 0;
  const state = loadState();

  // ---------- helpers ----------

  const fmtNum = (n) => n.toLocaleString("en-IN");
  const norm = (s) => (s || "").toLowerCase();

  function relTime(ms) {
    if (!ms) return "";
    const diff = Date.now() - ms;
    const min = Math.round(diff / 60000);
    if (min < 1) return "just now";
    if (min < 60) return `${min} min ago`;
    const h = Math.round(min / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.round(h / 24);
    if (d < 30) return `${d}d ago`;
    const mo = Math.round(d / 30);
    return mo < 12 ? `${mo}mo ago` : `${Math.round(mo / 12)}y ago`;
  }

  function fmtDate(iso) {
    const d = new Date(iso + (iso.length === 10 ? "T00:00:00Z" : ""));
    return isNaN(d) ? iso : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  }

  function safeUrl(url) {
    try {
      const u = new URL(url);
      return u.protocol === "https:" || u.protocol === "http:" ? u.href : "#";
    } catch { return "#"; }
  }

  function debounce(fn, ms) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  }

  // ---------- state <-> URL ----------

  function loadState() {
    const p = new URLSearchParams(location.search);
    const list = (k) => (p.get(k) || "").split(",").filter(Boolean);
    return {
      q: p.get("q") || DEFAULTS.q,
      window: ["24", "48", "all"].includes(p.get("window")) ? p.get("window") : DEFAULTS.window,
      skills: list("skills"),
      types: list("types").filter((t) => JOB_TYPES.includes(t)),
      loc: p.get("loc") || "",
      source: p.get("source") || "",
      sort: p.get("sort") === "deadline" ? "deadline" : "newest",
      expired: p.get("expired") === "1",
    };
  }

  function saveState() {
    const p = new URLSearchParams();
    if (state.q) p.set("q", state.q);
    if (state.window !== DEFAULTS.window) p.set("window", state.window);
    if (state.skills.length) p.set("skills", state.skills.join(","));
    if (state.types.length) p.set("types", state.types.join(","));
    if (state.loc) p.set("loc", state.loc);
    if (state.source) p.set("source", state.source);
    if (state.sort !== "newest") p.set("sort", state.sort);
    if (state.expired) p.set("expired", "1");
    const qs = p.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }

  // ---------- data ----------

  async function load() {
    renderSkeletons();
    try {
      const res = await fetch(`jobs.json?v=${Math.floor(Date.now() / 600000)}`, { cache: "no-cache" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
    } catch (err) {
      el.grid.innerHTML = "";
      el.updated.textContent = "Could not load jobs.json";
      el.resultLine.textContent = `Error loading data: ${err.message}. If you opened index.html directly from disk, serve the folder instead (e.g. "python -m http.server" inside frontend/).`;
      return;
    }
    jobs = (data.jobs || []).map((j) => {
      const postedMs = Date.parse(j.posted || "") || Date.parse((j.first_seen || "") + "T00:00:00Z") || 0;
      return {
        ...j,
        job_type: j.job_type || [],
        skills: j.skills || [],
        _posted: postedMs,
        _deadline: j.deadline ? Date.parse(j.deadline + "T23:59:59Z") : Infinity,
        _hay: norm(`${j.title} ${j.company}`),
        _loc: norm(j.location),
      };
    });
    buildControls();
    renderHealth();
    const gen = Date.parse(data.generated_at);
    el.updated.textContent = gen ? `Updated ${relTime(gen)} · refreshes every 2 hours` : "";
    el.updated.title = data.generated_at || "";
    apply();
  }

  // ---------- controls ----------

  function chip(label, value, pressed, count, onToggle) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.dataset.value = value;
    b.setAttribute("aria-pressed", String(pressed));
    b.textContent = label;
    if (count !== undefined) {
      const n = document.createElement("span");
      n.className = "n";
      n.textContent = fmtNum(count);
      b.append(n);
    }
    b.addEventListener("click", () => {
      const now = b.getAttribute("aria-pressed") !== "true";
      b.setAttribute("aria-pressed", String(now));
      onToggle(value, now);
    });
    return b;
  }

  function toggleIn(list, value, on) {
    const i = list.indexOf(value);
    if (on && i < 0) list.push(value);
    if (!on && i >= 0) list.splice(i, 1);
  }

  function buildControls() {
    const active = jobs.filter((j) => j.status === "active");
    const count = (pred) => active.reduce((n, j) => n + (pred(j) ? 1 : 0), 0);

    // Skills: my skills first, then any other tag present.
    const skills = [...new Set([...(data.my_skills || []), ...(data.all_skills || [])])];
    el.skillChips.replaceChildren(...skills.map((s) =>
      chip(s, s, state.skills.includes(s), count((j) => j.skills.includes(s)),
        (v, on) => { toggleIn(state.skills, v, on); apply(); })));
    if (!skills.length) {
      const hint = document.createElement("span");
      hint.className = "updated";
      hint.textContent = "Add skills to MY_SKILLS in backend/filters/skills_config.py";
      el.skillChips.append(hint);
    }

    el.typeChips.replaceChildren(...JOB_TYPES.map((t) =>
      chip(t, t, state.types.includes(t), count((j) => j.job_type.includes(t)),
        (v, on) => { toggleIn(state.types, v, on); apply(); })));

    const sources = new Map();
    active.forEach((j) => sources.set(j.source, (sources.get(j.source) || 0) + 1));
    [...sources.entries()].sort((a, b) => a[0].localeCompare(b[0])).forEach(([name, n]) => {
      const o = document.createElement("option");
      o.value = name;
      o.textContent = `${name} (${fmtNum(n)})`;
      el.source.append(o);
    });

    el.q.value = state.q;
    el.location.value = state.loc;
    el.source.value = state.source;
    el.sort.value = state.sort;
    el.expired.checked = state.expired;
    syncWindowButtons();
  }

  function syncWindowButtons() {
    document.querySelectorAll("[data-window]").forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.window === state.window)));
  }

  function wireEvents() {
    el.q.addEventListener("input", debounce(() => { state.q = el.q.value.trim(); apply(); }, 150));
    el.location.addEventListener("input", debounce(() => { state.loc = el.location.value.trim(); apply(); }, 150));
    el.source.addEventListener("change", () => { state.source = el.source.value; apply(); });
    el.sort.addEventListener("change", () => { state.sort = el.sort.value; apply(); });
    el.expired.addEventListener("change", () => { state.expired = el.expired.checked; apply(); });
    document.querySelectorAll("[data-window]").forEach((b) =>
      b.addEventListener("click", () => { state.window = b.dataset.window; syncWindowButtons(); apply(); }));
    const reset = () => {
      Object.assign(state, JSON.parse(JSON.stringify(DEFAULTS)));
      document.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", "false"));
      el.q.value = el.location.value = "";
      el.source.value = "";
      el.sort.value = "newest";
      el.expired.checked = false;
      syncWindowButtons();
      apply();
    };
    $("reset").addEventListener("click", reset);
    $("empty-reset").addEventListener("click", reset);
    el.filtersToggle.addEventListener("click", () => {
      const open = el.filters.classList.toggle("open");
      el.filtersToggle.setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "/" && document.activeElement.tagName !== "INPUT") { e.preventDefault(); el.q.focus(); }
    });
    if ("IntersectionObserver" in window) {
      new IntersectionObserver((entries) => {
        if (entries.some((e) => e.isIntersecting)) renderMore();
      }, { rootMargin: "800px" }).observe(el.sentinel);
    }
  }

  // ---------- filtering ----------

  function apply() {
    if (!data) return;
    saveState();
    const q = norm(state.q);
    const terms = q.split(/\s+/).filter(Boolean);
    const loc = norm(state.loc);
    // tech / non-tech are alternatives (OR); internship / remote narrow further (AND).
    const categories = state.types.filter((t) => t === "tech" || t === "non-tech");
    const flags = state.types.filter((t) => t === "internship" || t === "remote");
    const since = state.window === "all" ? 0 : Date.now() - Number(state.window) * 3600 * 1000;

    results = jobs.filter((j) => {
      if (!state.expired && j.status !== "active") return false;
      if (since && j._posted < since) return false;
      if (terms.length && !terms.every((t) => j._hay.includes(t))) return false;
      if (loc && !j._loc.includes(loc)) return false;
      if (state.source && j.source !== state.source) return false;
      if (categories.length && !categories.some((t) => j.job_type.includes(t))) return false;
      if (flags.length && !flags.every((t) => j.job_type.includes(t))) return false;
      if (state.skills.length && !state.skills.some((s) => j.skills.includes(s))) return false;
      return true;
    });

    if (state.sort === "deadline") {
      results.sort((a, b) => (a._deadline - b._deadline) || (b._posted - a._posted));
    } else {
      results.sort((a, b) => b._posted - a._posted);
    }

    const activeCount = data.counts ? data.counts.active : jobs.filter((j) => j.status === "active").length;
    el.badge.textContent = `${fmtNum(activeCount)} active jobs`;
    const windowText = state.window === "all" ? "" : ` posted in the last ${state.window}h`;
    el.resultLine.textContent = `Showing ${fmtNum(results.length)} job${results.length === 1 ? "" : "s"}${windowText}`;

    const nFilters = state.skills.length + state.types.length + (state.loc ? 1 : 0) + (state.source ? 1 : 0) + (state.expired ? 1 : 0);
    el.filtersCount.hidden = !nFilters;
    el.filtersCount.textContent = nFilters;

    el.grid.replaceChildren();
    rendered = 0;
    el.empty.hidden = results.length > 0;
    renderMore();
  }

  // ---------- rendering ----------

  function renderSkeletons() {
    el.grid.replaceChildren(...Array.from({ length: 6 }, () => {
      const d = document.createElement("div");
      d.className = "skeleton";
      return d;
    }));
  }

  function pill(text, cls) {
    const s = document.createElement("span");
    s.className = `pill ${cls || ""}`;
    s.textContent = text;
    return s;
  }

  function card(j) {
    const node = el.template.content.firstElementChild.cloneNode(true);
    const q = (sel) => node.querySelector(sel);
    q(".card-title").textContent = j.title;
    q(".card-company").textContent = j.company;
    q(".meta-location").textContent = j.location || "";
    q(".meta-salary").textContent = j.salary || "";
    q(".snippet").textContent = j.snippet || "";

    const pills = q(".pills");
    j.skills.forEach((s) => pills.append(pill(s, "skill")));
    j.job_type.forEach((t) => pills.append(pill(t, `type-${t}`)));

    const posted = q(".posted");
    if (j._posted) {
      posted.textContent = j.posted ? `Posted ${relTime(j._posted)}` : `Found ${relTime(j._posted)}`;
      posted.title = j.posted || j.first_seen || "";
    }
    if (j.deadline) {
      const dl = q(".deadline");
      dl.textContent = `Apply by ${fmtDate(j.deadline)}`;
      if (j._deadline - Date.now() < 3 * 86400000) dl.classList.add("soon");
    }
    q(".source").textContent = j.source;

    const a = q(".apply");
    a.href = safeUrl(j.apply_link);
    a.setAttribute("aria-label", `Apply: ${j.title} at ${j.company} (opens ${j.source} in a new tab)`);

    if (j.status !== "active") {
      node.classList.add("is-expired");
      q(".status-pill").hidden = false;
      if (j.last_seen) q(".status-pill").title = `Last seen ${fmtDate(j.last_seen)}`;
    }
    return node;
  }

  function renderMore() {
    if (rendered >= results.length) return;
    const frag = document.createDocumentFragment();
    const end = Math.min(rendered + PAGE_SIZE, results.length);
    for (let i = rendered; i < end; i++) frag.append(card(results[i]));
    el.grid.append(frag);
    rendered = end;
    // The observer only fires when the sentinel *enters* view, so keep filling while it
    // is still near the viewport. Without IntersectionObserver, render everything.
    requestAnimationFrame(() => {
      const nearBottom = el.sentinel.getBoundingClientRect().top < window.innerHeight + 800;
      if (!("IntersectionObserver" in window) || nearBottom) renderMore();
    });
  }

  function renderHealth() {
    const rows = (data.sources || []).map((s) => {
      const tr = document.createElement("tr");
      const cells = [
        s.source,
        fmtNum(s.jobs_active || 0),
        s.feeds ? `${s.ok}/${s.feeds}` : "—",
        s.last_run ? relTime(Date.parse(s.last_run)) : "—",
        (s.errors || []).join(" · ") || "—",
      ];
      cells.forEach((text, i) => {
        const td = document.createElement("td");
        td.textContent = text;
        if (i === 1 || i === 2) td.className = "num";
        if (i === 2 && s.failed) td.classList.add("bad");
        if (i === 4) td.className = "errors";
        tr.append(td);
      });
      return tr;
    });
    el.healthBody.replaceChildren(...rows);
  }

  wireEvents();
  load();
})();
