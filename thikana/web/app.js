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
    limits: $("limits"), model: $("model"),
    modeSingle: $("mode-single"), modeFiles: $("mode-files"), singlePanel: $("single-panel"), filesPanel: $("files-panel"),
    drop: $("drop"), fileInput: $("file-input"), dropSub: $("drop-sub"), sample: $("sample"),
    filesClear: $("files-clear"), filesCancel: $("files-cancel"), filesRun: $("files-run"),
    filesRunLabel: $("files-run-label"), filesStatus: $("files-status"), files: $("files")
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
  var limits = Object.assign({}, T.FALLBACK_LIMITS);   // what the server accepts; replaced by what it reports
  var queuedFiles = false;    // the person pressed "Parse files" while the server was still waking

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
    var reported = info.limits || {};
    ["max_batch", "max_text_chars", "max_body_bytes"].forEach(function (key) {
      if (Number.isInteger(reported[key]) && reported[key] > 0) { limits[key] = reported[key]; }
    });
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
      if (queuedFiles) { queuedFiles = false; runFiles(); }
      updateRunButton();
    } else {
      queued = false;
      queuedFiles = false;
      setFilesStatus("", "");
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

  /* ---- files: several CSV / TSV / TXT files, each parsed row by row and handed back as a CSV ---- */
  var BATCH_TIMEOUT_MS = 30000;
  var fileList = [];          // one entry per card: {name, state, table, hasHeader, column, items, outcomes, result, ui}
  var running = false;
  var stopRequested = false;
  var FAILURE_WORDS = {
    rate_limited: "the site's request limit did not clear",
    not_ready: "the model was not ready",
    network: "the connection dropped",
    rejected: "the server refused a group of rows",
    bad_response: "the server's answer could not be read"
  };

  function setFilesStatus(message, state) {
    el.filesStatus.textContent = message;
    el.filesStatus.className = "status " + (state || "");
  }

  function setMode(mode) {
    var files = mode === "files";
    el.singlePanel.hidden = files;
    el.filesPanel.hidden = !files;
    el.modeSingle.setAttribute("aria-selected", String(!files));
    el.modeFiles.setAttribute("aria-selected", String(files));
  }

  function updateRunButton() {
    var waiting = fileList.some(function (f) { return f.state === "ready" || f.state === "failed"; });
    el.filesRun.disabled = running || !waiting;
    el.filesRunLabel.textContent = running ? "Parsing..." : "Parse files";
    el.filesCancel.hidden = !running;
  }

  function truncate(text, max) {
    var chars = Array.from(text);
    return chars.length > max ? chars.slice(0, max - 1).join("") + "…" : text;
  }

  function dataRows(file) {
    var start = file.hasHeader ? 1 : 0;
    return file.table.rows.slice(start, start + T.FILE_LIMITS.MAX_ROWS);
  }

  function download(filename, text, type) {
    var url = URL.createObjectURL(new Blob([text], { type: type }));
    var link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.hidden = true;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function summaryLine(file) {
    var s = T.summarise(file.outcomes);
    var notes = [];
    if (s.noParts) { notes.push(s.noParts + " had no parts found"); }
    if (s.empty) { notes.push(s.empty + " empty"); }
    if (s.tooLong) { notes.push(s.tooLong + " too long to send"); }
    if (s.failed) { notes.push(s.failed + " failed"); }
    if (s.notRun) { notes.push(s.notRun + " not run"); }
    var line = "Parsed " + s.parsed + " of " + s.total + " rows" + (notes.length ? " (" + notes.join(", ") + ")" : "") + ".";
    var reason = file.outcomes.filter(function (o) { return o.status === "error"; })[0];
    if (reason) { line += " Rows failed because " + (FAILURE_WORDS[reason.reason] || "of a server error") + "."; }
    if (file.result.cancelled) { line += " Stopped before the end."; }
    if (file.result.aborted) { line += " Stopped: three groups in a row failed."; }
    return line;
  }

  function columnOptions(file) {
    var options = [];
    for (var i = 0; i < file.table.columns; i++) {
      var name = file.hasHeader ? (file.table.rows[0][i] || "").trim() : "";
      options.push({ value: i, label: file.table.lines ? "Each line" : "Column " + (i + 1) + (name ? ": " + truncate(name, 30) : "") });
    }
    if (file.table.columns > 1) { options.push({ value: -1, label: "Whole line (all columns joined)" }); }
    return options;
  }

  function refreshCard(file) {
    if (!file.table) { return; }       // a card that only shows why a file was refused
    var ui = file.ui;
    var rows = dataRows(file);
    var total = file.table.rows.length - (file.hasHeader ? 1 : 0);
    ui.meta.textContent = total + (total === 1 ? " row" : " rows") + ", " + file.table.columns +
      (file.table.columns === 1 ? " column" : " columns") +
      (total > rows.length ? ". Only the first " + rows.length + " rows are used." : "");

    ui.select.textContent = "";
    columnOptions(file).forEach(function (option) {
      var node = document.createElement("option");
      node.value = String(option.value);
      node.textContent = option.label;
      ui.select.appendChild(node);
    });
    ui.select.value = String(file.column);
    ui.selectWrap.hidden = file.table.columns <= 1;

    var first = T.prepareItems(rows, file.column, limits).filter(function (item) { return item.status === "ok"; })[0];
    ui.sample.textContent = first ? "First address read: " + truncate(first.send, 90) : "No usable address in that column.";

    var finished = file.state === "done" || file.state === "stopped";
    ui.actions.hidden = !finished;
    ui.status.hidden = !finished && file.state !== "running" && file.state !== "failed";
    if (finished) { ui.status.textContent = summaryLine(file); }
    if (file.state === "failed") {      // nothing was parsed: no file worth downloading, and the person can try again
      ui.status.textContent = summaryLine(file) + " There is nothing to download. Check that the site is running, then press Parse files again.";
    }
    ui.progress.hidden = file.state !== "running";
    ui.node.setAttribute("data-state", file.state);
    ui.select.disabled = ui.header.disabled = running;
  }

  function invalidate(file) {      // the person changed a choice after a run: those results no longer match
    file.state = "ready";
    file.outcomes = null;
    file.result = null;
    refreshCard(file);
    updateRunButton();
  }

  function removeFile(file) {
    fileList.splice(fileList.indexOf(file), 1);
    file.ui.node.remove();
    updateRunButton();
  }

  function addCard(name, build) {
    var item = document.createElement("li");
    item.className = "file";
    var head = document.createElement("div");
    head.className = "file-head";
    var title = document.createElement("strong");
    title.className = "file-name";
    title.textContent = name;
    var remove = document.createElement("button");
    remove.type = "button";
    remove.className = "link small";
    remove.textContent = "Remove";
    remove.setAttribute("aria-label", "Remove " + name);
    head.appendChild(title);
    head.appendChild(remove);
    item.appendChild(head);
    el.files.appendChild(item);
    var entry = { name: name, ui: { node: item } };
    remove.addEventListener("click", function () { if (entry.state !== "running") { removeFile(entry); } });
    build(entry, item);
    fileList.push(entry);
    return entry;
  }

  function addProblem(name, message) {
    addCard(name, function (entry, item) {
      entry.state = "problem";
      var note = document.createElement("p");
      note.className = "file-problem";
      note.textContent = message;
      item.appendChild(note);
      item.setAttribute("data-state", "problem");
    });
  }

  function addTable(name, table, note) {
    var file = addCard(name, function (entry, item) {
      entry.table = table;
      entry.hasHeader = T.guessHasHeader(table);
      entry.column = T.guessColumn(table, entry.hasHeader);
      entry.state = "ready";
      var ui = entry.ui;
      ui.meta = document.createElement("p");
      ui.meta.className = "file-meta";
      var opts = document.createElement("div");
      opts.className = "file-opts";
      ui.selectWrap = document.createElement("label");
      ui.selectWrap.appendChild(document.createTextNode("Address column "));
      ui.select = document.createElement("select");
      ui.selectWrap.appendChild(ui.select);
      var headerWrap = document.createElement("label");
      headerWrap.className = "check";
      ui.header = document.createElement("input");
      ui.header.type = "checkbox";
      ui.header.checked = entry.hasHeader;
      headerWrap.appendChild(ui.header);
      headerWrap.appendChild(document.createTextNode(" First row is a header"));
      opts.appendChild(ui.selectWrap);
      opts.appendChild(headerWrap);
      ui.sample = document.createElement("p");
      ui.sample.className = "file-sample";
      ui.progress = document.createElement("progress");
      ui.progress.hidden = true;
      ui.status = document.createElement("p");
      ui.status.className = "file-status";
      ui.status.hidden = true;
      ui.actions = document.createElement("div");
      ui.actions.className = "file-actions";
      ui.actions.hidden = true;
      var csv = document.createElement("button");
      csv.type = "button";
      csv.textContent = "Download CSV";
      var json = document.createElement("button");
      json.type = "button";
      json.className = "secondary";
      json.textContent = "Download JSON";
      ui.actions.appendChild(csv);
      ui.actions.appendChild(json);
      [ui.meta, opts, ui.sample, ui.progress, ui.status, ui.actions].forEach(function (node) { item.appendChild(node); });
      if (note) {
        var warning = document.createElement("p");
        warning.className = "file-problem";
        warning.textContent = note;
        item.insertBefore(warning, opts);
      }
      ui.select.addEventListener("change", function () { entry.column = Number(ui.select.value); invalidate(entry); });
      ui.header.addEventListener("change", function () {
        entry.hasHeader = ui.header.checked;
        entry.column = T.guessColumn(entry.table, entry.hasHeader);
        invalidate(entry);
      });
      csv.addEventListener("click", function () {
        var rows = T.outputRows(entry.table, entry.hasHeader, dataRows(entry), entry.outcomes);
        download(T.downloadName(entry.name, "csv"), "﻿" + T.toCsv(rows), "text/csv;charset=utf-8");
      });
      json.addEventListener("click", function () {
        var data = T.outputJson(entry.items, entry.outcomes);
        download(T.downloadName(entry.name, "json"), JSON.stringify(data, null, 2), "application/json;charset=utf-8");
      });
    });
    refreshCard(file);
  }

  async function addFile(file) {
    var ext = (file.name.match(/\.([^.]+)$/) || [])[1];
    ext = ext ? ext.toLowerCase() : "";
    if (["csv", "tsv", "txt"].indexOf(ext) === -1) {
      addProblem(file.name, ext === "pdf" || ext === "xlsx" || ext === "xls" || ext === "docx"
        ? "." + ext + " files are not supported yet. Save the addresses as a CSV UTF-8 or TXT file and add that."
        : "Only CSV, TSV and TXT files are supported.");
      return;
    }
    if (file.size > T.FILE_LIMITS.MAX_BYTES) {
      addProblem(file.name, "That file is larger than " + (T.FILE_LIMITS.MAX_BYTES / (1024 * 1024)) + " MB. Split it and add the parts.");
      return;
    }
    var text;
    try { text = await file.text(); } catch (unreadable) {
      addProblem(file.name, "That file could not be read.");
      return;
    }
    var table = T.readTable(text, file.name);
    if (!table.rows.length) { addProblem(file.name, "There is nothing in that file."); return; }
    var notes = [];
    if (text.indexOf("�") !== -1) {
      notes.push("Some characters could not be decoded. Save the file as CSV UTF-8 (Bangla needs it) and add it again.");
    }
    if (table.unterminated) { notes.push("A quote in this file is never closed, so its last row may hold more text than intended."); }
    addTable(file.name, table, notes.join(" "));
  }

  async function handleFiles(chosen) {
    var incoming = Array.from(chosen || []);
    el.fileInput.value = "";
    if (!incoming.length || running) { return; }
    var room = T.FILE_LIMITS.MAX_FILES - fileList.length;
    var taken = incoming.slice(0, Math.max(room, 0));
    for (var i = 0; i < taken.length; i++) { await addFile(taken[i]); }
    setFilesStatus(incoming.length > taken.length
      ? "Only " + T.FILE_LIMITS.MAX_FILES + " files at a time: " + (incoming.length - taken.length) + " not added."
      : "", incoming.length > taken.length ? "bad" : "");
    updateRunButton();
  }

  async function sendBatch(texts) {
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, BATCH_TIMEOUT_MS);
    try {
      var response = await fetch("/api/v1/parse/batch", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ texts: texts }),
        signal: controller.signal
      });
      var body = null;
      try { body = await response.json(); } catch (notJson) { /* an error page, not JSON */ }
      return { status: response.status, body: body, retryAfter: response.headers.get("Retry-After") };
    } finally {
      clearTimeout(timer);
    }
  }

  async function runFiles() {
    if (running) { return; }
    var todo = fileList.filter(function (f) { return f.state === "ready" || f.state === "failed"; });
    if (!todo.length) { return; }
    if (!ready) {
      queuedFiles = true;
      setFilesStatus("The server is still waking up. Your files will be parsed as soon as it is ready.", "wait");
      return;
    }
    running = true;
    stopRequested = false;
    setFilesStatus("", "");
    updateRunButton();
    fileList.forEach(refreshCard);
    for (var i = 0; i < todo.length && !stopRequested; i++) {
      var file = todo[i];
      file.items = T.prepareItems(dataRows(file), file.column, limits);
      file.state = "running";
      refreshCard(file);
      file.ui.status.textContent = "Parsing " + (i + 1) + " of " + todo.length + "...";
      file.result = await T.parseItems(file.items, limits, {
        send: sendBatch,
        sleep: sleep,
        cancelled: function () { return stopRequested; },
        onProgress: function (done, total) {
          file.ui.progress.max = total;
          file.ui.progress.value = done;
          file.ui.status.textContent = "Parsed " + done + " of " + total + " rows...";
        }
      });
      file.outcomes = file.result.outcomes;
      var counts = T.summarise(file.outcomes);
      file.state = counts.parsed + counts.noParts === 0 && counts.failed > 0 ? "failed"
        : file.result.cancelled || file.result.aborted ? "stopped" : "done";
    }
    var stopped = stopRequested;
    var failed = todo.filter(function (f) { return f.state === "failed"; }).length;
    var kept = todo.filter(function (f) { return f.state === "done" || f.state === "stopped"; }).length;
    running = false;
    stopRequested = false;
    fileList.forEach(refreshCard);
    updateRunButton();
    if (failed) {
      setFilesStatus(failed === 1 && !kept ? "Nothing could be parsed. See the reason below." :
                     failed + " of " + todo.length + " files could not be parsed. See the reason below.", "bad");
    } else {
      setFilesStatus(stopped ? "Stopped. What was parsed so far can still be downloaded." : "Done. Download each file below.",
                     stopped ? "" : "ok");
    }
  }

  function clearFiles() {
    if (running) { stopRequested = true; }
    fileList = fileList.filter(function (f) { return f.state === "running"; });
    el.files.textContent = "";
    fileList.forEach(function (f) { el.files.appendChild(f.ui.node); });
    queuedFiles = false;
    setFilesStatus("", "");
    updateRunButton();
  }

  /* ---- wiring ---- */
  el.modeSingle.addEventListener("click", function () { setMode("single"); });
  el.modeFiles.addEventListener("click", function () { setMode("files"); });
  el.fileInput.addEventListener("change", function () { handleFiles(el.fileInput.files); });
  ["dragenter", "dragover"].forEach(function (name) {
    el.drop.addEventListener(name, function (event) { event.preventDefault(); el.drop.classList.add("over"); });
  });
  ["dragleave", "drop"].forEach(function (name) {
    el.drop.addEventListener(name, function (event) { event.preventDefault(); el.drop.classList.remove("over"); });
  });
  el.drop.addEventListener("drop", function (event) { handleFiles(event.dataTransfer && event.dataTransfer.files); });
  // A file dropped anywhere else would make the browser leave this page and open the file.
  window.addEventListener("dragover", function (event) { event.preventDefault(); });
  window.addEventListener("drop", function (event) { event.preventDefault(); });
  el.sample.addEventListener("click", function () {
    download("thikana_sample.csv", "﻿" + T.SAMPLE_CSV, "text/csv;charset=utf-8");
  });
  el.filesRun.addEventListener("click", runFiles);
  el.filesCancel.addEventListener("click", function () { stopRequested = true; });
  el.filesClear.addEventListener("click", clearFiles);

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
