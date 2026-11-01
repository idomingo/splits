/* Splits dashboard: sync, feed, charts. No build step, ECharts + Leaflet only. */
(function () {
  "use strict";

  const $ = (s, root) => (root || document).querySelector(s);
  const $$ = (s, root) => Array.from((root || document).querySelectorAll(s));
  const SPORTS = ["run", "walk", "cycle", "swim", "strength", "other"];
  const SPORT_LABEL = { run: "Running", walk: "Walking", cycle: "Cycling", swim: "Swimming", strength: "Strength", other: "Other" };
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  /* ---------- theme tokens ---------- */
  function tokens() {
    const cs = getComputedStyle(document.documentElement);
    const v = (n) => cs.getPropertyValue(n).trim();
    const dark = cs.getPropertyValue("color-scheme").trim() === "dark";
    const t = {
      dark, page: v("--page"), surface: v("--surface"), surface2: v("--surface-2"), ink: v("--ink"), ink2: v("--ink-2"),
      muted: v("--muted"), line: v("--line"), lineStrong: v("--line-strong"), grid: v("--grid"),
      hr: v("--hr"), elev: v("--elev"), cad: v("--cad"), pwr: v("--pwr"), font: v("--font"),
      sport: {}, zone: [v("--z1"), v("--z2"), v("--z3"), v("--z4"), v("--z5")],
    };
    SPORTS.forEach((s) => (t.sport[s] = v("--c-" + s)));
    t.group = { easy: v("--g-easy"), workout: v("--g-workout"), long: v("--g-long"), race: v("--g-race") };
    t.wind = v("--wind");
    // single-hue sequential ramp (blue), light to dark; reversed on a dark surface
    const ramp = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"];
    t.ramp = dark ? ramp.slice().reverse() : ramp;
    return t;
  }

  /* ---------- formatting ---------- */
  const pad = (n) => String(n).padStart(2, "0");
  function dur(s) {
    if (s == null || isNaN(s)) return "-";
    s = Math.round(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
  }
  const pace = (s) => (s == null || !isFinite(s) ? "-" : `${Math.floor(Math.round(s) / 60)}:${pad(Math.round(s) % 60)}`);
  function hm(h) {
    const mins = Math.round(h * 60);
    return mins >= 60 ? `${Math.floor(mins / 60)} h ${pad(mins % 60)} min` : `${mins} min`;
  }
  const num = (v, d = 0) => (v == null || isNaN(v) ? "-" : Number(v).toLocaleString("en", { minimumFractionDigits: d, maximumFractionDigits: d }));
  function parseDate(s) { const [y, m, d] = s.slice(0, 10).split("-").map(Number); return new Date(y, m - 1, d); }
  function dayLabel(s) { const d = parseDate(s); return `${DAYS[(d.getDay() + 6) % 7]} ${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`; }
  function shortDate(s) { const d = parseDate(s); return `${d.getDate()} ${MONTHS[d.getMonth()]}`; }
  function monthLabel(s) { const d = parseDate(s); return `${MONTHS[d.getMonth()]} ${d.getFullYear()}`; }
  function compact(v) { return Math.abs(v) >= 1000 ? (v / 1000).toFixed(v % 1000 === 0 ? 0 : 1) + "K" : String(Math.round(v * 10) / 10); }

  /* ---------- chart registry (re-render on theme change) ---------- */
  const registry = [];
  function chart(el, build, opts) {
    el = typeof el === "string" ? document.getElementById(el) : el;
    if (!el || !window.echarts) return null;
    const entry = { el, build, opts: opts || {}, chart: null };
    entry.render = function () {
      if (entry.chart) entry.chart.dispose();
      entry.chart = echarts.init(el, null, { renderer: "svg" });
      if (entry.opts.group) entry.chart.group = entry.opts.group;
      const option = build(tokens(), entry);
      if (option) { fitLegend(option, el); entry.chart.setOption(option, true); }
      if (entry.opts.after) entry.opts.after(entry.chart);
    };
    entry.render();
    registry.push(entry);
    return entry;
  }
  // a legend that wraps onto more lines pushes the plot down instead of sitting on the top axis label
  function fitLegend(option, el) {
    const lg = option.legend, g = option.grid;
    if (!lg || !lg.data || !g || Array.isArray(g)) return;
    const avail = el.clientWidth - 8;
    let rows = 1, x = 0;
    lg.data.forEach((name) => {
      const w = 12 + 5 + String(name).length * 7 + (lg.itemGap || 16);
      if (x > 0 && x + w > avail) { rows++; x = w; } else x += w;
    });
    if (rows > 1) g.top = (g.top == null ? 30 : g.top) + (rows - 1) * 22;
  }
  function rerenderAll() {
    registry.forEach((e) => e.render());
    if (window.__afterRerender) window.__afterRerender();
  }
  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => registry.forEach((e) => e.chart && e.chart.resize()), 120);
  });

  /* ---------- shared chart pieces ---------- */
  function base(t) {
    return {
      animationDuration: 350,
      textStyle: { fontFamily: t.font, color: t.ink2, fontSize: 12 },
      grid: { left: 6, right: 14, top: 30, bottom: 6, containLabel: true },
      tooltip: tooltipBase(t),
    };
  }
  function tooltipBase(t) {
    return {
      trigger: "axis",
      backgroundColor: t.surface, borderColor: t.line, borderWidth: 1, padding: [8, 12],
      textStyle: { color: t.ink, fontFamily: t.font },
      extraCssText: "border-radius:12px;box-shadow:0 8px 28px rgba(0,0,0,.14);",
      axisPointer: { type: "line", lineStyle: { color: t.lineStrong, width: 1 } },
      confine: true,
    };
  }
  function legend(t, data) {
    return { top: 0, left: 0, data, icon: "roundRect", itemWidth: 12, itemHeight: 10, itemGap: 16,
             textStyle: { color: t.ink2, fontSize: 12.5 }, inactiveColor: t.lineStrong };
  }
  function axisCat(t, data, fmt) {
    return { type: "category", data, axisTick: { show: false }, axisLine: { lineStyle: { color: t.lineStrong } },
             axisLabel: { color: t.muted, formatter: fmt, hideOverlap: true } };
  }
  function axisVal(t, fmt, extra) {
    return Object.assign({ type: "value", splitLine: { lineStyle: { color: t.grid } }, axisLine: { show: false },
             axisLabel: { color: t.muted, formatter: fmt || compact, hideOverlap: true }, axisTick: { show: false } }, extra || {});
  }
  function axisTime(t, extra) {
    return Object.assign({ type: "time", axisLine: { lineStyle: { color: t.lineStrong } }, axisTick: { show: false },
             splitLine: { show: false },
             splitNumber: 5, minInterval: 86400000,
             axisLabel: { color: t.muted, hideOverlap: true, formatter: (v) => { const d = new Date(v); return d.getMonth() === 0 && d.getDate() === 1 ? String(d.getFullYear()) : d.getDate() === 1 ? MONTHS[d.getMonth()] : `${d.getDate()} ${MONTHS[d.getMonth()]}`; } } }, extra || {});
  }
  // a time axis over only a few days (a short trip) gets two weeks of room, so the dots do not sit on the edges
  function timeSpan(dates) {
    const ts = dates.filter(Boolean).map((d) => parseDate(d).getTime());
    if (!ts.length) return {};
    const lo = Math.min(...ts), hi = Math.max(...ts), want = 14 * 86400000;
    if (hi - lo >= want) return {};
    const pad = (want - (hi - lo)) / 2;
    return { min: lo - pad, max: hi + pad };
  }
  function esc(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
  function ttHtml(title, rows) {
    // values lead, labels follow; a short line key per series
    let h = `<div class="tt"><div class="tt-title">${esc(title)}</div>`;
    rows.forEach((r) => {
      h += `<div class="tt-row"><span class="tt-key" style="background:${r.color || "transparent"}"></span><span class="tt-name">${esc(r.name)}</span><span class="tt-val">${esc(r.value)}</span></div>`;
    });
    return h + "</div>";
  }
  function rolling(points, days) {
    // points: [[iso, v]], returns rolling mean over `days` calendar days
    const out = [];
    let j = 0, sum = 0, n = 0;
    const ts = points.map((p) => parseDate(p[0]).getTime());
    for (let i = 0; i < points.length; i++) {
      if (points[i][1] != null) { sum += points[i][1]; n++; }
      while (ts[j] <= ts[i] - days * 86400000) { if (points[j][1] != null) { sum -= points[j][1]; n--; } j++; }
      out.push([points[i][0], n ? Math.round((sum / n) * 10) / 10 : null]);
    }
    return out;
  }
  // stacked bars: 2px surface gap between segments, 4px rounded top on the top segment only
  function stackedBars(t, keys, seriesData, colors, names) {
    const n = seriesData[keys[0]] ? seriesData[keys[0]].length : 0;
    const topIdx = [];
    for (let i = 0; i < n; i++) {
      let top = -1;
      keys.forEach((k, ki) => { if ((seriesData[k] || [])[i] > 0) top = ki; });
      topIdx.push(top);
    }
    const dense = n > 70;  // thin bars: a 1px gap would eat most of the colour
    return keys.map((k, ki) => ({
      name: names[k], type: "bar", stack: "total", barMaxWidth: 24,
      itemStyle: { color: colors[k], borderColor: t.surface, borderWidth: dense ? 0 : 1 },
      emphasis: { focus: "series" },
      data: (seriesData[k] || []).map((v, i) => ({ value: v, itemStyle: topIdx[i] === ki ? { borderRadius: dense ? [2, 2, 0, 0] : [4, 4, 0, 0] } : undefined })),
    }));
  }


  function monthTick(v) { const d = parseDate(v); return d.getMonth() === 0 ? String(d.getFullYear()) : MONTHS[d.getMonth()]; }

  // day-by-day bars: every day is kept; when they do not fit, a slider picks the window (and keeps it across re-renders)
  function zoomState(n, el) {
    const size = () => (el.clientWidth < 640 ? 60 : 150);
    const st = { win: null };
    st.has = () => n > size();
    st.option = (t) => {
      if (!st.has()) return undefined;
      const w = st.win || [n - size(), n - 1];
      return [{
        type: "slider", xAxisIndex: 0, startValue: w[0], endValue: w[1], bottom: 8, height: 22, brushSelect: false, showDetail: true,
        borderColor: t.line, backgroundColor: "transparent", fillerColor: t.dark ? "rgba(255,255,255,.08)" : "rgba(19,33,46,.07)",
        dataBackground: { lineStyle: { color: t.lineStrong, width: 1 }, areaStyle: { color: t.grid, opacity: 1 } },
        selectedDataBackground: { lineStyle: { color: t.muted, width: 1 }, areaStyle: { color: t.lineStrong, opacity: 0.7 } },
        handleStyle: { color: t.surface, borderColor: t.muted }, moveHandleSize: 5, moveHandleStyle: { color: t.lineStrong, opacity: 1 },
        emphasis: { handleStyle: { borderColor: t.ink }, moveHandleStyle: { color: t.muted } },
        textStyle: { color: t.muted, fontSize: 11, fontFamily: t.font },
        labelFormatter: (i, str) => { if (!str) return ""; const d = parseDate(str); return `${d.getDate()} ${MONTHS[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`; },
      }];
    };
    st.after = (c) => c.on("datazoom", () => {
      const z = c.getOption().dataZoom;
      if (z && z[0] && z[0].startValue != null) st.win = [z[0].startValue, z[0].endValue];
    });
    return st;
  }

  /* ---------- sparklines (inline SVG, no chart instance) ---------- */
  function sparks() {
    $$(".spark[data-spark]").forEach((el) => {
      const vals = el.dataset.spark.split(",").map(Number).filter((v) => !isNaN(v));
      if (vals.length < 2) return;
      const w = 200, h = 34, p = 3;
      const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
      const pts = vals.map((v, i) => [p + (i * (w - 2 * p)) / (vals.length - 1), h - p - ((v - min) / span) * (h - 2 * p)]);
      const d = pts.map((q, i) => (i ? "L" : "M") + q[0].toFixed(1) + " " + q[1].toFixed(1)).join("");
      const last = pts[pts.length - 1];
      el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" width="100%" height="${h}"><path d="${d}" fill="none" stroke="var(--line-strong)" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg><span class="spark-dot" style="left:calc(${(last[0] / w) * 100}% - 4px);top:${last[1] - 4}px"></span>`;
      el.style.position = "relative";
    });
  }

  /* ---------- theme toggle ---------- */
  function initTheme() {
    const btn = $("#theme-toggle");
    if (!btn) return;
    const label = $("span", btn);
    const read = () => document.documentElement.dataset.theme || "auto";
    const show = () => (label.textContent = "Theme: " + read());
    show();
    btn.addEventListener("click", () => {
      const next = { auto: "light", light: "dark", dark: "auto" }[read()];
      if (next === "auto") delete document.documentElement.dataset.theme;
      else document.documentElement.dataset.theme = next;
      try { next === "auto" ? localStorage.removeItem("splits-theme") : localStorage.setItem("splits-theme", next); } catch (e) {}
      show();
      rerenderAll();
    });
    if (window.matchMedia) {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      (mq.addEventListener ? mq.addEventListener.bind(mq, "change") : mq.addListener.bind(mq))(() => { if (read() === "auto") rerenderAll(); });
    }
  }

  /* ---------- toast ---------- */
  let toastTimer;
  function toast(html, ms) {
    const el = $("#toast");
    if (!el) return;
    el.innerHTML = html;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (el.hidden = true), ms || 5000);
  }

  /* ---------- sync ---------- */
  function initSync() {
    const box = $("#sync");
    if (!box) return;
    const btn = $("#sync-btn"), label = $(".sync-label", btn), status = $("#sync-status");
    const bar = $(".sync-progress", box), fill = $(".sync-progress span", box);
    const csrf = ($("input[name=csrfmiddlewaretoken]", box) || {}).value;
    let polling = null, runId = box.dataset.running || null;
    const idleLabel = label.textContent;

    function setRunning(on) {
      box.classList.toggle("is-running", on);
      btn.disabled = on;
      $$("[data-sync-trigger]").forEach((b) => (b.disabled = on));
      bar.hidden = !on;
      label.textContent = on ? "Syncing" : idleLabel;
    }
    function update(s) {
      if (s.status === "running") {
        setRunning(true);
        const pct = s.total ? Math.min(100, (100 * s.done) / s.total) : null;
        bar.classList.toggle("is-indeterminate", pct == null);
        fill.style.width = pct == null ? "" : pct + "%";
        // first sync on an empty page: show the activities as soon as the list is in
        if (box.dataset.empty === "1" && s.phase && s.phase !== "Activities" && s.phase !== "Heart rate zones" && s.phase !== "Starting") {
          box.dataset.empty = "0";
          location.reload();
          return;
        }
        let text = s.phase || "Starting";
        if (s.total) text += ` ${s.done} of ${s.total}`;
        else if (s.done) text += ` ${s.done}`;
        status.textContent = text;
        return;
      }
      stop();
      setRunning(false);
      if (s.status === "failed") {
        status.textContent = "Last sync failed";
        toast(`<strong>Sync failed.</strong> ${esc(s.error || s.message || "")}`, 9000);
      } else if (s.status === "ok" || s.status === "partial") {
        status.textContent = "Last sync just now";
        const n = s.new || 0;
        const more = s.status === "partial" ? " Some data sets could not be read; see the terminal for details." : "";
        toast(n ? `<strong>${n} new activit${n === 1 ? "y" : "ies"}.</strong> Refreshing the page.${more}` : `<strong>You are up to date.</strong> Refreshing the page.${more}`, 4000);
        // the sync may also have sorted runs, found places or added weather: always show the new state
        setTimeout(() => location.reload(), 1200);
      }
    }
    function poll() {
      fetch(box.dataset.statusUrl + (runId ? "?id=" + runId : ""), { headers: { Accept: "application/json" } })
        .then((r) => r.json()).then(update).catch(() => {});
    }
    function startPolling() { if (!polling) { poll(); polling = setInterval(poll, 1500); } }
    function stop() { clearInterval(polling); polling = null; }
    function start() {
      setRunning(true);
      bar.classList.add("is-indeterminate");
      status.textContent = "Starting";
      const body = new URLSearchParams();
      fetch(box.dataset.startUrl, { method: "POST", headers: { "X-CSRFToken": csrf }, body })
        .then((r) => r.json()).then((s) => { runId = s.id; update(s); startPolling(); })
        .catch(() => { setRunning(false); toast("<strong>Could not start the sync.</strong> Is the app still running?"); });
    }
    btn.addEventListener("click", start);
    $$("[data-sync-trigger]").forEach((b) => b.addEventListener("click", start));
    if (runId) { setRunning(true); startPolling(); }
  }

  /* ---------- feed: load earlier weeks ---------- */
  function initFeed() {
    const list = $(".feed-list");
    if (!list) return;
    let busy = false;
    function load(more) {
      if (busy) return;
      busy = true;
      const btn = $("button", more);
      if (btn) { btn.disabled = true; btn.textContent = "Loading"; }
      fetch(more.dataset.url).then((r) => r.text()).then((html) => {
        const tpl = document.createElement("template");
        tpl.innerHTML = html;
        more.replaceWith(tpl.content);
        busy = false;
        watch();
      }).catch(() => { busy = false; if (btn) { btn.disabled = false; btn.textContent = "Show earlier weeks"; } });
    }
    const io = "IntersectionObserver" in window ? new IntersectionObserver((entries) => {
      entries.forEach((e) => { if (e.isIntersecting) { io.unobserve(e.target); load(e.target); } });
    }, { rootMargin: "600px" }) : null;
    function watch() {
      const more = $(".feed-more", list);
      if (!more) return;
      $("button", more).addEventListener("click", () => load(more));
      if (io) io.observe(more);
    }
    watch();
  }

  /* ---------- selects that apply on change ---------- */
  function initAutoSubmit() {
    document.documentElement.classList.add("js");
    $$("select[data-autosubmit]").forEach((sel) => sel.addEventListener("change", () => {
      const form = sel.form;
      if (!sel.value) { location.href = location.pathname; return; }  // Everywhere: drop the filter
      form.submit();
    }));
  }

  /* ---------- seg buttons ---------- */
  function seg(attr, onChange) {
    const btns = $$(`[data-${attr}]`);
    btns.forEach((b) => b.addEventListener("click", () => {
      btns.forEach((x) => x.classList.toggle("is-on", x === b));
      onChange(b.dataset[attr]);
    }));
  }

  /* =================================================================
     Pages
     ================================================================= */
  const PAGES = {};

  PAGES.overview = function (data) {
    let metric = "hours";
    const sports = data.sports;
    const weekly = chart("chart-weekly", (t) => {
      const series = metric === "km" ? data.weekly.km : data.weekly.hours;
      const keys = sports.filter((s) => series[s]);
      return Object.assign(base(t), {
        legend: legend(t, keys.map((k) => SPORT_LABEL[k])),
        xAxis: axisCat(t, data.weekly.weeks, shortDate),
        yAxis: axisVal(t, (v) => (metric === "km" ? v + " km" : v + " h")),
        tooltip: Object.assign(tooltipBase(t), {
          axisPointer: { type: "shadow", shadowStyle: { color: t.dark ? "rgba(255,255,255,.04)" : "rgba(0,0,0,.035)" } },
          formatter: (ps) => {
            const total = ps.reduce((a, p) => a + (p.value || 0), 0);
            const rows = ps.filter((p) => p.value > 0).reverse().map((p) => ({ color: p.color, name: p.seriesName, value: metric === "km" ? num(p.value, 1) + " km" : hm(p.value) }));
            rows.push({ name: "Total", value: metric === "km" ? num(total, 1) + " km" : hm(total) });
            return ttHtml("Week of " + dayLabel(ps[0].axisValue), rows);
          },
        }),
        series: stackedBars(t, keys, series, t.sport, SPORT_LABEL),
      });
    });
    seg("weekly", (m) => { metric = m; weekly && weekly.render(); });

    chart("chart-load", (t) => {
      const L = data.load;
      const bands = [[0, 0.8, t.zone[0]], [0.8, 1.3, t.zone[2]], [1.3, 1.5, t.zone[3]], [1.5, 3, t.zone[4]]];
      const rmax = Math.max(1.8, ...L.ratio.filter((v) => v != null).map((v) => Math.ceil(v * 10) / 10 + 0.1));
      return {
        animationDuration: 350,
        textStyle: { fontFamily: t.font, color: t.ink2, fontSize: 12 },
        legend: legend(t, ["Last 7 days", "Usual week"]),
        axisPointer: { link: [{ xAxisIndex: "all" }] },
        grid: [{ left: 44, right: 14, top: 30, height: "46%" }, { left: 44, right: 14, top: "66%", bottom: 24 }],
        xAxis: [Object.assign(axisCat(t, L.dates, shortDate), { gridIndex: 0, axisLabel: { show: false } }),
                Object.assign(axisCat(t, L.dates, shortDate), { gridIndex: 1 })],
        yAxis: [Object.assign(axisVal(t, (v) => compact(v)), { gridIndex: 0, splitNumber: 3 }),
                Object.assign(axisVal(t, (v) => v.toFixed(1)), { gridIndex: 1, min: 0, max: rmax, interval: 0.5 })],
        tooltip: Object.assign(tooltipBase(t), {
          formatter: (ps) => {
            const i = ps[0].dataIndex;
            return ttHtml(dayLabel(L.dates[i]), [
              { color: t.ink, name: "Load, last 7 days", value: num(L.acute[i]) },
              { color: t.muted, name: "Usual week (last 28 days)", value: num(L.usual[i]) },
              { name: "Ratio", value: L.ratio[i] == null ? "-" : L.ratio[i].toFixed(2) },
            ]);
          },
        }),
        series: [
          { name: "Usual week", type: "line", data: L.usual, showSymbol: false, smooth: 0.2, lineStyle: { width: 2, color: t.muted }, itemStyle: { color: t.muted },
            areaStyle: { color: t.muted, opacity: 0.1 } },
          { name: "Last 7 days", type: "line", data: L.acute, showSymbol: false, smooth: 0.2, lineStyle: { width: 2, color: t.ink }, itemStyle: { color: t.ink } },
          { name: "Ratio", type: "line", xAxisIndex: 1, yAxisIndex: 1, data: L.ratio, showSymbol: false, smooth: 0.2, connectNulls: false,
            lineStyle: { width: 2, color: t.ink }, itemStyle: { color: t.ink },
            markArea: { silent: true, data: bands.map(([a, b, c]) => [{ yAxis: a, itemStyle: { color: c, opacity: t.dark ? 0.18 : 0.13 } }, { yAxis: Math.min(b, rmax) }]) } },
        ],
      };
    });

    chart("chart-calendar", (t, entry) => {
      const narrow = entry.el.clientWidth < 640;
      const end = data.calendar.end;
      const startDate = parseDate(end);
      startDate.setDate(startDate.getDate() - (narrow ? 181 : 364));
      // never before the first activity: a new user sees their weeks, not a year of empty squares
      const first = parseDate(data.calendar.start);
      if (first > startDate) startDate.setTime(first.getTime());
      const start = `${startDate.getFullYear()}-${pad(startDate.getMonth() + 1)}-${pad(startDate.getDate())}`;
      const weeks = Math.ceil((parseDate(end) - startDate) / (7 * 86400000)) + 1;
      // keep square-ish cells when there are only a few weeks
      const cell = Math.min(26, (entry.el.clientWidth - 40) / Math.max(weeks, 1));
      const pieces = [
        { min: 1, max: 30, color: t.ramp[0], label: narrow ? "<30" : "< 30 min" },
        { min: 30, max: 60, color: t.ramp[1], label: narrow ? "30-60" : "30-60 min" },
        { min: 60, max: 90, color: t.ramp[3], label: narrow ? "60-90" : "1-1.5 h" },
        { min: 90, max: 150, color: t.ramp[4], label: narrow ? "90-150" : "1.5-2.5 h" },
        { min: 150, color: t.ramp[5], label: narrow ? "150+ min" : "> 2.5 h" },
      ];
      return {
        textStyle: { fontFamily: t.font, color: t.ink2 },
        tooltip: Object.assign(tooltipBase(t), { trigger: "item", formatter: (p) => ttHtml(dayLabel(p.value[0]), [{ name: "Active", value: p.value[1] ? hm(p.value[1] / 60) : "rest day" }]) }),
        visualMap: { type: "piecewise", pieces, orient: "horizontal", right: narrow ? undefined : 0, left: narrow ? 0 : undefined, bottom: 0, itemWidth: 12, itemHeight: 12, itemGap: narrow ? 6 : 10,
                     textStyle: { color: t.muted, fontSize: 11.5 }, showLabel: true, outOfRange: { color: t.surface2 } },
        calendar: {
          range: [start, end], top: 24, left: 34, bottom: 36, cellSize: [cell, "auto"],
          splitLine: { show: false }, itemStyle: { color: t.surface2, borderColor: t.surface, borderWidth: 3 },
          yearLabel: { show: false }, dayLabel: { firstDay: 1, nameMap: ["S", "M", "T", "W", "T", "F", "S"], color: t.muted, fontSize: 11 },
          monthLabel: { color: t.muted, fontSize: 11.5, nameMap: MONTHS },
        },
        series: [{ type: "heatmap", coordinateSystem: "calendar", data: data.calendar.days }],
      };
    });
  };

  PAGES.sport = function (data) {
    const cat = data.category;
    const paceMode = data.pace_mode;
    const M = data.monthly, D = data.daily;
    const unitFmt = (v) => (M.unit === "km" ? num(v, 1) + " km" : hm(v));
    const axisUnit = (v) => (M.unit === "km" ? compact(v) + " km" : v + " h");
    // runs are split into four colour groups; one kind of run, or another sport, uses one colour
    const mainColor = (t) => (data.kind_group ? t.group[data.kind_group] : t.sport[cat]);
    const colorOf = (t, g) => (g === "all" ? mainColor(t) : t.group[g]);
    const colors = (t) => { const c = {}; M.groups.forEach((g) => (c[g] = colorOf(t, g))); return c; };
    const multi = M.groups.length > 1;
    function go(p) { if (p && p.data && p.data.id) location.href = "/activity/" + p.data.id + "/"; }
    const shadow = (t) => ({ type: "shadow", shadowStyle: { color: t.dark ? "rgba(255,255,255,.04)" : "rgba(0,0,0,.035)" } });

    chart("chart-monthly", (t) => Object.assign(base(t), {
      legend: multi ? legend(t, M.groups.map((g) => M.labels[g])) : undefined,
      grid: { left: 6, right: 14, top: multi ? 30 : 16, bottom: 6, containLabel: true },
      xAxis: axisCat(t, M.months, monthTick),
      yAxis: axisVal(t, axisUnit),
      tooltip: Object.assign(tooltipBase(t), {
        axisPointer: shadow(t),
        formatter: (ps) => {
          const i = ps[0].dataIndex;
          const rows = ps.filter((p) => p.value > 0).reverse().map((p) => ({ color: p.color, name: p.seriesName, value: unitFmt(p.value) }));
          if (multi) rows.push({ name: "Total", value: unitFmt(M.groups.reduce((a, g) => a + (M.values[g][i] || 0), 0)) });
          rows.push({ name: "Sessions", value: M.count[i] });
          return ttHtml(monthLabel(ps[0].axisValue), rows);
        },
      }),
      series: stackedBars(t, M.groups, M.values, colors(t), M.labels),
    }));

    // day by day: every day since the first session; a slider when there are too many days to fit
    const dailyEl = document.getElementById("chart-daily");
    if (dailyEl) {
      const zoom = zoomState(D.days.length, dailyEl);
      chart(dailyEl, (t) => Object.assign(base(t), {
        legend: multi ? legend(t, D.groups.map((g) => D.labels[g])) : undefined,
        grid: { left: 6, right: 14, top: multi ? 30 : 16, bottom: zoom.has() ? 50 : 6, containLabel: true },
        xAxis: axisCat(t, D.days, shortDate),
        yAxis: axisVal(t, axisUnit),
        dataZoom: zoom.option(t),
        tooltip: Object.assign(tooltipBase(t), {
          axisPointer: shadow(t),
          formatter: (ps) => {
            const i = ps[0].dataIndex;
            const acts = D.acts[i] || [];
            if (!acts.length) return ttHtml(dayLabel(ps[0].axisValue), [{ name: "Rest day", value: "" }]);
            const rows = acts.map((a) => ({ name: a.kind || "Session", value: a.km ? num(a.km, 1) + " km" : a.min + " min" }));
            if (acts.length > 1) rows.push({ name: "Total", value: unitFmt(D.groups.reduce((s, g) => s + (D.values[g][i] || 0), 0)) });
            return ttHtml(dayLabel(ps[0].axisValue), rows);
          },
        }),
        series: stackedBars(t, D.groups, D.values, colors(t), D.labels).map((s) => Object.assign(s, { barMaxWidth: 14 })),
      }), { after: zoom.after });
    }

    // pace (or speed) over time: one series per group so races stand out
    const pts = data.points;
    const y = (p) => (paceMode ? p.pace : p.kmh);
    const yFmt = (v) => (paceMode ? pace(v) + " /km" : num(v, 1) + " km/h");
    // one kind of run (or another sport) is a single series; all running splits into the four groups
    const pg = (p) => (data.kind || cat !== "run" ? "all" : p.group);
    const ptGroups = [];
    pts.forEach((p) => { if (ptGroups.indexOf(pg(p)) < 0) ptGroups.push(pg(p)); });
    const order = ["easy", "workout", "long", "race", "all"];
    ptGroups.sort((a, b) => order.indexOf(a) - order.indexOf(b));
    const groupName = (g) => (g === "all" ? (data.kind ? M.labels.all || "Session" : "Session") : (M.labels[g] || g));
    if (data.zone_pace) {
      // runs: pace while heart rate sat in the same band, so easy days, tempo work and races each compare with
      // their own kind of effort (the bands come from the runner's own zones)
      const Z = data.zone_pace;
      const zc = (t, k) => ({ z2: t.zone[1], z34: t.zone[3], z45: t.zone[4] })[k];
      chart("chart-pace", (t) => {
        const series = [];
        Z.forEach((b) => {
          series.push({ name: b.label, type: "scatter", symbolSize: 7, z: 2,
            itemStyle: { color: zc(t, b.key), opacity: 0.55, borderColor: t.surface, borderWidth: 1 },
            data: b.points.map((p) => ({ value: [p.date, p.pace], id: p.id, name: p.name, min: p.min, hr: p.hr, kind: p.kind, band: b.label, range: b.range })) });
          if (b.line.length) series.push({ name: b.label, type: "line", showSymbol: false, smooth: 0.3, z: 4, line: true,
            lineStyle: { width: 2.5, color: zc(t, b.key) }, itemStyle: { color: zc(t, b.key) }, data: b.line, tooltip: { show: false } });
        });
        const all = Z.flatMap((b) => b.points.map((p) => p.date));
        return Object.assign(base(t), {
          grid: { left: 6, right: 14, top: 30, bottom: 6, containLabel: true },
          legend: legend(t, Z.map((b) => b.label)),
          xAxis: axisTime(t, timeSpan(all)),
          yAxis: axisVal(t, pace, { inverse: true, scale: true }),
          tooltip: Object.assign(tooltipBase(t), {
            trigger: "item",
            formatter: (p) => {
              const d = p.data;
              if (!d || !d.name) return "";
              return ttHtml(d.name, [
                { name: dayLabel(d.value[0]), value: "" },
                { color: p.color, name: "Pace in " + d.band.toLowerCase(), value: pace(d.value[1]) + " /km" },
                { name: "Time in that band", value: d.min + " min" },
                { name: "Average heart rate there", value: d.hr + " bpm" },
              ].concat(d.kind ? [{ name: "Kind", value: d.kind }] : []));
            },
          }),
          series,
        });
      }, { after: (c) => c.on("click", go) });
    } else chart("chart-pace", (t) => {
      const series = ptGroups.map((g) => {
        const race = g === "race";
        return {
          name: groupName(g), type: "scatter", symbolSize: race ? 11 : 8, z: race ? 4 : 2,
          itemStyle: { color: colorOf(t, g), opacity: race ? 1 : 0.7, borderColor: race ? t.ink : t.surface, borderWidth: race ? 1.5 : 1 },
          data: pts.filter((p) => pg(p) === g).map((p) => ({ value: [p.date, y(p)], id: p.id, name: p.name, km: p.km, hr: p.hr, kind: p.kind })),
        };
      });
      if (data.pace_line.length) {
        series.push({ name: "6-week median", type: "line", showSymbol: false, smooth: 0.3, lineStyle: { width: 2, color: t.ink }, itemStyle: { color: t.ink }, z: 5,
                      data: paceMode ? data.pace_line : data.pace_line.map((r) => [r[0], Math.round(36000 / r[1]) / 10]) });
      }
      return Object.assign(base(t), {
        grid: { left: 6, right: 14, top: 30, bottom: 6, containLabel: true },
        legend: legend(t, series.map((s) => s.name)),
        xAxis: axisTime(t, timeSpan(pts.map((p) => p.date))),
        yAxis: axisVal(t, paceMode ? pace : (v) => v + " km/h", { inverse: paceMode, scale: true }),
        tooltip: Object.assign(tooltipBase(t), {
          trigger: "item",
          formatter: (p) => {
            if (p.seriesName === "6-week median") return ttHtml(dayLabel(p.value[0]), [{ color: t.ink, name: "Median", value: yFmt(p.value[1]) }]);
            const d = p.data;
            return ttHtml(d.name, [
              { name: dayLabel(d.value[0]), value: "" },
              { color: p.color, name: paceMode ? "Pace" : "Speed", value: yFmt(d.value[1]) },
              { name: "Distance", value: num(d.km, 2) + " km" },
              { name: "Heart rate", value: d.hr ? num(d.hr) + " bpm" : "-" },
            ].concat(d.kind ? [{ name: "Kind", value: d.kind }] : []));
          },
        }),
        series,
      });
    }, { after: (c) => c.on("click", go) });

    chart("chart-eff", (t) => Object.assign(base(t), {
      grid: { left: 6, right: 14, top: 30, bottom: 6, containLabel: true },
      legend: legend(t, ["Session", "6-week median"]),
      xAxis: axisTime(t, timeSpan(data.efficiency.points.map((p) => p[0]))),
      yAxis: axisVal(t, (v) => v.toFixed(2) + " m", { scale: true }),
      tooltip: Object.assign(tooltipBase(t), { trigger: "item", formatter: (p) => ttHtml(dayLabel(p.value[0]), [{ color: p.color, name: p.seriesName, value: p.value[1].toFixed(2) + " m per beat" }]) }),
      series: [
        { name: "Session", type: "scatter", symbolSize: 7, itemStyle: { color: mainColor(t), opacity: 0.45 }, data: data.efficiency.points },
        { name: "6-week median", type: "line", showSymbol: false, smooth: 0.3, lineStyle: { width: 2, color: t.ink }, itemStyle: { color: t.ink }, data: data.efficiency.line },
      ],
    }));

    if (data.race_vdot && data.race_vdot.length > 1) {
      chart("chart-vdot", (t) => Object.assign(base(t), {
        grid: { left: 6, right: 14, top: 16, bottom: 6, containLabel: true },
        xAxis: axisTime(t, timeSpan(data.race_vdot.map((r) => r[0]))),
        yAxis: axisVal(t, (v) => num(v, 0), { scale: true }),
        tooltip: Object.assign(tooltipBase(t), { trigger: "item", formatter: (p) => ttHtml(p.data.r[3], [
          { name: dayLabel(p.data.r[0]), value: "" }, { color: p.color, name: "VDOT", value: num(p.data.r[1], 1) }, { name: "Time", value: dur(p.data.r[4]) }]) }),
        series: [{ type: "line", data: data.race_vdot.map((r) => ({ value: [r[0], r[1]], id: r[2], r })), symbol: "circle", symbolSize: 9,
                   lineStyle: { width: 2, color: t.group.race }, itemStyle: { color: t.group.race, borderColor: t.surface, borderWidth: 1.5 } }],
      }), { after: (c) => c.on("click", go) });
    }

    // best efforts: a small chart per distance (different scales, so no shared axis), best of each month
    const multiples = document.getElementById("chart-progress");
    if (multiples) {
      const tick = (s) => { const d = parseDate(s); return `${MONTHS[d.getMonth()]} \u2019${String(d.getFullYear()).slice(2)}`; };
      const minis = [];
      Object.values(data.progress).sort((a, b) => a.dist - b.dist).forEach((P) => {
        const wrap = document.createElement("div");
        wrap.className = "mini-wrap";
        const best = Math.min(...P.month.map((r) => r.secs));
        wrap.innerHTML = `<p class="mini-title">${esc(P.label)} <span>best ${esc(dur(best))}</span></p><div class="chart mini" style="height:140px"></div>`;
        multiples.appendChild(wrap);
        minis.push(chart($(".mini", wrap), (t) => {
          const rows = P.month;
          const c = mainColor(t);
          return Object.assign(base(t), {
            grid: { left: 4, right: 12, top: 8, bottom: 4, containLabel: true },
            xAxis: axisCat(t, rows.map((r) => r.p), tick),
            yAxis: axisVal(t, dur, { inverse: true, splitNumber: 3,
              min: (e) => Math.max(0, Math.floor(e.min - Math.max((e.max - e.min) * 0.15, e.min * 0.02))),
              max: (e) => Math.ceil(e.max + Math.max((e.max - e.min) * 0.15, e.max * 0.02)),
              axisLabel: { color: t.muted, formatter: dur, showMinLabel: false, showMaxLabel: false } }),
            tooltip: Object.assign(tooltipBase(t), { formatter: (ps) => {
              const i = ps[0].dataIndex;
              return ttHtml(monthLabel(rows[i].p), [{ color: c, name: "Fastest that month", value: dur(rows[i].secs) }]);
            } }),
            series: [
              { name: "Fastest", type: "line", data: rows.map((r) => ({ value: r.secs, id: r.id })), symbol: "circle", symbolSize: 7, z: 3,
                lineStyle: { width: 2, color: c }, itemStyle: { color: c, borderColor: t.surface, borderWidth: 1.5 } },
            ],
          });
        }, { after: (c) => c.on("click", go) }));
      });
    }

    // weather
    const WX = data.weather;
    if (WX) {
      const easy = WX.points.filter((p) => p.easy && p.eff != null);
      const wxTip = (t, extra) => Object.assign(tooltipBase(t), {
        trigger: "item",
        formatter: (p) => {
          if (p.seriesName === "Median") return ttHtml(p.data.band, [{ color: t.ink, name: "Median", value: num(p.value[1], 2) + " m per beat" }, { name: "Sessions", value: p.data.n }]);
          const d = p.data.p;
          return ttHtml(d.name, [
            { name: dayLabel(d.date), value: "" },
            { color: p.color, name: "Efficiency", value: d.eff != null ? num(d.eff, 2) + " m per beat" : "-" },
            { name: paceMode ? "Pace" : "Speed", value: paceMode ? pace(d.pace) + " /km" : num(3600 / d.pace, 1) + " km/h" },
            { name: "Heart rate", value: d.hr ? num(d.hr) + " bpm" : "-" },
          ].concat(extra(d)));
        },
      });
      const medianLine = (t, bins) => ({
        name: "Median", type: "line", z: 5, symbol: "circle", symbolSize: 7, lineStyle: { width: 2, color: t.ink }, itemStyle: { color: t.ink, borderColor: t.surface, borderWidth: 1.5 },
        data: bins.filter((b) => b.n >= 2 && b.x != null).map((b) => ({ value: [b.x, b.median], band: b.label, n: b.n })),
      });
      chart("chart-wx-temp", (t) => Object.assign(base(t), {
        grid: { left: 6, right: 18, top: 30, bottom: 6, containLabel: true },
        legend: legend(t, ["Session", "Median"]),
        xAxis: axisVal(t, (v) => v + "°C", { scale: true, splitLine: { show: false }, axisLine: { show: true, lineStyle: { color: t.lineStrong } } }),
        yAxis: axisVal(t, (v) => v.toFixed(2) + " m", { scale: true }),
        tooltip: wxTip(t, (d) => [{ name: "Temperature", value: num(d.temp, 0) + "°C" }, { name: "Dew point", value: d.dew != null ? num(d.dew, 0) + "°C" : "-" }]),
        series: [
          { name: "Session", type: "scatter", symbolSize: 8, itemStyle: { color: mainColor(t), opacity: 0.6, borderColor: t.surface, borderWidth: 1 },
            data: easy.filter((p) => p.temp != null).map((p) => ({ value: [p.temp, p.eff], id: p.id, p })) },
          medianLine(t, WX.by_temp),
        ],
      }), { after: (c) => c.on("click", go) });
      chart("chart-wx-wind", (t) => Object.assign(base(t), {
        grid: { left: 6, right: 28, top: 30, bottom: 6, containLabel: true },
        legend: legend(t, ["Session", "Median"]),
        xAxis: axisVal(t, (v) => v + " km/h", { min: 0, splitLine: { show: false }, axisLine: { show: true, lineStyle: { color: t.lineStrong } } }),
        yAxis: axisVal(t, (v) => v.toFixed(2) + " m", { scale: true }),
        tooltip: wxTip(t, (d) => [{ name: "Wind", value: num(d.wind, 0) + " km/h" + (d.gust ? ", gusts " + num(d.gust, 0) : "") },
                                  { name: d.head >= 0 ? "Headwind on the route" : "Tailwind on the route", value: d.head != null ? num(Math.abs(d.head), 1) + " km/h" : "-" }]),
        series: [
          { name: "Session", type: "scatter", symbolSize: 8, itemStyle: { color: mainColor(t), opacity: 0.6, borderColor: t.surface, borderWidth: 1 },
            data: easy.filter((p) => p.wind != null).map((p) => ({ value: [p.wind, p.eff], id: p.id, p })) },
          medianLine(t, WX.by_wind),
        ],
      }), { after: (c) => c.on("click", go) });
      chart("chart-wx-time", (t) => {
        const all = WX.points;
        const title = (text, top) => ({ text, top, left: 0, textStyle: { fontSize: 12.5, fontWeight: 600, color: t.ink2, fontFamily: t.font } });
        const dot = (key) => all.filter((p) => p[key] != null).map((p) => ({ value: [p.date, p[key]], id: p.id, p }));
        return {
          animationDuration: 350,
          textStyle: { fontFamily: t.font, color: t.ink2, fontSize: 12 },
          title: [title("Temperature", 0), title("Wind", "52%")],
          grid: [{ left: 6, right: 14, top: 24, height: "30%", containLabel: true }, { left: 6, right: 14, top: "62%", bottom: 6, containLabel: true }],
          xAxis: [axisTime(t, Object.assign({ gridIndex: 0, axisLabel: { show: false } }, timeSpan(all.map((p) => p.date)))),
                  axisTime(t, Object.assign({ gridIndex: 1 }, timeSpan(all.map((p) => p.date))))],
          yAxis: [axisVal(t, (v) => v + "°C", { gridIndex: 0, scale: true, splitNumber: 3 }), axisVal(t, (v) => v + " km/h", { gridIndex: 1, min: 0, splitNumber: 3 })],
          axisPointer: { link: [{ xAxisIndex: "all" }] },
          tooltip: Object.assign(tooltipBase(t), { trigger: "item", formatter: (p) => {
            const d = p.data.p;
            return ttHtml(d.name, [
              { name: dayLabel(d.date), value: "" },
              { color: mainColor(t), name: "Temperature", value: num(d.temp, 0) + "°C" },
              { name: "Wind", value: num(d.wind, 0) + " km/h" + (d.gust ? ", gusts " + num(d.gust, 0) : "") },
              { name: "Rain", value: d.rain ? num(d.rain, 1) + " mm" : "none" },
            ]);
          } }),
          series: [
            { name: "Temperature", type: "scatter", xAxisIndex: 0, yAxisIndex: 0, symbolSize: 7, itemStyle: { color: mainColor(t), opacity: 0.8 }, data: dot("temp") },
            { name: "Wind", type: "scatter", xAxisIndex: 1, yAxisIndex: 1, symbolSize: 7, itemStyle: { color: mainColor(t), opacity: 0.8 }, data: dot("wind") },
          ],
        };
      }, { after: (c) => c.on("click", go) });
    }

    chart("chart-when", (t) => {
      const max = Math.max(1, ...data.heatmap.map((h) => h[2]));
      const hours = Array.from({ length: 24 }, (_, i) => String(i));
      return {
        textStyle: { fontFamily: t.font, color: t.ink2 },
        grid: { left: 6, right: 6, top: 6, bottom: 44, containLabel: true },
        tooltip: Object.assign(tooltipBase(t), { trigger: "item", formatter: (p) => ttHtml(`${DAYS[p.value[1]]}, ${pad(p.value[0])}:00 to ${pad(p.value[0] + 1)}:00`, [{ name: "Sessions", value: p.value[2] }]) }),
        xAxis: { type: "category", data: hours, axisTick: { show: false }, axisLine: { show: false }, splitArea: { show: false }, axisLabel: { color: t.muted, interval: 2, formatter: (v) => pad(v) + "h" } },
        yAxis: { type: "category", data: DAYS, inverse: true, axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: t.muted } },
        visualMap: { min: 1, max, calculable: false, orient: "horizontal", left: "center", bottom: 0, itemWidth: 10, itemHeight: 120,
                     inRange: { color: [t.ramp[0], t.ramp[5]] }, text: ["more", "fewer"], textStyle: { color: t.muted, fontSize: 11.5 } },
        series: [{ type: "heatmap", data: data.heatmap.filter((h) => h[2] > 0), itemStyle: { borderColor: t.surface, borderWidth: 2, borderRadius: 3 } }],
      };
    });

    chart("chart-hist", (t) => Object.assign(base(t), {
      grid: { left: 6, right: 14, top: 16, bottom: 6, containLabel: true },
      xAxis: axisCat(t, data.hist.labels, (v) => v + " km"),
      yAxis: axisVal(t),
      tooltip: Object.assign(tooltipBase(t), { axisPointer: shadow(t),
                formatter: (ps) => ttHtml(ps[0].axisValue + " km", [{ color: mainColor(t), name: "Sessions", value: ps[0].value }]) }),
      series: [{ type: "bar", data: data.hist.counts, barMaxWidth: 24, itemStyle: { color: mainColor(t), borderRadius: [4, 4, 0, 0] },
                 label: { show: true, position: "top", color: t.ink2, fontSize: 11.5, formatter: (p) => (p.value ? p.value : "") } }],
    }));

    chart("chart-cadence", (t) => Object.assign(base(t), {
      grid: { left: 6, right: 14, top: 14, bottom: 6, containLabel: true },
      xAxis: axisTime(t),
      yAxis: axisVal(t, (v) => v, { scale: true }),
      tooltip: Object.assign(tooltipBase(t), { formatter: (ps) => ttHtml(monthLabel(ps[0].value[0]), [{ color: mainColor(t), name: "Cadence", value: num(ps[0].value[1]) }]) }),
      series: [{ type: "line", data: data.cadence, symbol: "circle", symbolSize: 6, lineStyle: { width: 2, color: mainColor(t) }, itemStyle: { color: mainColor(t) } }],
    }));
  };

  PAGES.activity = function (data) {
    const s = data.stream || {};
    if (!s.t) return;
    const cat = data.category, paceMode = data.pace_mode;
    const n = s.t.length;
    let axis = s.d ? "d" : "t";
    const xs = () => (axis === "d" ? s.d.map((v) => v / 1000) : s.t);
    const floors = data.floors;
    const blocks = data.blocks || [];
    const zoneOf = (h) => { if (h == null || !floors) return -1; let z = -1; for (let i = 0; i < 5; i++) if (h >= floors[i]) z = i; return z; };

    // smoothed pace (s/km) or speed (km/h)
    function smooth(arr, k) {
      const out = new Array(arr.length);
      for (let i = 0; i < arr.length; i++) {
        let sum = 0, c = 0;
        for (let j = Math.max(0, i - k); j <= Math.min(arr.length - 1, i + k); j++) if (arr[j] != null) { sum += arr[j]; c++; }
        out[i] = c ? sum / c : null;
      }
      return out;
    }
    const spd = s.spd ? smooth(s.spd, 4) : null;
    const channels = [];
    if (spd) {
      if (paceMode) channels.push({ key: "pace", title: "Pace", unit: "/km", color: () => tokens().sport[cat], vals: spd.map((v) => (v && v > 0.5 ? Math.min(1000 / v, 1200) : null)), fmt: pace, inverse: true });
      else channels.push({ key: "speed", title: "Speed", unit: "km/h", color: () => tokens().sport[cat], vals: spd.map((v) => (v != null ? Math.round(v * 36) / 10 : null)), fmt: (v) => num(v, 1) });
    }
    if (s.hr) channels.push({ key: "hr", title: "Heart rate", unit: "bpm", color: () => tokens().hr, vals: s.hr, fmt: (v) => num(v), zones: true });
    if (s.alt) channels.push({ key: "alt", title: "Elevation", unit: "m", color: () => tokens().elev, vals: s.alt, fmt: (v) => num(v), area: true });
    if (s.cad) channels.push({ key: "cad", title: "Cadence", unit: cat === "cycle" ? "rpm" : "spm", color: () => tokens().cad, vals: smooth(s.cad, 2), fmt: (v) => num(v), dots: true });
    if (s.pwr) channels.push({ key: "pwr", title: "Power", unit: "W", color: () => tokens().pwr, vals: smooth(s.pwr, 3), fmt: (v) => num(v) });
    // running dynamics from the activity file (watches that record them)
    const has = (k) => s[k] && s[k].some((v) => v != null && v > 0);
    const nz = (arr, f) => arr.map((v) => (v ? f(v) : null));
    if (has("gct")) channels.push({ key: "gct", title: "Ground contact", unit: "ms", color: () => tokens().cad, vals: smooth(nz(s.gct, (v) => v), 3), fmt: (v) => num(v) });
    if (has("vo")) channels.push({ key: "vo", title: "Vertical oscillation", unit: "cm", color: () => tokens().pwr, vals: smooth(nz(s.vo, (v) => v / 10), 3), fmt: (v) => num(v, 1) });
    if (has("vr")) channels.push({ key: "vr", title: "Vertical ratio", unit: "%", color: () => tokens().elev, vals: smooth(nz(s.vr, (v) => v), 3), fmt: (v) => num(v, 1) });
    if (has("step")) channels.push({ key: "step", title: "Stride length", unit: "m", color: () => tokens().hr, vals: smooth(nz(s.step, (v) => v / 1000), 3), fmt: (v) => num(v, 2) });
    if (data.wind && data.wind.some((v) => v != null)) {
      channels.push({ key: "wind", title: "Headwind", note: "minus means tailwind", unit: "km/h", color: () => tokens().wind, vals: data.wind,
                      fmt: (v) => (v == null ? "-" : (v > 0 ? "+" : "") + num(v, 0)), area: true, zero: true });
    }

    const wrap = document.getElementById("stream-charts");
    const entries = [];
    // the charts move together, but only the one under the pointer shows the tooltip (it lists every channel)
    let tipOwner = 0;
    function setTipOwner(ci) {
      if (ci === tipOwner) return;
      const prev = entries[tipOwner], cur = entries[ci];
      tipOwner = ci;
      if (prev && prev.chart) prev.chart.setOption({ tooltip: { showContent: false } });
      if (cur && cur.chart) cur.chart.setOption({ tooltip: { showContent: true } });
    }
    channels.forEach((ch, ci) => {
      const valid = ch.vals.filter((v) => v != null);
      const avg = valid.length ? valid.reduce((a, b) => a + b, 0) / valid.length : null;
      const title = document.createElement("p");
      title.className = "stream-title";
      title.innerHTML = `${esc(ch.title)} <span>average ${esc(ch.fmt(avg))} ${esc(ch.unit)}${ch.note ? ", " + esc(ch.note) : ""}</span>`;
      wrap.appendChild(title);
      const el = document.createElement("div");
      el.className = "chart";
      const last = ci === channels.length - 1;
      el.style.height = (last ? 150 : 124) + "px";
      wrap.appendChild(el);
      el.addEventListener("pointerenter", () => setTipOwner(ci));
      const e = chart(el, (t) => {
        const x = xs();
        const color = ch.color();
        const series = {
          type: "line", data: x.map((xv, i) => [xv, ch.vals[i]]), showSymbol: false, sampling: "lttb",
          lineStyle: { width: ch.dots ? 0 : 2, color }, itemStyle: { color }, connectNulls: false,
        };
        if (ch.dots) Object.assign(series, { type: "scatter", symbolSize: 3, itemStyle: { color, opacity: 0.6 } });
        if (ch.area) series.areaStyle = { color, opacity: 0.12 };
        if (ch.zero) series.markLine = { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: t.lineStrong, type: "solid", width: 1 }, data: [{ yAxis: 0 }] };
        if (ci === 0 && blocks.length) {
          // fast blocks the run classifier found, shaded behind the pace line
          const at = (sec) => { if (axis === "t") return sec; let i = 0; while (i < n - 1 && s.t[i] < sec) i++; return s.d ? s.d[i] / 1000 : sec; };
          series.markArea = { silent: true, data: blocks.map((b) => [{ xAxis: at(b.start), itemStyle: { color: t.group.workout, opacity: t.dark ? 0.2 : 0.14 } }, { xAxis: at(b.start + b.dur) }]) };
        }
        if (ch.zones && floors) {
          const top = Math.max(...valid, floors[4] + 10);
          series.markArea = { silent: true, data: floors.map((f, i) => [{ yAxis: f, itemStyle: { color: t.zone[i], opacity: t.dark ? 0.14 : 0.1 } }, { yAxis: i < 4 ? floors[i + 1] : top }]) };
        }
        const lo = Math.min(...valid), hi = Math.max(...valid);
        return {
          animation: false,
          textStyle: { fontFamily: t.font, color: t.ink2, fontSize: 12 },
          grid: { left: 54, right: 14, top: 8, bottom: last ? 26 : 6 },
          tooltip: Object.assign(tooltipBase(t), {
            showContent: ci === tipOwner,
            formatter: (ps) => {
              const i = ps[0].dataIndex;
              const head = (axis === "d" ? num(x[i], 2) + " km" : dur(x[i])) + (axis === "d" ? ", " + dur(s.t[i]) : s.d ? ", " + num(s.d[i] / 1000, 2) + " km" : "");
              return ttHtml(head, channels.map((c) => ({ color: c.color(), name: c.title, value: c.vals[i] == null ? "-" : c.fmt(c.vals[i]) + " " + c.unit })));
            },
          }),
          axisPointer: { link: [{ xAxisIndex: "all" }] },
          xAxis: { type: "value", min: x[0], max: x[n - 1], axisLine: { lineStyle: { color: t.lineStrong } }, axisTick: { show: false }, splitLine: { show: false },
                   axisLabel: { show: last, showMaxLabel: false, color: t.muted, formatter: (v) => (axis === "d" ? num(v, v < 10 ? 1 : 0) + " km" : dur(v)) } },
          yAxis: { type: "value", inverse: !!ch.inverse,
                   min: ch.key === "pace" ? Math.max(0, Math.floor((lo - 15) / 30) * 30) : ch.zero ? Math.min(-5, Math.floor(lo - 1)) : Math.floor(lo - (hi - lo) * 0.08),
                   max: ch.key === "pace" ? Math.ceil((hi + 15) / 30) * 30 : ch.zero ? Math.max(5, Math.ceil(hi + 1)) : Math.ceil(hi + (hi - lo) * 0.08), splitNumber: 3,
                   splitLine: { lineStyle: { color: t.grid } }, axisLabel: { color: t.muted, formatter: ch.fmt } },
          series: [series].concat(ch.key === "hr" && (data.marks || []).length ? [{
            // stretches where heart rate did not follow pace, shaded so they are easy to spot
            type: "line", data: [], silent: true,
            markArea: { silent: true, itemStyle: { color: t.muted, opacity: t.dark ? 0.25 : 0.18 },
                        data: data.marks.map(([a, b]) => { const at = (sec) => { if (axis === "t") return sec; let i = 0; while (i < n - 1 && s.t[i] < sec) i++; return s.d ? s.d[i] / 1000 : sec; }; return [{ xAxis: at(a) }, { xAxis: at(b) }]; }) },
          }] : []),
        };
      }, { group: "stream" });
      entries.push(e);
    });
    if (window.echarts) echarts.connect("stream");
    seg("axis", (a) => { axis = a; entries.forEach((e) => e.render()); echarts.connect("stream"); hookPointer(); });

    // split bars: faster split, longer bar
    const splits = data.splits || [];
    const paces = splits.map((sp) => sp.pace).filter(Boolean);
    if (paces.length) {
      const min = Math.min(...paces), max = Math.max(...paces);
      $$(".table-splits tbody tr").forEach((tr, i) => {
        const p = splits[i] && splits[i].pace;
        const w = p ? (max === min ? 0.7 : 0.25 + 0.75 * ((max - p) / (max - min))) : 0;
        const bar = $(".split-bar", tr);
        if (bar) bar.style.setProperty("--w", w.toFixed(3));
      });
    }

    // ---------- map ----------
    // Vector basemap (MapLibre + CARTO style) when configured, raster tiles (Leaflet) otherwise.
    const MAPCFG = (() => { const el = document.getElementById("map-config"); return el ? JSON.parse(el.textContent) : {}; })();
    const coordsIdx = [];
    if (s.lat && s.lon) for (let i = 0; i < n; i++) if (s.lat[i] != null && s.lon[i] != null) coordsIdx.push(i);
    const EMPTY = { type: "FeatureCollection", features: [] };
    let mapApi = null;

    function zoneSegments(t) {
      // consecutive points in the same HR zone become one coloured piece; [lon, lat]
      const segs = [];
      let cur = null, curZone = null;
      coordsIdx.forEach((i) => {
        const z = s.hr ? zoneOf(s.hr[i]) : -2;
        const pt = [s.lon[i], s.lat[i]];
        if (z !== curZone) { if (cur) cur.pts.push(pt); cur = { z, pts: [pt] }; segs.push(cur); curZone = z; }
        else cur.pts.push(pt);
      });
      return segs.map((sg) => ({ color: sg.z === -2 ? t.sport[cat] : sg.z === -1 ? t.zone[0] : t.zone[sg.z], pts: sg.pts }));
    }
    function kmMarks() {
      if (!s.d || !coordsIdx.length) return [];
      const total = s.d[n - 1] / 1000;
      const step = total > 60 ? 10 : total > 25 ? 5 : 1;
      const out = [];
      let next = step;
      coordsIdx.forEach((i) => {
        if (next < total - step * 0.3 && s.d[i] / 1000 >= next) { out.push({ km: next, lon: s.lon[i], lat: s.lat[i] }); next += step; }
      });
      return out;
    }
    function nearest(lon, lat) {
      const k = Math.cos((lat * Math.PI) / 180);
      let best = null, bd = Infinity;
      coordsIdx.forEach((i) => {
        const dx = (s.lon[i] - lon) * k, dy = s.lat[i] - lat, dd = dx * dx + dy * dy;
        if (dd < bd) { bd = dd; best = i; }
      });
      return best;
    }
    function idxRange(i0, i1) { return coordsIdx.filter((i) => i >= i0 && i <= i1); }
    function kmEl(km) { const d = document.createElement("div"); d.className = "km-mark"; d.textContent = km; d.title = km + " km"; return d; }

    function vectorMap(el, t, styleUrl, onFail) {
      const ml = window.maplibregl;
      const lons = coordsIdx.map((i) => s.lon[i]), lats = coordsIdx.map((i) => s.lat[i]);
      const bounds = [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]];
      let map, styleReady = false, gaveUp = false;
      const giveUp = () => { if (gaveUp) return; gaveUp = true; try { map && map.remove(); } catch (e) {} onFail(); };
      try {
        map = new ml.Map({
          container: el, style: styleUrl, bounds, fitBoundsOptions: { padding: 44, maxZoom: 16 },
          attributionControl: false, cooperativeGestures: true, dragRotate: false, pitchWithRotate: false, touchPitch: false,
          transformRequest: (url) => {
            // CARTO wants the key on style, tile, font and sprite requests alike
            if (MAPCFG.key && /basemaps\.cartocdn\.com/.test(url) && !/[?&]key=/.test(url)) {
              return { url: url + (url.indexOf("?") >= 0 ? "&" : "?") + "key=" + encodeURIComponent(MAPCFG.key) };
            }
            return { url };
          },
        });
      } catch (e) { giveUp(); return null; }
      map.touchZoomRotate.disableRotation();
      map.addControl(new ml.NavigationControl({ showCompass: false }), "top-left");
      map.addControl(new ml.FullscreenControl(), "top-left");
      map.on("style.load", () => { styleReady = true; });
      map.on("error", () => { if (!styleReady) giveUp(); });  // style missing or rejected: fall back
      map.on("load", () => {
        const hasAttr = Object.values(map.getStyle().sources || {}).some((src) => src.attribution);
        map.addControl(new ml.AttributionControl({ compact: true, customAttribution: hasAttr ? undefined : MAPCFG.attribution }), "bottom-right");
        const segs = zoneSegments(t);
        const first = coordsIdx[0], last = coordsIdx[coordsIdx.length - 1];
        map.addSource("route", { type: "geojson", data: { type: "FeatureCollection", features: segs.map((sg) => ({
          type: "Feature", properties: { color: sg.color }, geometry: { type: "LineString", coordinates: sg.pts } })) } });
        map.addSource("split", { type: "geojson", data: EMPTY });
        map.addSource("cursor", { type: "geojson", data: EMPTY });
        map.addSource("ends", { type: "geojson", data: { type: "FeatureCollection", features: [
          { type: "Feature", properties: { fill: t.ink, stroke: t.surface, name: "Start" }, geometry: { type: "Point", coordinates: [s.lon[first], s.lat[first]] } },
          { type: "Feature", properties: { fill: t.surface, stroke: t.ink, name: "Finish" }, geometry: { type: "Point", coordinates: [s.lon[last], s.lat[last]] } },
        ] } });
        const w = (a, b) => ["interpolate", ["linear"], ["zoom"], 10, a, 16, b];
        const round = { "line-join": "round", "line-cap": "round" };
        map.addLayer({ id: "route-casing", type: "line", source: "route", layout: round, paint: { "line-color": t.surface, "line-width": w(6, 11), "line-opacity": 0.95 } });
        map.addLayer({ id: "split-glow", type: "line", source: "split", layout: round, paint: { "line-color": t.ink, "line-width": w(11, 18), "line-opacity": 0.3 } });
        map.addLayer({ id: "route-line", type: "line", source: "route", layout: round, paint: { "line-color": ["get", "color"], "line-width": w(3.2, 6) } });
        map.addLayer({ id: "route-hit", type: "line", source: "route", layout: round, paint: { "line-color": "#000", "line-width": 22, "line-opacity": 0 } });
        map.addLayer({ id: "ends", type: "circle", source: "ends", paint: { "circle-radius": 7, "circle-color": ["get", "fill"], "circle-stroke-color": ["get", "stroke"], "circle-stroke-width": 3 } });
        map.addLayer({ id: "cursor", type: "circle", source: "cursor", paint: { "circle-radius": 8, "circle-color": t.sport[cat], "circle-stroke-color": t.surface, "circle-stroke-width": 3 } });
        kmMarks().forEach((m) => new ml.Marker({ element: kmEl(m.km) }).setLngLat([m.lon, m.lat]).addTo(map));
        map.on("mousemove", "route-hit", (e) => { map.getCanvas().style.cursor = "crosshair"; const i = nearest(e.lngLat.lng, e.lngLat.lat); if (i != null) followFromMap(i); });
        map.on("mouseleave", "route-hit", () => { map.getCanvas().style.cursor = ""; leaveFromMap(); });
      });
      const src = (id) => map.getSource && map.isStyleLoaded() && map.getSource(id);
      return {
        setCursor(i) { const c = src("cursor"); if (c) c.setData({ type: "Feature", geometry: { type: "Point", coordinates: [s.lon[i], s.lat[i]] } }); },
        clearCursor() { const c = src("cursor"); if (c) c.setData(EMPTY); },
        highlight(i0, i1) {
          const c = src("split"); const idx = idxRange(i0, i1);
          if (c && idx.length > 1) c.setData({ type: "Feature", geometry: { type: "LineString", coordinates: idx.map((i) => [s.lon[i], s.lat[i]]) } });
        },
        clearHighlight() { const c = src("split"); if (c) c.setData(EMPTY); },
        destroy() { try { map.remove(); } catch (e) {} },
      };
    }

    function rasterMap(el, t) {
      if (!window.L) return null;
      const map = L.map(el, { scrollWheelZoom: false, zoomControl: true });
      L.tileLayer(MAPCFG.raster || "https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19, referrerPolicy: "strict-origin-when-cross-origin", attribution: MAPCFG.raster_attribution || '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      }).addTo(map);
      const ll = (p) => [p[1], p[0]];
      const segs = zoneSegments(t);
      const all = [];
      segs.forEach((sg) => { L.polyline(sg.pts.map(ll), { color: t.surface, weight: 8, opacity: 0.95, lineCap: "round", lineJoin: "round" }).addTo(map); all.push(...sg.pts.map(ll)); });
      const glow = L.polyline([], { color: t.ink, weight: 14, opacity: 0.3, lineCap: "round", lineJoin: "round" }).addTo(map);
      segs.forEach((sg) => L.polyline(sg.pts.map(ll), { color: sg.color, weight: 4.5, opacity: 1, lineCap: "round", lineJoin: "round" }).addTo(map));
      map.fitBounds(L.latLngBounds(all), { padding: [30, 30] });
      L.circleMarker(all[0], { radius: 7, color: t.surface, weight: 3, fillColor: t.ink, fillOpacity: 1 }).addTo(map).bindTooltip("Start");
      L.circleMarker(all[all.length - 1], { radius: 7, color: t.ink, weight: 3, fillColor: t.surface, fillOpacity: 1 }).addTo(map).bindTooltip("Finish");
      kmMarks().forEach((m) => L.marker([m.lat, m.lon], { icon: L.divIcon({ className: "", html: kmEl(m.km).outerHTML, iconSize: [20, 20] }), interactive: false }).addTo(map));
      const cursor = L.circleMarker(all[0], { radius: 8, color: t.surface, weight: 3, fillColor: t.sport[cat], fillOpacity: 1, interactive: false });
      return {
        setCursor(i) { cursor.setLatLng([s.lat[i], s.lon[i]]); if (!map.hasLayer(cursor)) cursor.addTo(map); },
        clearCursor() { if (map.hasLayer(cursor)) map.removeLayer(cursor); },
        highlight(i0, i1) { glow.setLatLngs(idxRange(i0, i1).map((i) => [s.lat[i], s.lon[i]])); },
        clearHighlight() { glow.setLatLngs([]); },
        destroy() { map.remove(); },
      };
    }

    function drawMap() {
      const el = document.getElementById("map");
      if (!el || !coordsIdx.length) return;
      if (mapApi) { mapApi.destroy(); mapApi = null; }
      const t = tokens();
      const style = t.dark && MAPCFG.vector_dark ? MAPCFG.vector_dark : MAPCFG.vector;
      const raster = () => { mapApi = rasterMap(el, t); };
      if (style && window.maplibregl) {
        mapApi = vectorMap(el, t, style, () => {
          // a dark style the key does not cover: use the light style, then plain tiles
          if (style !== MAPCFG.vector && MAPCFG.vector) mapApi = vectorMap(el, t, MAPCFG.vector, raster);
          else raster();
        });
      } else raster();
    }
    drawMap();

    // route hover -> charts (the charts then move the cursor and the split row)
    function followFromMap(i) {
      setTipOwner(0);
      const c = entries[0] && entries[0].chart;
      if (c) c.dispatchAction({ type: "showTip", seriesIndex: 0, dataIndex: i });
      else if (mapApi) mapApi.setCursor(i);
    }
    function leaveFromMap() {
      entries.forEach((e) => e && e.chart && e.chart.dispatchAction({ type: "hideTip" }));
      if (mapApi) mapApi.clearCursor();
    }

    // chart hover -> map cursor + split row
    const splitEnds = splits.map((sp) => sp.t_end);
    let hot = null;
    function hookPointer() {
      entries.forEach((e) => {
        if (!e || !e.chart) return;
        e.chart.on("updateAxisPointer", (ev) => {
          const info = ev.axesInfo && ev.axesInfo[0];
          if (!info) return;
          const x = xs();
          let lo = 0, hi = n - 1;
          while (lo < hi) { const mid = (lo + hi) >> 1; if (x[mid] < info.value) lo = mid + 1; else hi = mid; }
          const i = lo;
          if (mapApi && s.lat && s.lat[i] != null) mapApi.setCursor(i);
          const k = splitEnds.findIndex((te) => s.t[i] <= te);
          const row = k >= 0 ? $(`.table-splits tr[data-split="${k}"]`) : null;
          if (hot && hot !== row) hot.classList.remove("is-hot");
          if (row) { row.classList.add("is-hot"); hot = row; }
        });
        e.chart.getZr().on("globalout", () => { if (mapApi) mapApi.clearCursor(); });
      });
    }
    hookPointer();

    // split row hover -> that km lights up on the map
    $$(".table-splits tbody tr").forEach((tr) => {
      const k = Number(tr.dataset.split);
      tr.addEventListener("mouseenter", () => {
        if (!mapApi || !splits[k]) return;
        const t0 = k > 0 ? splits[k - 1].t_end : s.t[0], t1 = splits[k].t_end;
        let i0 = 0; while (i0 < n - 1 && s.t[i0] < t0) i0++;
        let i1 = i0; while (i1 < n - 1 && s.t[i1] < t1) i1++;
        mapApi.highlight(Math.max(0, i0 - 1), i1);
      });
      tr.addEventListener("mouseleave", () => mapApi && mapApi.clearHighlight());
    });
    window.__afterRerender = () => { drawMap(); echarts.connect("stream"); hookPointer(); };
  };

  // month by month and day by day per sport: every month and every day in the range, never merged
  function monthDayBySport(data) {
    const shadow = (t) => ({ type: "shadow", shadowStyle: { color: t.dark ? "rgba(255,255,255,.04)" : "rgba(0,0,0,.035)" } });
    function stackedOption(t, labels, series, m, tick, title, zoom) {
      const keys = data.sports.filter((k) => series[k]);
      const fmt = (v) => (m === "km" ? num(v, 1) + " km" : hm(v));
      return Object.assign(base(t), {
        legend: legend(t, keys.map((k) => SPORT_LABEL[k])),
        grid: { left: 6, right: 14, top: 30, bottom: zoom && zoom.has() ? 50 : 6, containLabel: true },
        xAxis: axisCat(t, labels, tick),
        yAxis: axisVal(t, (v) => (m === "km" ? compact(v) + " km" : v + " h")),
        dataZoom: zoom ? zoom.option(t) : undefined,
        tooltip: Object.assign(tooltipBase(t), {
          axisPointer: shadow(t),
          formatter: (ps) => {
            const rows = ps.filter((p) => p.value > 0).reverse().map((p) => ({ color: p.color, name: p.seriesName, value: fmt(p.value) }));
            if (!rows.length) return ttHtml(title(ps[0].axisValue), [{ name: zoom ? "Rest day" : "Nothing recorded", value: "" }]);
            if (rows.length > 1) rows.push({ name: "Total", value: fmt(ps.reduce((a, p) => a + (p.value || 0), 0)) });
            return ttHtml(title(ps[0].axisValue), rows);
          },
        }),
        series: stackedBars(t, keys, series, t.sport, SPORT_LABEL).map((x) => (zoom ? Object.assign(x, { barMaxWidth: 14 }) : x)),
      });
    }
    let mMetric = "hours", dMetric = "hours";
    const pm = chart("chart-p-monthly", (t) => stackedOption(t, data.monthly.months, mMetric === "km" ? data.monthly.km : data.monthly.hours, mMetric, monthTick, monthLabel));
    seg("pmonthly", (m) => { mMetric = m; pm && pm.render(); });
    const dEl = document.getElementById("chart-p-daily");
    let pd = null;
    if (dEl) {
      const zoom = zoomState(data.daily.days.length, dEl);
      pd = chart(dEl, (t) => stackedOption(t, data.daily.days, dMetric === "km" ? data.daily.km : data.daily.hours, dMetric, shortDate, dayLabel, zoom), { after: zoom.after });
    }
    seg("pdaily", (m) => { dMetric = m; pd && pd.render(); });
  }

  PAGES.personal = function (data) {
    monthDayBySport(data);

    chart("chart-weight", (t) => weightOption(t, data.weights.map((w) => [w[0], w[1]])));
  };

  function weightOption(t, pts) {
    // a single weigh-in still gets a sensible window around it
    const one = pts.length === 1 ? parseDate(pts[0][0]).getTime() : null;
    return Object.assign(base(t), {
      grid: { left: 6, right: 14, top: 14, bottom: 6, containLabel: true },
      xAxis: axisTime(t, one ? { min: one - 14 * 86400000, max: one + 14 * 86400000 } : {}),
      yAxis: axisVal(t, (v) => v + " kg", { min: (e) => Math.floor(e.min - 2), max: (e) => Math.ceil(e.max + 2), minInterval: 1 }),
      tooltip: Object.assign(tooltipBase(t), { formatter: (ps) => ttHtml(dayLabel(ps[0].value[0]), [{ color: t.ink, name: "Weight", value: num(ps[0].value[1], 1) + " kg" }]) }),
      series: [{ type: "line", data: pts, symbol: "circle", symbolSize: 5, lineStyle: { width: 2, color: t.ink }, itemStyle: { color: t.ink } }],
    });
  }

  PAGES.health = function (data) {
    let range = 90;
    const last = (() => {
      const all = [].concat(data.daily.dates, data.sleep.dates, data.hrv.dates);
      return all.length ? all.sort().slice(-1)[0] : null;
    })();
    function cut(dates) {
      if (!range || !last) return 0;
      const lim = parseDate(last); lim.setDate(lim.getDate() - range + 1);
      const iso = `${lim.getFullYear()}-${pad(lim.getMonth() + 1)}-${pad(lim.getDate())}`;
      let i = 0; while (i < dates.length && dates[i] < iso) i++;
      return i;
    }
    const weekly = () => !range || range > 120;
    function pairs(dates, vals) { const i0 = cut(dates); const out = []; for (let i = i0; i < dates.length; i++) out.push([dates[i], vals[i]]); return out; }
    function weekAgg(pts, fn) {
      // [[iso, v]] -> weekly (Monday) mean
      const m = new Map();
      pts.forEach(([d, v]) => {
        if (v == null) return;
        const dt = parseDate(d); dt.setDate(dt.getDate() - ((dt.getDay() + 6) % 7));
        const k = `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}`;
        if (!m.has(k)) m.set(k, []);
        m.get(k).push(v);
      });
      return Array.from(m.entries()).map(([k, arr]) => [k, fn ? fn(arr) : arr.reduce((a, b) => a + b, 0) / arr.length]);
    }
    const note = $("[data-agg-note]");

    function lineWithAvg(t, pts, name, unit, color, digits, extra) {
      const avg = rolling(pts, 7);
      return Object.assign(base(t), {
        grid: { left: 6, right: 14, top: 30, bottom: 6, containLabel: true },
        legend: legend(t, [name, "7-day average"]),
        xAxis: axisTime(t),
        yAxis: axisVal(t, (v) => compact(v), { scale: true }),
        tooltip: Object.assign(tooltipBase(t), { formatter: (ps) => ttHtml(dayLabel(ps[0].value[0]), ps.map((p) => ({ color: p.color, name: p.seriesName, value: p.value[1] == null ? "-" : num(p.value[1], digits) + (unit ? " " + unit : "") }))) }),
        series: [
          { name, type: "line", data: pts, showSymbol: false, lineStyle: { width: 1.5, color, opacity: 0.35 }, itemStyle: { color } },
          { name: "7-day average", type: "line", data: avg, showSymbol: false, smooth: 0.3, lineStyle: { width: 2, color: t.ink }, itemStyle: { color: t.ink } },
        ].concat(extra || []),
      });
    }

    const charts = [];
    charts.push(chart("chart-sleep", (t) => {
      const S = data.sleep;
      const i0 = cut(S.dates);
      const stages = [["deep_s", "Deep", t.dark ? "#3987e5" : "#256abf"], ["light_s", "Light", t.dark ? "#1c5cab" : "#86b6ef"], ["rem_s", "REM", t.dark ? "#9085e9" : "#6250d6"], ["awake_s", "Awake", t.dark ? "#d55181" : "#e87ba4"]];
      let dates = S.dates.slice(i0);
      let vals = {};
      stages.forEach(([k]) => (vals[k] = S[k].slice(i0).map((v) => (v == null ? 0 : Math.round((v / 3600) * 100) / 100))));
      if (weekly()) {
        const agg = {};
        stages.forEach(([k]) => { agg[k] = weekAgg(dates.map((d, i) => [d, vals[k][i]])); });
        dates = agg.deep_s.map((r) => r[0]);
        stages.forEach(([k]) => (vals[k] = agg[k].map((r) => Math.round(r[1] * 100) / 100)));
        if (note) note.textContent = "Weekly average per night";
      } else if (note) note.textContent = "Hours per night";
      const colors = {}, names = {};
      stages.forEach(([k, nm, c]) => { colors[k] = c; names[k] = nm; });
      return Object.assign(base(t), {
        legend: legend(t, stages.map((s) => s[1])),
        xAxis: axisCat(t, dates, shortDate),
        yAxis: axisVal(t, (v) => v + " h"),
        tooltip: Object.assign(tooltipBase(t), {
          axisPointer: { type: "shadow", shadowStyle: { color: t.dark ? "rgba(255,255,255,.04)" : "rgba(0,0,0,.035)" } },
          formatter: (ps) => {
            const total = ps.filter((p) => p.seriesName !== "Awake").reduce((a, p) => a + (p.value || 0), 0);
            return ttHtml((weekly() ? "Week of " : "") + dayLabel(ps[0].axisValue), ps.slice().reverse().map((p) => ({ color: p.color, name: p.seriesName, value: hm(p.value || 0) })).concat([{ name: "Asleep", value: hm(total) }]));
          },
        }),
        series: stackedBars(t, stages.map((s) => s[0]), vals, colors, names),
      });
    }));
    charts.push(chart("chart-sleep-score", (t) => lineWithAvg(t, pairs(data.sleep.dates, data.sleep.score), "Score", "", t.sport.run, 0)));
    const at = (dates, vals) => { const m = new Map(); dates.forEach((d, i) => m.set(d, vals[i])); return m; };
    charts.push(chart("chart-hr", (t) => {
      const Dd = data.daily;
      const i0 = cut(Dd.dates);
      const d = Dd.dates.slice(i0), lo = Dd.min_hr.slice(i0), hi = Dd.max_hr.slice(i0), rhr = Dd.resting_hr.slice(i0);
      const sleep = pairs(data.sleep.dates, data.sleep.avg_hr);
      const mLo = at(d, lo), mHi = at(d, hi), mR = at(d, rhr), mS = new Map(sleep);
      return Object.assign(base(t), {
        grid: { left: 6, right: 14, top: 30, bottom: 6, containLabel: true },
        legend: legend(t, ["Resting", "Average asleep", "Lowest to highest"]),
        xAxis: axisTime(t),
        yAxis: axisVal(t, (v) => v + " bpm", { scale: true }),
        tooltip: Object.assign(tooltipBase(t), { formatter: (ps) => {
          const day = ps[0].value[0];
          const v = (m) => (m.get(day) != null ? num(m.get(day)) + " bpm" : "-");
          return ttHtml(dayLabel(day), [
            { color: t.hr, name: "Resting", value: v(mR) },
            { color: t.cad, name: "Average asleep", value: v(mS) },
            { name: "Lowest", value: v(mLo) },
            { name: "Highest", value: v(mHi) },
          ]);
        } }),
        series: [
          { name: "band-base", type: "line", stack: "hrband", data: d.map((x, i) => [x, lo[i]]), showSymbol: false, lineStyle: { opacity: 0 }, silent: true, tooltip: { show: false } },
          { name: "Lowest to highest", type: "line", stack: "hrband", data: d.map((x, i) => [x, hi[i] != null && lo[i] != null ? hi[i] - lo[i] : null]), showSymbol: false,
            lineStyle: { opacity: 0 }, areaStyle: { color: t.hr, opacity: t.dark ? 0.16 : 0.11 }, itemStyle: { color: t.hr }, silent: true },
          { name: "Average asleep", type: "line", data: sleep, showSymbol: false, lineStyle: { width: 1.5, color: t.cad }, itemStyle: { color: t.cad } },
          { name: "Resting", type: "line", data: d.map((x, i) => [x, rhr[i]]), showSymbol: false, lineStyle: { width: 2.5, color: t.hr }, itemStyle: { color: t.hr } },
        ],
      });
    }));
    charts.push(chart("chart-sleep-need", (t) => {
      const S = data.sleep;
      const i0 = cut(S.dates);
      let rows = S.dates.slice(i0).map((d, i) => [d, S.total_s[i0 + i] != null ? S.total_s[i0 + i] / 3600 : null, S.need_min[i0 + i] != null ? S.need_min[i0 + i] / 60 : null]);
      const isWeekly = weekly();
      if (isWeekly) {
        const a = new Map(weekAgg(rows.map((r) => [r[0], r[1]]))), b = new Map(weekAgg(rows.map((r) => [r[0], r[2]])));
        rows = Array.from(new Set([...a.keys(), ...b.keys()])).sort().map((k) => [k, a.get(k) ?? null, b.get(k) ?? null]);
      }
      return Object.assign(base(t), {
        grid: { left: 6, right: 14, top: 30, bottom: 6, containLabel: true },
        legend: legend(t, ["Slept", "Sleep need"]),
        xAxis: axisCat(t, rows.map((r) => r[0]), shortDate),
        yAxis: axisVal(t, (v) => v + " h", { min: 0 }),
        tooltip: Object.assign(tooltipBase(t), { axisPointer: { type: "shadow", shadowStyle: { color: t.dark ? "rgba(255,255,255,.04)" : "rgba(0,0,0,.035)" } },
          formatter: (ps) => { const r = rows[ps[0].dataIndex];
            const diff = r[1] != null && r[2] != null ? r[1] - r[2] : null;
            return ttHtml((isWeekly ? "Week of " : "") + dayLabel(r[0]), [
              { color: t.ramp[3], name: "Slept", value: r[1] != null ? hm(r[1]) : "-" },
              { color: t.ink, name: "Need", value: r[2] != null ? hm(r[2]) : "-" },
              { name: diff == null ? "" : diff < 0 ? "Short by" : "Over by", value: diff == null ? "" : hm(Math.abs(diff)) },
            ]); } }),
        series: [
          { name: "Slept", type: "bar", data: rows.map((r) => r[1] != null ? Math.round(r[1] * 100) / 100 : null), barMaxWidth: 20, itemStyle: { color: t.ramp[3], borderRadius: [4, 4, 0, 0] } },
          { name: "Sleep need", type: "line", step: "middle", data: rows.map((r) => r[2] != null ? Math.round(r[2] * 100) / 100 : null), showSymbol: false, connectNulls: true, lineStyle: { width: 2, color: t.ink }, itemStyle: { color: t.ink } },
        ],
      });
    }));
    charts.push(chart("chart-spo2", (t) => {
      const avg = pairs(data.daily.dates, data.daily.spo2_avg), low = pairs(data.daily.dates, data.daily.spo2_min);
      const all = avg.concat(low).map((p) => p[1]).filter((v) => v != null);
      return Object.assign(base(t), {
        grid: { left: 6, right: 14, top: 30, bottom: 6, containLabel: true },
        legend: legend(t, ["Daily average", "Lowest reading"]),
        xAxis: axisTime(t),
        yAxis: axisVal(t, (v) => v + "%", { min: all.length ? Math.max(70, Math.floor(Math.min(...all) - 2)) : 80, max: 100 }),
        tooltip: Object.assign(tooltipBase(t), { formatter: (ps) => ttHtml(dayLabel(ps[0].value[0]), ps.map((p) => ({ color: p.color, name: p.seriesName, value: p.value[1] == null ? "-" : num(p.value[1]) + "%" }))) }),
        series: [
          { name: "Lowest reading", type: "line", data: low, showSymbol: false, connectNulls: false, lineStyle: { width: 1.5, color: t.muted }, itemStyle: { color: t.muted } },
          { name: "Daily average", type: "line", data: avg, showSymbol: false, connectNulls: false, lineStyle: { width: 2.5, color: t.sport.run }, itemStyle: { color: t.sport.run } },
        ],
      });
    }));
    charts.push(chart("chart-hrv", (t) => {
      const H = data.hrv;
      const i0 = cut(H.dates);
      const d = H.dates.slice(i0);
      const low = H.baseline_low.slice(i0), high = H.baseline_high.slice(i0);
      return Object.assign(base(t), {
        grid: { left: 6, right: 14, top: 30, bottom: 6, containLabel: true },
        legend: legend(t, ["Last night", "Weekly average", "Your normal range"]),
        xAxis: axisTime(t),
        yAxis: axisVal(t, (v) => v + " ms", { scale: true }),
        tooltip: Object.assign(tooltipBase(t), { formatter: (ps) => {
          const i = ps[0].dataIndex;
          return ttHtml(dayLabel(d[i]), [
            { color: t.sport.cycle, name: "Last night", value: num(H.last_night[i0 + i]) + " ms" },
            { color: t.ink, name: "Weekly average", value: num(H.weekly_avg[i0 + i]) + " ms" },
            { name: "Normal range", value: low[i] != null ? `${num(low[i])} to ${num(high[i])} ms` : "-" },
          ]);
        } }),
        series: [
          { name: "band-base", type: "line", stack: "band", data: d.map((x, i) => [x, low[i]]), showSymbol: false, lineStyle: { opacity: 0 }, silent: true, tooltip: { show: false } },
          { name: "Your normal range", type: "line", stack: "band", data: d.map((x, i) => [x, high[i] != null && low[i] != null ? high[i] - low[i] : null]), showSymbol: false,
            lineStyle: { opacity: 0 }, areaStyle: { color: t.sport.cycle, opacity: 0.13 }, itemStyle: { color: t.sport.cycle }, silent: true },
          { name: "Last night", type: "line", data: d.map((x, i) => [x, H.last_night[i0 + i]]), showSymbol: false, lineStyle: { width: 1.5, color: t.sport.cycle }, itemStyle: { color: t.sport.cycle } },
          { name: "Weekly average", type: "line", data: d.map((x, i) => [x, H.weekly_avg[i0 + i]]), showSymbol: false, smooth: 0.3, lineStyle: { width: 2, color: t.ink }, itemStyle: { color: t.ink } },
        ],
      });
    }));
    charts.push(chart("chart-vo2", (t) => {
      const i0 = cut(data.vo2.running.map((r) => r[0]));
      const pts = data.vo2.running.slice(i0);
      return Object.assign(base(t), {
        grid: { left: 6, right: 44, top: 14, bottom: 6, containLabel: true },
        xAxis: axisTime(t),
        yAxis: axisVal(t, (v) => v, { min: (v) => Math.floor(v.min - 1), max: (v) => Math.ceil(v.max + 1), minInterval: 1 }),
        tooltip: Object.assign(tooltipBase(t), { formatter: (ps) => ttHtml(dayLabel(ps[0].value[0]), [{ color: t.sport.run, name: "VO2max", value: num(ps[0].value[1], 1) }]) }),
        series: [{ type: "line", step: "end", data: pts, showSymbol: false, lineStyle: { width: 2, color: t.sport.run }, itemStyle: { color: t.sport.run },
                   areaStyle: { color: t.sport.run, opacity: 0.08 },
                   endLabel: { show: true, color: t.ink, fontWeight: 650, formatter: (p) => num(p.value[1], 1) } }],
      });
    }));
    charts.push(chart("chart-stress", (t) => lineWithAvg(t, pairs(data.daily.dates, data.daily.avg_stress), "Stress", "", t.sport.walk, 0)));
    charts.push(chart("chart-bb", (t) => {
      const D = data.daily;
      const i0 = cut(D.dates);
      const d = D.dates.slice(i0), lo = D.bb_min.slice(i0), hi = D.bb_max.slice(i0);
      return Object.assign(base(t), {
        grid: { left: 6, right: 14, top: 30, bottom: 6, containLabel: true },
        legend: legend(t, ["High", "Low"]),
        xAxis: axisTime(t),
        yAxis: axisVal(t, (v) => v, { min: 0, max: 100 }),
        tooltip: Object.assign(tooltipBase(t), { formatter: (ps) => { const i = ps[0].dataIndex; return ttHtml(dayLabel(d[i]), [{ color: t.sport.cycle, name: "High", value: num(hi[i]) }, { color: t.muted, name: "Low", value: num(lo[i]) }]); } }),
        series: [
          { name: "Low", type: "line", stack: "bb", data: d.map((x, i) => [x, lo[i]]), showSymbol: false, lineStyle: { width: 1.5, color: t.muted }, itemStyle: { color: t.muted } },
          { name: "range", type: "line", stack: "bb", data: d.map((x, i) => [x, hi[i] != null && lo[i] != null ? hi[i] - lo[i] : null]), showSymbol: false, lineStyle: { opacity: 0 },
            areaStyle: { color: t.sport.cycle, opacity: 0.16 }, silent: true, tooltip: { show: false } },
          { name: "High", type: "line", data: d.map((x, i) => [x, hi[i]]), showSymbol: false, lineStyle: { width: 2, color: t.sport.cycle }, itemStyle: { color: t.sport.cycle } },
        ],
      });
    }));
    charts.push(chart("chart-steps", (t) => {
      let pts = pairs(data.daily.dates, data.daily.steps);
      let goals = pairs(data.daily.dates, data.daily.steps_goal);
      const isWeekly = weekly();
      if (isWeekly) { pts = weekAgg(pts).map((r) => [r[0], Math.round(r[1])]); goals = weekAgg(goals).map((r) => [r[0], Math.round(r[1])]); }
      const gm = new Map(goals);
      const goal = pts.map((p) => (gm.has(p[0]) ? gm.get(p[0]) : null));
      return Object.assign(base(t), {
        grid: { left: 6, right: 14, top: 14, bottom: 6, containLabel: true },
        xAxis: axisCat(t, pts.map((p) => p[0]), shortDate),
        yAxis: axisVal(t),
        tooltip: Object.assign(tooltipBase(t), { axisPointer: { type: "shadow", shadowStyle: { color: "rgba(0,0,0,.03)" } },
                  formatter: (ps) => { const i = ps[0].dataIndex; return ttHtml((isWeekly ? "Week of " : "") + dayLabel(ps[0].axisValue), [{ color: t.sport.walk, name: isWeekly ? "Steps a day" : "Steps", value: num(pts[i][1]) }, { color: t.ink, name: "Goal", value: goal[i] != null ? num(goal[i]) : "-" }]); } }),
        series: [{ type: "bar", data: pts.map((p) => p[1]), barMaxWidth: 24, itemStyle: { color: t.sport.walk, borderRadius: [4, 4, 0, 0] } },
                 { name: "Goal", type: "line", step: "middle", data: goal, showSymbol: false, connectNulls: true, lineStyle: { width: 2, color: t.ink }, itemStyle: { color: t.ink } }],
      });
    }));
    charts.push(chart("chart-im", (t) => {
      const D = data.daily;
      const mod = weekAgg(pairs(D.dates, D.im_moderate), (a) => a.reduce((x, y) => x + y, 0));
      const vig = weekAgg(pairs(D.dates, D.im_vigorous), (a) => a.reduce((x, y) => x + y * 2, 0));
      const weeks = mod.map((r) => r[0]);
      const vmap = new Map(vig);
      return Object.assign(base(t), {
        legend: legend(t, ["Moderate", "Vigorous (counts double)"]),
        grid: { left: 6, right: 58, top: 30, bottom: 6, containLabel: true },
        xAxis: axisCat(t, weeks, shortDate),
        yAxis: axisVal(t, (v) => v + " min"),
        tooltip: Object.assign(tooltipBase(t), { axisPointer: { type: "shadow", shadowStyle: { color: "rgba(0,0,0,.03)" } },
                  formatter: (ps) => ttHtml("Week of " + dayLabel(ps[0].axisValue), ps.map((p) => ({ color: p.color, name: p.seriesName, value: num(p.value) + " min" }))) }),
        series: stackedBars(t, ["mod", "vig"], { mod: mod.map((r) => r[1]), vig: weeks.map((w) => vmap.get(w) || 0) },
                            { mod: t.ramp[1], vig: t.ramp[4] }, { mod: "Moderate", vig: "Vigorous (counts double)" })
          .concat([{ type: "line", data: [], markLine: { silent: true, symbol: "none", label: { formatter: "150 min", color: t.ink2, position: "end" },
                     lineStyle: { color: t.ink2, type: "solid", width: 1 }, data: [{ yAxis: 150 }] } }]),
      });
    }));
    charts.push(chart("chart-resp", (t) => {
      const awake = pairs(data.daily.dates, data.daily.resp_avg), asleep = pairs(data.sleep.dates, data.sleep.resp_avg);
      const mA = new Map(awake), mS = new Map(asleep);
      return Object.assign(base(t), {
        grid: { left: 6, right: 14, top: 30, bottom: 6, containLabel: true },
        legend: legend(t, ["Awake", "Asleep"]),
        xAxis: axisTime(t),
        yAxis: axisVal(t, (v) => v, { scale: true }),
        tooltip: Object.assign(tooltipBase(t), { formatter: (ps) => { const day = ps[0].value[0];
          return ttHtml(dayLabel(day), [
            { color: t.sport.cycle, name: "Awake", value: mA.get(day) != null ? num(mA.get(day), 1) + " brpm" : "-" },
            { color: t.cad, name: "Asleep", value: mS.get(day) != null ? num(mS.get(day), 1) + " brpm" : "-" },
          ]); } }),
        series: [
          { name: "Awake", type: "line", data: awake, showSymbol: false, lineStyle: { width: 2, color: t.sport.cycle }, itemStyle: { color: t.sport.cycle } },
          { name: "Asleep", type: "line", data: asleep, showSymbol: false, lineStyle: { width: 2, color: t.cad }, itemStyle: { color: t.cad } },
        ],
      });
    }));
    // daily bars that switch to weekly averages over long ranges, same as sleep and steps
    function dailyBars(t, keys, names, colors, digits, unitFmt, opts) {
      opts = opts || {};
      const Dd = data.daily;
      const i0 = cut(Dd.dates);
      let dates = Dd.dates.slice(i0);
      let vals = {};
      keys.forEach((k) => (vals[k] = Dd[k].slice(i0).map((v) => (v == null ? null : (opts.scale ? v * opts.scale : v)))));
      const isWeekly = weekly();
      if (isWeekly) {
        const agg = {};
        keys.forEach((k) => (agg[k] = new Map(weekAgg(dates.map((d, i) => [d, vals[k][i]])))));
        const wk = Array.from(new Set([].concat(...keys.map((k) => Array.from(agg[k].keys()))))).sort();
        keys.forEach((k) => (vals[k] = wk.map((w) => (agg[k].has(w) ? agg[k].get(w) : null))));
        dates = wk;
      }
      keys.forEach((k) => (vals[k] = vals[k].map((v) => (v == null ? null : Math.round(v * Math.pow(10, digits)) / Math.pow(10, digits)))));
      const series = keys.length > 1 || opts.stack ? stackedBars(t, keys, vals, colors, names)
        : [{ name: names[keys[0]], type: "bar", data: vals[keys[0]], barMaxWidth: 20, itemStyle: { color: colors[keys[0]], borderRadius: [4, 4, 0, 0] } }];
      series.forEach((x) => (x.barMaxWidth = 20));
      return Object.assign(base(t), {
        grid: { left: 6, right: 14, top: keys.length > 1 ? 30 : 14, bottom: 6, containLabel: true },
        legend: keys.length > 1 ? legend(t, keys.map((k) => names[k])) : undefined,
        xAxis: axisCat(t, dates, shortDate),
        yAxis: axisVal(t, opts.axisFmt),
        tooltip: Object.assign(tooltipBase(t), { axisPointer: { type: "shadow", shadowStyle: { color: t.dark ? "rgba(255,255,255,.04)" : "rgba(0,0,0,.035)" } },
          formatter: (ps) => {
            const i = ps[0].dataIndex;
            const rows = keys.slice().reverse().map((k) => ({ color: colors[k], name: names[k], value: vals[k][i] == null ? "-" : unitFmt(vals[k][i]) }));
            if (opts.total) rows.push({ name: "Total", value: unitFmt(keys.reduce((a, k) => a + (vals[k][i] || 0), 0)) });
            if (opts.extra) rows.push(...opts.extra(dates[i], isWeekly));
            return ttHtml((isWeekly ? (opts.weekLabel || "Week of ") : "") + dayLabel(dates[i]), rows);
          } }),
        series,
      });
    }
    charts.push(chart("chart-stress-mix", (t) => {
      const c = t.dark ? ["#256abf", "#7d4c14", "#b8651f", "#f0a05a"] : ["#9ec5f4", "#f5c48e", "#ec9447", "#c25a14"];
      const keys = ["stress_rest_s", "stress_low_s", "stress_med_s", "stress_high_s"];
      const names = { stress_rest_s: "Rest", stress_low_s: "Low", stress_med_s: "Medium", stress_high_s: "High" };
      const colors = {}; keys.forEach((k, i) => (colors[k] = c[i]));
      return dailyBars(t, keys, names, colors, 2, (v) => hm(v), { scale: 1 / 3600, axisFmt: (v) => v + " h", weekLabel: "Daily average, week of " });
    }));
    charts.push(chart("chart-floors", (t) => {
      const down = at(data.daily.dates, data.daily.floors_down);
      return dailyBars(t, ["floors_up"], { floors_up: "Floors up" }, { floors_up: t.elev }, 1, (v) => num(v, 0), {
        weekLabel: "Daily average, week of ",
        extra: (d, wk) => (wk ? [] : [{ name: "Floors down", value: down.get(d) != null ? num(down.get(d)) : "-" }]) });
    }));
    charts.push(chart("chart-kcal", (t) => dailyBars(t, ["kcal_resting", "kcal_active"], { kcal_resting: "Resting", kcal_active: "Active" },
      { kcal_resting: t.lineStrong, kcal_active: t.sport.walk }, 0, (v) => num(v) + " kcal", { total: true, weekLabel: "Daily average, week of " })));
    charts.push(chart("chart-weight", (t) => {
      const i0 = cut(data.weight.map((w) => w[0]));
      return weightOption(t, data.weight.slice(i0));
    }));

    seg("range", (r) => { range = Number(r); charts.forEach((c) => c && c.render()); });
  };

  /* ---------- maps with many activities (places) ---------- */
  function mapConfig() { const el = document.getElementById("map-config"); return el ? JSON.parse(el.textContent) : {}; }
  function cartoTransform(cfg) {
    // CARTO wants the key on style, tile, font and sprite requests alike
    return (url) => {
      if (cfg.key && /basemaps\.cartocdn\.com/.test(url) && !/[?&]key=/.test(url)) {
        return { url: url + (url.indexOf("?") >= 0 ? "&" : "?") + "key=" + encodeURIComponent(cfg.key) };
      }
      return { url };
    };
  }
  function boundsOf(coords, trim) {
    // with many points, leave out the outer 2% on each side so one stray GPS jump does not zoom the map out
    const lons = coords.map((c) => c[0]).sort((a, b) => a - b), lats = coords.map((c) => c[1]).sort((a, b) => a - b);
    const k = trim && coords.length > 200 ? Math.floor(coords.length * 0.02) : 0;
    const lo = (arr) => arr[k], hi = (arr) => arr[arr.length - 1 - k];
    return [[lo(lons), lo(lats)], [hi(lons), hi(lats)]];
  }
  function tipHtml(title, sub) { return `<div class="tt"><div class="tt-row"><span class="tt-name" style="color:var(--ink);font-weight:650">${esc(title)}</span></div>${sub ? `<div class="tt-title">${esc(sub)}</div>` : ""}</div>`; }

  // lines: [{id, color, c: [[[lon, lat], ...], ...], title, sub, href}] (a track can come in pieces where the GPS jumped),
  // points: [{lon, lat, size, label, title, sub, href}]
  function overviewMap(el, opts) {
    const cfg = mapConfig();
    const t = tokens();
    const all = [];
    (opts.lines || []).forEach((l) => {
      if (l.c.length && typeof l.c[0][0] === "number") l.c = [l.c];  // older single-piece tracks
      l.c.forEach((piece) => all.push(...piece));
    });
    (opts.points || []).forEach((p) => all.push([p.lon, p.lat]));
    if (!all.length) return null;
    const bounds = boundsOf(all, !!(opts.lines || []).length);
    const style = t.dark && cfg.vector_dark ? cfg.vector_dark : cfg.vector;

    function raster() {
      if (!window.L) return null;
      el.innerHTML = "";
      const map = L.map(el, { scrollWheelZoom: false, zoomControl: true });
      L.tileLayer(cfg.raster || "https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19, referrerPolicy: "strict-origin-when-cross-origin",
        attribution: cfg.raster_attribution || '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      }).addTo(map);
      (opts.lines || []).forEach((l) => {
        const line = L.polyline(l.c.map((piece) => piece.map((p) => [p[1], p[0]])), { color: l.color, weight: 2.4, opacity: 0.6, lineCap: "round", lineJoin: "round" }).addTo(map);
        line.bindTooltip(tipHtml(l.title, l.sub), { sticky: true, className: "map-tip", opacity: 1 });
        line.on("mouseover", () => line.setStyle({ weight: 5, opacity: 1 }).bringToFront());
        line.on("mouseout", () => line.setStyle({ weight: 2.4, opacity: 0.6 }));
        line.on("click", () => (location.href = l.href));
      });
      (opts.points || []).forEach((p) => {
        const m = L.marker([p.lat, p.lon], { icon: L.divIcon({ className: "", html: placeMarker(p).outerHTML, iconSize: [p.size, p.size] }) }).addTo(map);
        m.bindTooltip(tipHtml(p.title, p.sub), { className: "map-tip", opacity: 1, direction: "top", offset: [0, -p.size / 2] });
        m.on("click", () => (location.href = p.href));
      });
      map.fitBounds(L.latLngBounds([[bounds[0][1], bounds[0][0]], [bounds[1][1], bounds[1][0]]]), { padding: [30, 30], maxZoom: opts.maxZoom || 14 });
      return { destroy() { map.remove(); } };
    }

    function vector(styleUrl, onFail) {
      const ml = window.maplibregl;
      let map, ready = false, gaveUp = false;
      const giveUp = () => { if (gaveUp) return; gaveUp = true; try { map && map.remove(); } catch (e) {} onFail(); };
      try {
        map = new ml.Map({
          container: el, style: styleUrl, bounds, fitBoundsOptions: { padding: 40, maxZoom: opts.maxZoom || 14 },
          attributionControl: false, cooperativeGestures: true, dragRotate: false, pitchWithRotate: false, touchPitch: false,
          transformRequest: cartoTransform(cfg),
        });
      } catch (e) { giveUp(); return null; }
      map.touchZoomRotate.disableRotation();
      map.addControl(new ml.NavigationControl({ showCompass: false }), "top-left");
      map.addControl(new ml.FullscreenControl(), "top-left");
      map.on("style.load", () => { ready = true; });
      map.on("error", () => { if (!ready) giveUp(); });
      map.on("load", () => {
        const hasAttr = Object.values(map.getStyle().sources || {}).some((src) => src.attribution);
        map.addControl(new ml.AttributionControl({ compact: true, customAttribution: hasAttr ? undefined : cfg.attribution }), "bottom-right");
        if ((opts.lines || []).length) {
          map.addSource("routes", { type: "geojson", data: { type: "FeatureCollection", features: opts.lines.map((l, i) => ({
            type: "Feature", id: i, properties: { color: l.color, i }, geometry: { type: "MultiLineString", coordinates: l.c } })) } });
          const round = { "line-join": "round", "line-cap": "round" };
          map.addLayer({ id: "routes", type: "line", source: "routes", layout: round, paint: {
            "line-color": ["get", "color"], "line-opacity": ["case", ["boolean", ["feature-state", "hot"], false], 1, 0.55],
            // zoom must be the outer expression; the hovered line is drawn wider at every zoom
            "line-width": ["interpolate", ["linear"], ["zoom"],
              9, ["case", ["boolean", ["feature-state", "hot"], false], 4.5, 1.4],
              15, ["case", ["boolean", ["feature-state", "hot"], false], 7, 3]] } });
          map.addLayer({ id: "routes-hit", type: "line", source: "routes", layout: round, paint: { "line-color": "#000", "line-width": 14, "line-opacity": 0 } });
          const popup = new ml.Popup({ closeButton: false, closeOnClick: false, className: "map-tip", offset: 10 });
          let hot = null;
          map.on("mousemove", "routes-hit", (e) => {
            const f = e.features && e.features[0];
            if (!f) return;
            map.getCanvas().style.cursor = "pointer";
            if (hot !== null && hot !== f.id) map.setFeatureState({ source: "routes", id: hot }, { hot: false });
            hot = f.id;
            map.setFeatureState({ source: "routes", id: hot }, { hot: true });
            const l = opts.lines[f.properties.i];
            popup.setLngLat(e.lngLat).setHTML(tipHtml(l.title, l.sub)).addTo(map);
          });
          map.on("mouseleave", "routes-hit", () => {
            map.getCanvas().style.cursor = "";
            if (hot !== null) map.setFeatureState({ source: "routes", id: hot }, { hot: false });
            hot = null;
            popup.remove();
          });
          map.on("click", "routes-hit", (e) => { const f = e.features && e.features[0]; if (f) location.href = opts.lines[f.properties.i].href; });
        }
        (opts.points || []).forEach((p) => {
          const node = placeMarker(p);
          node.title = p.title + (p.sub ? ", " + p.sub : "");
          node.addEventListener("click", () => (location.href = p.href));
          new ml.Marker({ element: node }).setLngLat([p.lon, p.lat]).addTo(map);
        });
      });
      return { destroy() { try { map.remove(); } catch (e) {} } };
    }

    if (style && window.maplibregl) {
      let api = null;
      const fallback = () => { api = raster(); };
      api = vector(style, () => {
        if (style !== cfg.vector && cfg.vector) api = vector(cfg.vector, fallback);
        else fallback();
      });
      return { destroy() { api && api.destroy(); } };
    }
    return raster();
  }
  function placeMarker(p) {
    const d = document.createElement("div");
    d.className = "place-marker";
    d.style.width = d.style.height = p.size + "px";
    d.textContent = p.label;
    return d;
  }

  PAGES.places = function (data) {
    const el = document.getElementById("places-map");
    if (!el) return;
    const max = Math.max(1, ...data.places.map((p) => p.count));
    let api = null;
    const draw = () => {
      if (api) api.destroy();
      api = overviewMap(el, {
        maxZoom: 9,
        points: data.places.map((p) => ({
          lon: p.lon, lat: p.lat, size: Math.round(22 + 26 * Math.sqrt(p.count / max)), label: p.count,
          title: p.name, sub: `${p.country}, ${p.count} activit${p.count === 1 ? "y" : "ies"}`, href: "/places/" + p.slug + "/",
        })),
      });
    };
    draw();
    window.__afterRerender = draw;
  };

  PAGES.place = function (data) {
    monthDayBySport(data);
    const el = document.getElementById("routes-map");
    if (!el || !data.routes.length) return;
    let api = null;
    const draw = () => {
      if (api) api.destroy();
      const t = tokens();
      api = overviewMap(el, {
        maxZoom: 15,
        lines: data.routes.slice().reverse().map((r) => ({
          c: r.c, color: t.sport[r.cat] || t.sport.other, href: "/activity/" + r.id + "/",
          title: r.name || SPORT_LABEL[r.cat], sub: `${dayLabel(r.date)}${r.km ? ", " + num(r.km, 1) + " km" : ""}${r.kind ? ", " + r.kind : ""}`,
        })),
      });
    };
    draw();
    window.__afterRerender = draw;
  };

  // one course: every run on it, time against date (up is faster), coloured by kind
  PAGES.courses = function (data) {
    const R = data.rows;
    const order = ["easy", "workout", "long", "race"];
    const names = { easy: "Easy and other", workout: "Workouts", long: "Long runs", race: "Races and time trials" };
    const groups = order.filter((g) => R.some((r) => r.group === g));
    chart("chart-course", (t) => {
      const best = Math.min(...R.map((r) => r.secs).filter(Boolean));
      return Object.assign(base(t), {
        grid: { left: 6, right: 14, top: 30, bottom: 6, containLabel: true },
        legend: legend(t, groups.map((g) => names[g])),
        xAxis: axisTime(t, timeSpan(R.map((r) => r.date))),
        yAxis: axisVal(t, dur, { inverse: true, scale: true }),
        tooltip: Object.assign(tooltipBase(t), {
          trigger: "item",
          formatter: (p) => {
            const r = p.data.r;
            return ttHtml(r.title, [
              { name: dayLabel(r.date), value: "" },
              { color: p.color, name: "Time", value: dur(r.secs) + (r.secs === best ? " (best)" : " (+" + dur(r.secs - best) + ")") },
              { name: "Pace", value: pace(r.pace) + " /km" },
              { name: "Heart rate", value: r.hr ? num(r.hr) + " bpm" : "-" },
              { name: "Conditions", value: (r.temp != null ? num(r.temp) + "°C" : "") + (r.wind != null ? ", wind " + num(r.wind) + " km/h" : "") },
            ].concat(r.kind ? [{ name: "Kind", value: r.kind }] : []));
          },
        }),
        series: [{ name: "line", type: "line", data: R.map((r) => [r.date, r.secs]), showSymbol: false, silent: true, z: 1,
                   lineStyle: { width: 1.5, color: t.lineStrong, type: "dashed" }, tooltip: { show: false } }].concat(groups.map((g) => ({
          name: names[g], type: "scatter", symbolSize: 11, z: 3,
          itemStyle: { color: t.group[g], borderColor: t.surface, borderWidth: 1.5 },
          data: R.filter((r) => r.group === g).map((r) => ({ value: [r.date, r.secs], id: r.id, r })),
        }))),
      });
    }, { after: (c) => c.on("click", (p) => { if (p.data && p.data.id) location.href = "/activity/" + p.data.id + "/"; }) });
  };

  /* ---------- phone menu: a panel under the top bar ---------- */
  function initMenu() {
    const btn = document.getElementById("nav-toggle");
    const side = document.querySelector(".side");
    if (!btn || !side) return;
    const set = (on) => {
      document.documentElement.style.setProperty("--bar-h", side.getBoundingClientRect().bottom + "px");
      document.body.classList.toggle("nav-open", on);
      btn.setAttribute("aria-expanded", on ? "true" : "false");
      btn.querySelector("span").textContent = on ? "Close" : "Menu";
    };
    btn.addEventListener("click", () => set(!document.body.classList.contains("nav-open")));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") set(false); });
    document.getElementById("main-nav").addEventListener("click", (e) => { if (e.target.closest("a")) set(false); });
    window.addEventListener("resize", () => { if (window.innerWidth > 900) set(false); });
  }

  /* ---------- date picker: weeks start on Monday, whatever the browser's language ---------- */
  function datePicker(input) {
    const pop = document.createElement("div");
    pop.className = "dp";
    pop.hidden = true;
    input.insertAdjacentElement("afterend", pop);
    let view = null;
    const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    const read = () => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(input.value.trim()); return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null; };
    function draw() {
      const chosen = read(), today = new Date();
      const first = new Date(view.getFullYear(), view.getMonth(), 1);
      const lead = (first.getDay() + 6) % 7;  // Monday = 0
      const days = new Date(view.getFullYear(), view.getMonth() + 1, 0).getDate();
      let h = `<div class="dp-head"><button type="button" data-dp="-1" aria-label="Previous month">&lsaquo;</button><span>${MONTHS[view.getMonth()]} ${view.getFullYear()}</span><button type="button" data-dp="1" aria-label="Next month">&rsaquo;</button></div><div class="dp-grid">`;
      h += ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((n) => `<span class="dp-dow">${n}</span>`).join("");
      for (let i = 0; i < lead; i++) h += "<span></span>";
      for (let dnum = 1; dnum <= days; dnum++) {
        const d = new Date(view.getFullYear(), view.getMonth(), dnum);
        const cls = [chosen && iso(d) === iso(chosen) ? "is-on" : "", iso(d) === iso(today) ? "is-today" : ""].join(" ");
        h += `<button type="button" class="${cls}" data-day="${iso(d)}">${dnum}</button>`;
      }
      pop.innerHTML = h + "</div>";
    }
    function open() { const c = read() || new Date(); view = new Date(c.getFullYear(), c.getMonth(), 1); draw(); pop.hidden = false; }
    function close() { pop.hidden = true; }
    input.addEventListener("focus", open);
    input.addEventListener("click", open);
    input.addEventListener("input", () => { if (read()) { open(); } });
    input.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
    pop.addEventListener("mousedown", (e) => e.preventDefault());  // keep focus in the input
    pop.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.dp) { view.setMonth(view.getMonth() + Number(b.dataset.dp)); draw(); return; }
      if (b.dataset.day) { input.value = b.dataset.day; close(); input.dispatchEvent(new Event("change")); }
    });
    document.addEventListener("click", (e) => { if (!pop.hidden && e.target !== input && !pop.contains(e.target)) close(); });
    input.addEventListener("blur", () => setTimeout(close, 150));
  }

  /* ---------- boot ---------- */
  function boot() {
    initTheme();
    initSync();
    initFeed();
    initAutoSubmit();
    sparks();
    // race form: "Other" distance shows a box for the kilometres
    $$("[data-distance]").forEach((sel) => {
      const box = sel.closest("form").querySelector("[data-other-km]");
      const sync = () => { if (box) box.hidden = sel.value !== "other"; };
      sel.addEventListener("change", sync);
      sync();
    });
    $$("[data-datepicker]").forEach(datePicker);
    initMenu();
    // courses: hide the ones run only once (remembered in this browser)
    const once = $("[data-hide-once]");
    if (once) {
      const apply = () => $$("[data-course-list] li").forEach((li) => { li.hidden = once.checked && li.dataset.count === "1"; });
      try { once.checked = localStorage.getItem("hideOnce") === "1"; } catch (e) { /* storage blocked */ }
      once.addEventListener("change", () => { try { localStorage.setItem("hideOnce", once.checked ? "1" : "0"); } catch (e) { /* ignore */ } apply(); });
      apply();
    }
    // copy buttons (the plan page's prompt for an AI tool)
    $$("[data-copy]").forEach((btn) => btn.addEventListener("click", () => {
      const el = document.getElementById(btn.dataset.copy);
      if (!el || !navigator.clipboard) return;
      navigator.clipboard.writeText(el.textContent.trim()).then(() => { const t = btn.textContent; btn.textContent = "Copied"; setTimeout(() => (btn.textContent = t), 1500); });
    }));
    const page = document.body.dataset.page;
    const dataEl = document.getElementById("page-data");
    const data = dataEl ? JSON.parse(dataEl.textContent) : null;
    if (!data) return;
    // the activity page carries a stream; overview, personal and health go by name; anything else is a sport page
    const which = data.stream !== undefined ? PAGES.activity : (PAGES[page] && page !== "sport" && page !== "activity" ? PAGES[page] : (data.category ? PAGES.sport : null));
    try { which && which(data); } catch (e) { console.error(e); }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
