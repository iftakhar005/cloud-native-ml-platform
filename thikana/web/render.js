/* Pure logic for the Thikana page. No DOM in here, so Node can unit-test it
   (tests/js/render.test.cjs). Loaded by the page as a classic script (no module system). */
(function (root) {
  "use strict";

  var LABELS = ["HOUSE", "ROAD", "BLOCK", "AREA", "UPAZILA", "DISTRICT", "DIVISION", "POSTCODE", "LANDMARK"];
  var NAMES = {
    HOUSE: "House", ROAD: "Road", BLOCK: "Block", AREA: "Area", UPAZILA: "Upazila",
    DISTRICT: "District", DIVISION: "Division", POSTCODE: "Postcode", LANDMARK: "Landmark"
  };

  /* Split `text` into runs, each either plain (label null) or one predicted entity.
     The API's start/end are Python offsets, i.e. in CODE POINTS. A JavaScript string is
     indexed in UTF-16 units, which differ for any character outside the BMP (emoji, some
     symbols), so slicing the string directly would highlight the wrong words. Array.from
     iterates by code point. Whatever the API returns, the runs always join back to `text`:
     an invalid, out-of-range or overlapping entity is skipped, never duplicated or invented. */
  function segments(text, entities) {
    var chars = Array.from(text);
    var valid = (entities || []).filter(function (e) {
      return Number.isInteger(e.start) && Number.isInteger(e.end) &&
             e.start >= 0 && e.end > e.start && e.end <= chars.length &&
             LABELS.indexOf(e.label) !== -1;
    }).sort(function (a, b) { return a.start - b.start || b.end - a.end; });

    var out = [];
    var pos = 0;
    valid.forEach(function (e) {
      if (e.start < pos) { return; }                       // overlaps the previous span
      if (e.start > pos) { out.push({ text: chars.slice(pos, e.start).join(""), label: null }); }
      out.push({ text: chars.slice(e.start, e.end).join(""), label: e.label });
      pos = e.end;
    });
    if (pos < chars.length) { out.push({ text: chars.slice(pos).join(""), label: null }); }
    return out;
  }

  /* The API's `fields` object ({"house": ["House 12"], ...}) as ordered table rows. */
  function fieldRows(fields) {
    return LABELS.filter(function (label) {
      var values = fields && fields[label.toLowerCase()];
      return Array.isArray(values) && values.length > 0;
    }).map(function (label) {
      return { label: label, name: NAMES[label], values: fields[label.toLowerCase()] };
    });
  }

  /* A message for the person, chosen from the status and the error CODE only. The body's own
     message is never shown: it is not needed, and nothing the server says should be able to
     put arbitrary text on the page. */
  function describeError(status, body, retryAfterSeconds) {
    var code = body && body.error && body.error.code;
    if (status === 429) {
      return "Too many requests from your network. Please wait " +
             (retryAfterSeconds || "a few") + " seconds and try again.";
    }
    if (status === 503) {
      return "The model is not ready yet. On a free host the first request after a quiet " +
             "period can take about a minute.";
    }
    if (code === "empty_text") { return "Type an address first."; }
    if (code === "text_too_long") { return "That is too long for the demo (500 characters at most)."; }
    if (status === 413) { return "That is too large for the demo."; }
    if (status === 422) { return "The demo could not use that input."; }
    return "Something went wrong (HTTP " + status + "). Please try again.";
  }

  function formatMs(ms) {
    return ms < 1000 ? Math.round(ms) + " ms" : (ms / 1000).toFixed(1) + " s";
  }

  /* Which parts were found and how many of each, in the fixed label order. Counted from the
     same runs the page highlights, so the legend can never disagree with the highlighting. */
  function labelCounts(text, entities) {
    var counts = {};
    segments(text, entities).forEach(function (s) {
      if (s.label) { counts[s.label] = (counts[s.label] || 0) + 1; }
    });
    return LABELS.filter(function (label) { return counts[label]; }).map(function (label) {
      return { label: label, name: NAMES[label], count: counts[label] };
    });
  }

  /* The fields as plain text for the clipboard: "House: House 12" per line. */
  function summaryText(fields) {
    return fieldRows(fields).map(function (row) {
      return row.name + ": " + row.values.join(", ");
    }).join("\n");
  }

  /* "" while there is room, "near" in the last tenth, "full" at the limit. */
  function counterState(used, max) {
    if (used >= max) { return "full"; }
    return used >= Math.floor(max * 0.9) ? "near" : "";
  }

  /* The example after `current` in the list, wrapping round; the first one if `current` is
     not an example (for instance, the person has typed their own text). */
  function cycleExample(examples, current) {
    if (!examples.length) { return ""; }
    return examples[(examples.indexOf(current) + 1) % examples.length];
  }

  /* How long the page keeps asking before it gives up on a server that is waking from sleep.
     Measured, not guessed: the image under a 0.1 CPU limit (what a free host gives) took 50 to
     127 seconds to become ready, and Render's own docs say a wake takes "about one minute".
     60 attempts x 4 s = 4 minutes covers the worst case seen with margin. One definition, tested
     (tests/js/render.test.cjs), so shortening it again cannot happen by accident. */
  var WAKE_ATTEMPTS = 60;
  var WAKE_DELAY_MS = 4000;

  /* Ask for the model until it answers, retrying on any failure: a 503 (not loaded yet), any
     other non-OK status, a network error, or an unreadable body. Everything it needs is passed
     in (fetchModel, sleep) so it can be tested without a browser or a clock.
       opts.fetchModel() -> Promise of a Response-like {ok, json()}
       opts.sleep(ms)    -> Promise
       opts.onWait(n, total, elapsedMs) -> called before each pause, for the status line */
  async function connectWithRetry(opts) {
    var attempts = opts.attempts || WAKE_ATTEMPTS;
    var delayMs = opts.delayMs === undefined ? WAKE_DELAY_MS : opts.delayMs;
    for (var attempt = 1; attempt <= attempts; attempt++) {
      try {
        var response = await opts.fetchModel();
        if (response.ok) { return { ok: true, info: await response.json(), attempts: attempt }; }
      } catch (failure) { /* the host may be waking up: fall through and try again */ }
      if (attempt < attempts) {
        if (opts.onWait) { opts.onWait(attempt, attempts, attempt * delayMs); }
        await opts.sleep(delayMs);
      }
    }
    return { ok: false, attempts: attempts };
  }

  /* ---- files: read a table, pick the address column, send in groups, write a CSV back ----
     Everything here runs in the browser. The only thing that leaves it is the address text of each
     row, sent to this site's own batch endpoint a few at a time, exactly as if it had been typed. */

  var COLUMNS = LABELS.map(function (label) { return label.toLowerCase(); });
  var FILE_LIMITS = { MAX_FILES: 5, MAX_ROWS: 500, MAX_BYTES: 2 * 1024 * 1024 };
  // Used until the server says what it accepts (GET /api/v1/model "limits"), and by an older server
  // that does not say. They are the public deployment's values, the strictest this project ships.
  var FALLBACK_LIMITS = { max_batch: 10, max_text_chars: 500, max_body_bytes: 64 * 1024 };
  var CONTROL = /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g;   // the server rejects these: they are not text
  var ADDRESS_WORDS = /address|addr|location|thikana|ঠিকানা/i;
  var HEADER_WORDS = /^(id|name|phone|mobile|email|sl|serial|no|customer|order)\b/i;

  /* Rows of cells from CSV-style text (RFC 4180: quoted cells may hold the delimiter, quotes ("")
     and line breaks). A byte-order mark is dropped and blank lines are skipped. `unterminated` is
     true when a quote is never closed, because the rest of the file then ends up in one cell. */
  function parseDelimited(text, delimiter) {
    if (text.charCodeAt(0) === 0xFEFF) { text = text.slice(1); }
    var rows = [], row = [], cell = "", quoted = false, started = false, i = 0;
    function endRow() {
      row.push(cell);
      if (row.length > 1 || row[0] !== "") { rows.push(row); }
      row = []; cell = ""; started = false;
    }
    while (i < text.length) {
      var c = text[i];
      if (quoted) {
        if (c === '"' && text[i + 1] === '"') { cell += '"'; i += 2; continue; }
        if (c === '"') { quoted = false; i++; continue; }
        cell += c; i++; continue;
      }
      if (c === '"' && cell === "") { quoted = true; started = true; i++; continue; }
      if (c === delimiter) { row.push(cell); cell = ""; started = true; i++; continue; }
      if (c === "\r" || c === "\n") {
        if (c === "\r" && text[i + 1] === "\n") { i++; }
        i++; endRow(); continue;
      }
      cell += c; i++;
    }
    var unterminated = quoted;
    if (cell !== "" || started) { endRow(); }
    return { rows: rows, unterminated: unterminated };
  }

  /* The delimiter a CSV-like file uses, taken from its first non-blank line. */
  function detectDelimiter(text) {
    var line = text.replace(/^﻿/, "").split(/\r\n|\r|\n/).filter(function (l) { return l.trim() !== ""; })[0] || "";
    var best = ",", bestCount = 0;
    [",", "\t", ";"].forEach(function (d) {
      var count = line.split(d).length - 1;
      if (count > bestCount) { best = d; bestCount = count; }
    });
    return best;
  }

  /* A file's text as a table. A .txt file is one address per line; .tsv is tab-separated; anything
     else is read as CSV with the delimiter detected. */
  function readTable(text, filename) {
    var lower = (filename || "").toLowerCase();
    var rows, unterminated = false;
    if (/\.txt$/.test(lower)) {
      rows = text.replace(/^﻿/, "").split(/\r\n|\r|\n/).map(function (l) { return l.trim(); })
        .filter(function (l) { return l !== ""; }).map(function (l) { return [l]; });
    } else {
      var parsed = parseDelimited(text, /\.tsv$/.test(lower) ? "\t" : detectDelimiter(text));
      rows = parsed.rows; unterminated = parsed.unterminated;
    }
    var widths = rows.map(function (r) { return r.length; });
    var columns = widths.length ? Math.max.apply(null, widths) : 0;
    var ragged = widths.some(function (w) { return w !== widths[0]; });
    return { rows: rows, columns: columns, ragged: ragged, unterminated: unterminated, lines: /\.txt$/.test(lower) };
  }

  function hasDigit(cell) { return /[0-9০-৯]/.test(cell); }

  /* Is the first row column names rather than data? Known words ("address", "ঠিকানা", "id"...) say yes.
     Otherwise it is a header only when there are several columns, the first row has no digit and a later
     row does: addresses carry house numbers and postcodes, column names never do. Wrongly dropping a
     real first address is worse than keeping a header as a row, so doubt means "no header". */
  function guessHasHeader(table) {
    if (table.rows.length < 2 || table.lines) { return false; }
    var first = table.rows[0];
    if (first.some(function (c) { return ADDRESS_WORDS.test(c) || HEADER_WORDS.test(c.trim()); })) { return true; }
    return table.columns > 1 && !first.some(hasDigit) &&
           table.rows.slice(1, 21).some(function (row) { return row.some(hasDigit); });
  }

  /* Which column holds the address: one named like an address; else the column whose cells are longest
     on average. With no header, rows of different lengths, or three or more columns that are all short,
     look like ONE address split on its commas, so -1: "join every cell of the row". */
  function guessColumn(table, hasHeader) {
    var data = table.rows.slice(hasHeader ? 1 : 0, (hasHeader ? 1 : 0) + 50);
    if (hasHeader) {
      for (var h = 0; h < table.rows[0].length; h++) { if (ADDRESS_WORDS.test(table.rows[0][h])) { return h; } }
    }
    if (table.columns <= 1) { return 0; }
    if (table.ragged) { return -1; }
    var best = 0, bestLength = -1;
    for (var col = 0; col < table.columns; col++) {
      var total = 0;
      data.forEach(function (r) { total += Array.from(r[col] || "").length; });
      var mean = data.length ? total / data.length : 0;
      if (mean > bestLength) { best = col; bestLength = mean; }
    }
    if (!hasHeader && table.columns >= 3 && bestLength < 20) { return -1; }
    return best;
  }

  /* One entry per data row, in order. `send` is the text to parse (control characters turned into
     spaces, trimmed) or null when the row is not sent: "empty" or "too_long" (code points, as the
     server counts them). `text` keeps the cell exactly as the file had it. */
  function prepareItems(dataRows, column, limits) {
    return dataRows.map(function (cells) {
      var raw = column < 0
        ? cells.map(function (c) { return c.trim(); }).filter(function (c) { return c !== ""; }).join(", ")
        : (cells[column] || "");
      var clean = raw.replace(CONTROL, " ").trim();
      if (!clean) { return { text: raw, send: null, status: "empty" }; }
      if (Array.from(clean).length > limits.max_text_chars) { return { text: raw, send: null, status: "too_long" }; }
      return { text: raw, send: clean, status: "ok" };
    });
  }

  function utf8Length(text) { return new TextEncoder().encode(text).length; }

  /* Group indexes of `texts` into requests that fit the server: at most `maxBatch` addresses and
     under three quarters of the body limit (headroom for the JSON around them). A text that is too
     big on its own still gets a request of its own, so no index is ever dropped. */
  function makeChunks(texts, maxBatch, maxBytes) {
    var budget = Math.floor(maxBytes * 0.75) - 32;
    var chunks = [], current = [], bytes = 0;
    texts.forEach(function (text, index) {
      var size = utf8Length(JSON.stringify(text)) + 1;
      if (current.length && (current.length >= maxBatch || bytes + size > budget)) {
        chunks.push(current); current = []; bytes = 0;
      }
      current.push(index); bytes += size;
    });
    if (current.length) { chunks.push(current); }
    return chunks;
  }

  var RETRIES = { rateLimited: 8, notReady: 8, network: 3 };

  function clampWait(seconds) {
    var n = Number(seconds);
    return Math.min(30, Math.max(1, isFinite(n) && n > 0 ? n : 2));
  }

  /* Send one group, waiting and retrying where waiting can help: 429 (the site's request limit:
     wait as long as it says), 503 (the model is still loading) and a dropped connection. Any other
     answer is final for this group. io.send(texts) -> {status, body, retryAfter}, or throws. */
  async function sendChunk(texts, io) {
    var limited = 0, notReady = 0, dropped = 0;
    for (;;) {
      if (io.cancelled()) { return { ok: false, reason: "cancelled" }; }
      var res = null;
      try { res = await io.send(texts); } catch (failure) { res = null; }
      if (res && res.status === 200) {
        var results = res.body && res.body.results;
        return Array.isArray(results) && results.length === texts.length
          ? { ok: true, results: results } : { ok: false, reason: "bad_response" };
      }
      if (res && res.status === 429) {
        if (++limited > RETRIES.rateLimited) { return { ok: false, reason: "rate_limited" }; }
        await io.sleep(clampWait(res.retryAfter) * 1000); continue;
      }
      if (res && res.status === 503) {
        if (++notReady > RETRIES.notReady) { return { ok: false, reason: "not_ready" }; }
        await io.sleep(4000); continue;
      }
      if (!res) {
        if (++dropped > RETRIES.network) { return { ok: false, reason: "network" }; }
        await io.sleep(2000); continue;
      }
      return { ok: false, reason: "rejected" };
    }
  }

  /* Parse every sendable item, group by group. Returns one outcome per item, in order:
     status "ok" (with `fields`), "empty", "too_long", "error" (with `reason`) or "not_run" (cancelled,
     or stopped after three groups in a row failed, which means waiting longer will not help). */
  async function parseItems(items, limits, io) {
    var texts = [], index = [];
    items.forEach(function (item, i) { if (item.status === "ok") { index.push(i); texts.push(item.send); } });
    var chunks = makeChunks(texts, limits.max_batch, limits.max_body_bytes);
    var outcomes = items.map(function (item) {
      return { status: item.status === "ok" ? "not_run" : item.status, fields: null };
    });
    var done = 0, strikes = 0, cancelled = false, aborted = false;
    for (var c = 0; c < chunks.length; c++) {
      var chunk = chunks[c];
      var sent = await sendChunk(chunk.map(function (k) { return texts[k]; }), io);
      if (sent.reason === "cancelled") { cancelled = true; break; }
      chunk.forEach(function (k, j) {
        var outcome = outcomes[index[k]];
        if (sent.ok) { outcome.status = "ok"; outcome.fields = sent.results[j].fields || {}; }
        else { outcome.status = "error"; outcome.reason = sent.reason; }
      });
      strikes = sent.ok ? 0 : strikes + 1;
      done += chunk.length;
      if (io.onProgress) { io.onProgress(done, texts.length); }
      if (strikes >= 3) { aborted = true; break; }
    }
    return { outcomes: outcomes, cancelled: cancelled, aborted: aborted };
  }

  /* Counts for the line under a file: how many rows were parsed, found no parts, were skipped, failed. */
  function summarise(outcomes) {
    var s = { total: outcomes.length, parsed: 0, noParts: 0, empty: 0, tooLong: 0, failed: 0, notRun: 0 };
    outcomes.forEach(function (o) {
      if (o.status === "ok") { if (fieldRows(o.fields).length) { s.parsed++; } else { s.noParts++; } }
      else if (o.status === "empty") { s.empty++; }
      else if (o.status === "too_long") { s.tooLong++; }
      else if (o.status === "error") { s.failed++; }
      else { s.notRun++; }
    });
    return s;
  }

  /* The word written in parse_status. A failed row says why: error_network, error_rate_limited,
     error_not_ready, error_rejected or error_bad_response. */
  function statusWord(outcome) {
    if (outcome.status === "ok") { return fieldRows(outcome.fields).length ? "ok" : "no_parts_found"; }
    if (outcome.status === "error") { return "error_" + (outcome.reason || "unknown"); }
    return outcome.status;
  }

  /* A cell that starts with = + - or @ is read by a spreadsheet as a formula, and the file may have come
     from anywhere. Prefix an apostrophe, except for plain numbers and phone numbers (digits, spaces,
     dots, commas, hyphens, brackets), which cannot form a function call. */
  function neutralise(value) {
    if (/^[=+\-@\t\r]/.test(value) && !/^[+-]?\d[\d\s.,()\-]*$/.test(value)) { return "'" + value; }
    return value;
  }

  function csvCell(value) {
    var s = neutralise(value === null || value === undefined ? "" : String(value));
    return /[",\r\n]|^\s|\s$/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }

  function toCsv(rows) {
    return rows.map(function (r) { return r.map(csvCell).join(","); }).join("\r\n") + "\r\n";
  }

  function padRow(cells, width) {
    var out = cells.slice(0, width);
    while (out.length < width) { out.push(""); }
    return out;
  }

  /* The CSV to give back: every original column as it was, then parsed_house ... parsed_landmark
     (several values of one kind joined with " | ") and parse_status. The prefix keeps a new column from
     clashing with one the file already has ("district"). */
  function outputRows(table, hasHeader, dataRows, outcomes) {
    var width = Math.max(table.columns, 1), names = [];
    for (var i = 0; i < width; i++) { names.push(table.lines ? "address" : "column_" + (i + 1)); }
    var header = hasHeader ? padRow(table.rows[0], width) : names;
    var out = [header.concat(COLUMNS.map(function (c) { return "parsed_" + c; }), ["parse_status"])];
    dataRows.forEach(function (cells, r) {
      var fields = outcomes[r].fields || {};
      var parts = COLUMNS.map(function (c) { return (fields[c] || []).join(" | "); });
      out.push(padRow(cells, width).concat(parts, [statusWord(outcomes[r])]));
    });
    return out;
  }

  /* The same results as JSON: one object per row, with the text that was parsed. */
  function outputJson(items, outcomes) {
    return items.map(function (item, r) {
      return { row: r + 1, input: item.text, status: statusWord(outcomes[r]), fields: outcomes[r].fields || {} };
    });
  }

  /* "customers.csv" -> "customers_parsed.csv". Keeps Bangla letters; never a path. */
  function downloadName(filename, extension) {
    var base = String(filename || "").split(/[\\/]/).pop().replace(/\.[^.]*$/, "")
      .replace(/[^\wঀ-৿.-]+/g, "_").replace(/^[._-]+|[._-]+$/g, "").slice(0, 60);
    return (base || "addresses") + "_parsed." + extension;
  }

  var SAMPLE_CSV = toCsv([
    ["id", "name", "address"],
    ["1", "Sample A", "House 12, Road 5, Mirpur-10, Dhaka-1216"],
    ["2", "Sample B", "বাসা ১২, রোড ৫, ধানমন্ডি, ঢাকা-১২০৫"],
    ["3", "Sample C", "Flat 4B, House 7, Block C, Road 3, Banani, Dhaka 1213"],
    ["4", "Sample D", "Vill: Kaunia, P.O: Kaunia, Thana: Kaunia, Dist: Rangpur"],
    ["5", "Sample E", "Zindabazar, Sylhet Sadar, Sylhet 3100"],
    ["6", "Sample F", "বুধড়া, গুনবতী, বগুড়া"]
  ]);

  var api = {
    LABELS: LABELS, NAMES: NAMES, WAKE_ATTEMPTS: WAKE_ATTEMPTS, WAKE_DELAY_MS: WAKE_DELAY_MS,
    segments: segments, fieldRows: fieldRows, describeError: describeError, formatMs: formatMs,
    labelCounts: labelCounts, summaryText: summaryText, counterState: counterState, cycleExample: cycleExample,
    connectWithRetry: connectWithRetry,
    COLUMNS: COLUMNS, FILE_LIMITS: FILE_LIMITS, FALLBACK_LIMITS: FALLBACK_LIMITS, SAMPLE_CSV: SAMPLE_CSV,
    parseDelimited: parseDelimited, detectDelimiter: detectDelimiter, readTable: readTable,
    guessHasHeader: guessHasHeader, guessColumn: guessColumn, prepareItems: prepareItems,
    makeChunks: makeChunks, sendChunk: sendChunk, parseItems: parseItems, summarise: summarise,
    neutralise: neutralise, csvCell: csvCell, toCsv: toCsv, outputRows: outputRows, outputJson: outputJson,
    downloadName: downloadName
  };
  if (typeof module === "object" && module.exports) { module.exports = api; } else { root.Thikana = api; }
})(typeof globalThis !== "undefined" ? globalThis : this);
