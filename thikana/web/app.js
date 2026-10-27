/* DOM wiring for the Thikana page. The logic worth testing is in render.js.
   Rules this file keeps: user text and server text are only ever inserted with textContent
   (never as HTML), nothing is stored (no cookies, no localStorage), nothing is sent anywhere
   except this site's own API. */
(function () {
  "use strict";

  var T = window.Thikana;
  var MAX_CHARS = 500;
  var CONNECT_ATTEMPTS = 25;      // ~100 s: enough for a free host to wake from sleep
  var CONNECT_DELAY_MS = 4000;
  var PARSE_TIMEOUT_MS = 20000;

  var el = {
    form: document.getElementById("form"),
    text: document.getElementById("text"),
    count: document.getElementById("count"),
    parse: document.getElementById("parse"),
    clear: document.getElementById("clear"),
    chips: document.getElementById("chips"),
    status: document.getElementById("status"),
    result: document.getElementById("result"),
    marked: document.getElementById("marked"),
    fields: document.getElementById("fields"),
    meta: document.getElementById("meta"),
    raw: document.getElementById("raw"),
    error: document.getElementById("error"),
    limits: document.getElementById("limits"),
    model: document.getElementById("model")
  };
  var ready = false;

  function sleep(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }

  function setStatus(message, state) {
    el.status.textContent = message;
    el.status.className = "status " + (state || "");
  }

  function showError(message) {
    el.error.textContent = message;
    el.error.hidden = false;
    el.result.hidden = true;
  }

  function updateCount() {
    el.count.textContent = Array.from(el.text.value).length + " / " + MAX_CHARS;
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
    for (var attempt = 1; attempt <= CONNECT_ATTEMPTS; attempt++) {
      try {
        var response = await fetch("/api/v1/model", { headers: { "Accept": "application/json" } });
        if (response.ok) {
          showModel(await response.json());
          ready = true;
          el.parse.disabled = false;
          setStatus("Ready.", "ok");
          return;
        }
      } catch (networkError) { /* the host may be waking up: fall through and retry */ }
      setStatus("Waking the server (free hosts sleep when idle). Attempt " + attempt + " of " +
                CONNECT_ATTEMPTS + "...", "wait");
      await sleep(CONNECT_DELAY_MS);
    }
    setStatus("Could not reach the model. Reload the page to try again.", "bad");
  }

  /* ---- parse ---- */
  function renderResult(text, data, roundTripMs) {
    el.marked.textContent = "";
    T.segments(text, data.entities).forEach(function (segment) {
      if (!segment.label) {
        el.marked.appendChild(document.createTextNode(segment.text));
        return;
      }
      var mark = document.createElement("mark");
      mark.className = "l-" + segment.label.toLowerCase();
      var body = document.createElement("span");
      body.textContent = segment.text;
      var tag = document.createElement("span");
      tag.className = "tag";                       // the label as TEXT: colour is never the only cue
      tag.textContent = T.NAMES[segment.label];
      mark.appendChild(body);
      mark.appendChild(tag);
      el.marked.appendChild(mark);
    });

    el.fields.textContent = "";
    var rows = T.fieldRows(data.fields);
    rows.forEach(function (row) {
      var tr = document.createElement("tr");
      var th = document.createElement("th");
      th.scope = "row";
      th.textContent = row.name;
      var td = document.createElement("td");
      td.textContent = row.values.join(" | ");
      tr.appendChild(th);
      tr.appendChild(td);
      el.fields.appendChild(tr);
    });
    if (!rows.length) {
      var none = document.createElement("tr");
      var cell = document.createElement("td");
      cell.colSpan = 2;
      cell.textContent = "Nothing was labelled.";
      none.appendChild(cell);
      el.fields.appendChild(none);
    }

    el.meta.textContent = "Model " + data.model_version + " · answered in " + T.formatMs(roundTripMs) +
      " (round trip). Nothing is stored.";
    el.raw.textContent = JSON.stringify(data, null, 2);
    el.error.hidden = true;
    el.result.hidden = false;
  }

  async function submit(event) {
    event.preventDefault();
    var text = el.text.value;
    if (!text.trim()) { showError(T.describeError(422, { error: { code: "empty_text" } })); return; }
    if (!ready) { showError(T.describeError(503, null)); return; }

    el.parse.disabled = true;
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
        renderResult(text, body, performance.now() - started);
        setStatus("Done.", "ok");
      }
    } catch (failure) {
      showError(failure && failure.name === "AbortError"
        ? "That took too long. The server may be waking from sleep; please try again."
        : "Could not reach the server. Check your connection and try again.");
      setStatus("", "");
    } finally {
      clearTimeout(timer);
      el.parse.disabled = false;
    }
  }

  /* ---- wiring ---- */
  el.text.addEventListener("input", updateCount);
  el.text.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { el.form.requestSubmit(); }
  });
  el.form.addEventListener("submit", submit);
  el.clear.addEventListener("click", function () {
    el.text.value = "";
    updateCount();
    el.result.hidden = true;
    el.error.hidden = true;
    el.text.focus();
  });
  el.chips.addEventListener("click", function (event) {
    var button = event.target.closest("button[data-text]");
    if (!button) { return; }
    el.text.value = button.getAttribute("data-text");
    updateCount();
    el.form.requestSubmit();
  });

  el.parse.disabled = true;
  updateCount();
  connect();
})();
