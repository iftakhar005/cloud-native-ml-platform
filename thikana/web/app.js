/* DOM wiring for the Thikana page. The logic worth testing is in render.js.
   Rules this file keeps: user text and server text are only ever inserted with textContent
   (never as HTML), nothing is stored (no cookies, no localStorage), nothing is sent anywhere
   except this site's own API. */
(function () {
  "use strict";

  var T = window.Thikana;
  var MAX_CHARS = 500;
  var PARSE_TIMEOUT_MS = 20000;   // (how long to keep waiting for a sleeping server: T.WAKE_ATTEMPTS)
  var COPIED_MS = 1600;

  function $(id) { return document.getElementById(id); }
  var el = {
    form: $("form"), text: $("text"), count: $("count"), parse: $("parse"), parseLabel: $("parse-label"),
    clear: $("clear"), chips: $("chips"), surprise: $("surprise"), status: $("status"),
    pill: $("pill"), pillText: $("pill-text"),
    wake: $("wake"), wakeText: $("wake-text"), wakeBar: $("wake-bar"), retry: $("retry"),
    result: $("result"), marked: $("marked"), legend: $("legend"), fields: $("fields"),
    emptyNote: $("empty-note"), meta: $("meta"), raw: $("raw"), error: $("error"),
    copyJson: $("copy-json"), copyParts: $("copy-parts"),
    about: $("about"), aboutOpen: $("about-open"), aboutClose: $("about-close"),
    limits: $("limits"), model: $("model")
  };
  var examples = Array.prototype.map.call(el.chips.querySelectorAll("button[data-text]"), function (b) {
    return b.getAttribute("data-text");
  });
  var ready = false;     // the model has answered
  var busy = false;      // a parse is in flight
  var queued = false;    // the person pressed Parse while the server was still waking
  var last = null;       // the latest successful answer, for the copy buttons
  var pinned = null;     // a part picked out by clicking
  var hovered = null;    // a part picked out by pointing or keyboard focus
  var pointerMoved = false;   // false after each new result: a result that appears under a resting pointer is not "pointed at"

  function sleep(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }

  function setStatus(message, state) {
    el.status.textContent = message;
    el.status.className = "status " + (state || "");
  }

  function setPill(state, label) {
    el.pill.className = "pill " + state;
    el.pillText.textContent = label;
  }

  function showError(message) {
    el.error.textContent = message;
    el.error.hidden = false;
    el.result.hidden = true;
  }

  function updateCount() {
    var used = Array.from(el.text.value).length;
    el.count.textContent = used + " / " + MAX_CHARS;
    el.count.className = "count " + T.counterState(used, MAX_CHARS);
  }

  /* ---- connect: wait for the model, filling the "about" box from the API's own words ---- */
  function showModel(info) {
    el.model.textContent = info.name + " (version " + info.version + ")";
    el.limits.textContent = "";
    (info.limitations || []).forEach(function (line) {
      var li = document.createElement("li");
      li.textContent = line;
      el.limits.appendChild(li);
    });
  }

  async function connect() {
    el.retry.hidden = true;
    el.wake.hidden = false;
    el.wake.className = "wake";
    el.wakeText.textContent = "Connecting to the model...";
    el.wakeBar.hidden = false;
    el.wakeBar.value = 0;
    setPill("wait", "Connecting");
    var result = await T.connectWithRetry({
      fetchModel: function () { return fetch("/api/v1/model", { headers: { "Accept": "application/json" } }); },
      sleep: sleep,
      onWait: function (attempt, total, elapsedMs) {
        var seconds = Math.round(elapsedMs / 1000);
        el.wakeText.textContent = "Waking the server: free hosts sleep when idle and this can take a couple " +
          "of minutes. Waited " + seconds + " s...";
        el.wakeBar.value = seconds;
        setPill("wait", "Waking up");
      }
    });
    if (result.ok) {
      showModel(result.info);
      ready = true;
      el.wake.hidden = true;
      setPill("ok", "Ready");
      if (queued) {
        queued = false;
        if (el.text.value.trim()) { el.form.requestSubmit(); }
      } else {
        setStatus("", "");
      }
    } else {
      queued = false;
      el.wake.className = "wake bad";
      el.wakeText.textContent = "Could not reach the model after several minutes.";
      el.wakeBar.hidden = true;
      el.retry.hidden = false;
      setPill("bad", "Offline");
      setStatus("", "");
    }
  }

  /* ---- picking out one kind of part (hover or focus), or pinning it (click) ---- */
  function applyHighlight() {
    var hot = hovered || pinned;
    if (hot) { el.result.setAttribute("data-hot", hot); } else { el.result.removeAttribute("data-hot"); }
    Array.prototype.forEach.call(el.result.querySelectorAll("[data-label]"), function (node) {
      var label = node.getAttribute("data-label");
      node.classList.toggle("hot", !!hot && label === hot);
      node.classList.toggle("dim", !!hot && label !== hot);
    });
    Array.prototype.forEach.call(el.legend.querySelectorAll("button"), function (button) {
      button.setAttribute("aria-pressed", String(pinned !== null && button.getAttribute("data-label") === pinned));
    });
  }

  function labelOf(event) {
    var node = event.target.closest && event.target.closest("[data-label]");
    return node && el.result.contains(node) ? node.getAttribute("data-label") : null;
  }

  /* ---- copy buttons ---- */
  async function copyText(text, button) {
    var done = false;
    try { await navigator.clipboard.writeText(text); done = true; } catch (unavailable) { /* blocked or unsupported */ }
    if (!button.getAttribute("data-idle")) { button.setAttribute("data-idle", button.textContent); }
    button.textContent = done ? "Copied" : "Copy failed";
    clearTimeout(button.resetTimer);
    button.resetTimer = setTimeout(function () { button.textContent = button.getAttribute("data-idle"); }, COPIED_MS);
  }

  /* ---- parse ---- */
  function renderResult(text, data, roundTripMs) {
    last = { text: text, data: data };
    pinned = null;
    hovered = null;
    pointerMoved = false;

    el.marked.textContent = "";
    T.segments(text, data.entities).forEach(function (segment) {
      if (!segment.label) {
        el.marked.appendChild(document.createTextNode(segment.text));
        return;
      }
      var mark = document.createElement("mark");
      mark.className = "l-" + segment.label.toLowerCase();
      mark.setAttribute("data-label", segment.label.toLowerCase());
      var body = document.createElement("span");
      body.textContent = segment.text;
      var tag = document.createElement("span");
      tag.className = "tag";                       // the label as TEXT: colour is never the only cue
      tag.textContent = T.NAMES[segment.label];
      mark.appendChild(body);
      mark.appendChild(tag);
      el.marked.appendChild(mark);
    });

    el.legend.textContent = "";
    T.labelCounts(text, data.entities).forEach(function (part) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "legend-item l-" + part.label.toLowerCase();
      button.setAttribute("data-label", part.label.toLowerCase());
      button.setAttribute("aria-pressed", "false");
      var dot = document.createElement("span");
      dot.className = "swatch";
      var name = document.createElement("span");
      name.textContent = part.name + (part.count > 1 ? " x" + part.count : "");
      button.appendChild(dot);
      button.appendChild(name);
      el.legend.appendChild(button);
    });
    el.legend.hidden = el.legend.children.length === 0;

    el.fields.textContent = "";
    var rows = T.fieldRows(data.fields);
    rows.forEach(function (row) {
      var tr = document.createElement("tr");
      tr.setAttribute("data-label", row.label.toLowerCase());
      var th = document.createElement("th");
      th.scope = "row";
      th.textContent = row.name;
      var td = document.createElement("td");
      td.textContent = row.values.join(" | ");
      var action = document.createElement("td");
      action.className = "row-action";
      var copy = document.createElement("button");
      copy.type = "button";
      copy.className = "secondary small";
      copy.textContent = "Copy";
      copy.setAttribute("data-copy", row.values.join(", "));
      copy.setAttribute("aria-label", "Copy " + row.name + ": " + row.values.join(", "));
      action.appendChild(copy);
      tr.appendChild(th);
      tr.appendChild(td);
      tr.appendChild(action);
      el.fields.appendChild(tr);
    });
    el.emptyNote.hidden = rows.length > 0;
    el.copyParts.hidden = rows.length === 0;

    el.meta.textContent = "Model " + data.model_version + " · answered in " + T.formatMs(roundTripMs) +
      " (round trip) · a draft, not a verified address · nothing is stored.";
    el.raw.textContent = JSON.stringify(data, null, 2);
    el.error.hidden = true;
    el.result.hidden = false;
    applyHighlight();
    var calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.result.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "nearest" });
  }

  function setBusy(on) {
    busy = on;
    el.parse.disabled = on;
    el.parseLabel.textContent = on ? "Parsing..." : "Parse";
  }

  async function submit(event) {
    event.preventDefault();
    if (busy) { return; }
    var text = el.text.value;
    if (!text.trim()) { showError(T.describeError(422, { error: { code: "empty_text" } })); return; }
    if (!ready) {
      queued = true;
      el.error.hidden = true;
      setStatus("The server is still waking up. This will be parsed as soon as it is ready.", "wait");
      return;
    }

    setBusy(true);
    setStatus("Parsing...", "wait");
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, PARSE_TIMEOUT_MS);
    var started = performance.now();
    try {
      var response = await fetch("/api/v1/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ text: text }),
        signal: controller.signal
      });
      var body = null;
      try { body = await response.json(); } catch (notJson) { /* an error page, not JSON */ }
      if (!response.ok) {
        showError(T.describeError(response.status, body, response.headers.get("Retry-After")));
        setStatus("", "");
      } else {
        var elapsed = performance.now() - started;
        renderResult(text, body, elapsed);
        setStatus("Done in " + T.formatMs(elapsed) + ".", "ok");
      }
    } catch (failure) {
      showError(failure && failure.name === "AbortError"
        ? "That took too long. The server may be waking from sleep; please try again."
        : "Could not reach the server. Check your connection and try again.");
      setStatus("", "");
    } finally {
      clearTimeout(timer);
      setBusy(false);
    }
  }

  function useExample(text) {
    el.text.value = text;
    updateCount();
    el.form.requestSubmit();
  }

  /* ---- wiring ---- */
  el.text.addEventListener("input", updateCount);
  el.text.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { el.form.requestSubmit(); }
  });
  el.form.addEventListener("submit", submit);
  el.clear.addEventListener("click", function () {
    el.text.value = "";
    queued = false;
    updateCount();
    el.result.hidden = true;
    el.error.hidden = true;
    setStatus("", "");
    el.text.focus();
  });
  el.chips.addEventListener("click", function (event) {
    var button = event.target.closest("button[data-text]");
    if (button) { useExample(button.getAttribute("data-text")); }
  });
  el.surprise.addEventListener("click", function () {
    useExample(T.cycleExample(examples, el.text.value));
  });
  el.retry.addEventListener("click", connect);

  el.result.addEventListener("mousemove", function (event) {
    if (!pointerMoved) { pointerMoved = true; hovered = labelOf(event); applyHighlight(); }
  });
  el.result.addEventListener("mouseover", function (event) {
    if (pointerMoved) { hovered = labelOf(event); applyHighlight(); }
  });
  el.result.addEventListener("mouseout", function () { hovered = null; applyHighlight(); });
  el.result.addEventListener("focusin", function (event) { hovered = labelOf(event); applyHighlight(); });
  el.result.addEventListener("focusout", function () { hovered = null; applyHighlight(); });
  el.result.addEventListener("click", function (event) {
    var copy = event.target.closest("button[data-copy]");
    if (copy) { copyText(copy.getAttribute("data-copy"), copy); return; }
    var label = labelOf(event);
    if (label && !event.target.closest("tr")) { pinned = pinned === label ? null : label; applyHighlight(); }
  });
  el.copyJson.addEventListener("click", function () {
    if (last) { copyText(JSON.stringify(last.data, null, 2), el.copyJson); }
  });
  el.copyParts.addEventListener("click", function () {
    if (last) { copyText(T.summaryText(last.data.fields), el.copyParts); }
  });

  el.aboutOpen.addEventListener("click", function () {
    if (typeof el.about.showModal === "function") { el.about.showModal(); } else { el.about.setAttribute("open", ""); }
  });
  el.aboutClose.addEventListener("click", function () {
    if (typeof el.about.close === "function") { el.about.close(); } else { el.about.removeAttribute("open"); }
  });
  el.about.addEventListener("click", function (event) {      // a click on the dimmed backdrop closes it
    if (event.target === el.about && typeof el.about.close === "function") { el.about.close(); }
  });

  el.wakeBar.max = Math.round(T.WAKE_ATTEMPTS * T.WAKE_DELAY_MS / 1000);
  updateCount();
  connect();
})();
