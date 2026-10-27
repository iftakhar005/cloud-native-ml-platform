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

  var api = {
    LABELS: LABELS, NAMES: NAMES, WAKE_ATTEMPTS: WAKE_ATTEMPTS, WAKE_DELAY_MS: WAKE_DELAY_MS,
    segments: segments, fieldRows: fieldRows, describeError: describeError, formatMs: formatMs,
    connectWithRetry: connectWithRetry
  };
  if (typeof module === "object" && module.exports) { module.exports = api; } else { root.Thikana = api; }
})(typeof globalThis !== "undefined" ? globalThis : this);
