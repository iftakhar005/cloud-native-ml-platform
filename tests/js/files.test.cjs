// Unit tests for the file-upload half of thikana/web/render.js, run with:
//   node --test tests/js/files.test.cjs
// (tests/test_web.py runs this from pytest and skips it when Node is not installed.)
const test = require("node:test");
const assert = require("node:assert/strict");
const T = require("../../thikana/web/render.js");

const LIMITS = { max_batch: 3, max_text_chars: 50, max_body_bytes: 64 * 1024 };

// ---- reading a table ------------------------------------------------------------------------

test("a quoted cell may hold the delimiter, a doubled quote and a line break", () => {
  const { rows, unterminated } = T.parseDelimited('id,address\r\n1,"House 12, Road 5"\r\n2,"say ""hi""\nsecond line"\r\n', ",");
  assert.deepEqual(rows, [["id", "address"], ["1", "House 12, Road 5"], ["2", 'say "hi"\nsecond line']]);
  assert.equal(unterminated, false);
});

test("a byte-order mark, blank lines and a missing final newline are all fine", () => {
  const { rows } = T.parseDelimited("\uFEFFa,b\n\n1,2\n\n3,4", ",");
  assert.deepEqual(rows, [["a", "b"], ["1", "2"], ["3", "4"]]);
});

test("empty cells are kept, so columns stay aligned", () => {
  assert.deepEqual(T.parseDelimited("a,,c\n,,\n1,2,3\n", ",").rows, [["a", "", "c"], ["", "", ""], ["1", "2", "3"]]);
});

test("a quote that is never closed is reported, not silently swallowed", () => {
  const parsed = T.parseDelimited('a,b\n1,"never closed\n2,3\n', ",");
  assert.equal(parsed.unterminated, true);
  assert.equal(parsed.rows.length, 2);
});

test("the delimiter is the commonest of comma, tab and semicolon on the first line", () => {
  assert.equal(T.detectDelimiter("a,b,c\n1,2,3"), ",");
  assert.equal(T.detectDelimiter("a\tb\tc\n1\t2\t3"), "\t");
  assert.equal(T.detectDelimiter("a;b;c\n1;2;3"), ";");
  assert.equal(T.detectDelimiter("just one column\nanother"), ",");
});

test("a .txt file is one address per line, whatever commas it holds", () => {
  const table = T.readTable("\uFEFFHouse 12, Road 5, Dhaka\r\n\r\n  Zindabazar, Sylhet  \n", "list.txt");
  assert.deepEqual(table.rows, [["House 12, Road 5, Dhaka"], ["Zindabazar, Sylhet"]]);
  assert.equal(table.columns, 1);
  assert.equal(table.lines, true);
});

test("a .tsv file splits on tabs only", () => {
  const table = T.readTable("id\taddress\n1\tHouse 12, Road 5\n", "x.tsv");
  assert.deepEqual(table.rows[1], ["1", "House 12, Road 5"]);
});

test("a header row is recognised by its words, or by being digit-free above rows that have digits", () => {
  const named = T.readTable("id,address\n1,House 12\n", "a.csv");
  assert.equal(T.guessHasHeader(named), true);
  assert.equal(T.guessHasHeader(T.readTable("ঠিকানা\nবাসা ১২, ঢাকা\n", "b.csv")), true);
  assert.equal(T.guessHasHeader(T.readTable("who,where\nA,Dhaka 1205\n", "c.csv")), true);
  // doubt means no header: dropping a real first address is worse than keeping a header as a row
  assert.equal(T.guessHasHeader(T.readTable("কাহালু, বগুড়া\nসাভার, ঢাকা\n", "c2.csv")), false);
  assert.equal(T.guessHasHeader(T.readTable("who,where\nA,Dhaka\n", "c3.csv")), false);
  // data, not a header: a digit in the first row, a single column, or a text file
  assert.equal(T.guessHasHeader(T.readTable("1,House 12, Road 5\n2,House 3, Road 1\n", "d.csv")), false);
  assert.equal(T.guessHasHeader(T.readTable("Zindabazar, Sylhet\nMirpur, Dhaka\n", "e.txt")), false);
  assert.equal(T.guessHasHeader(T.readTable('"Zindabazar, Sylhet"\n"Mirpur, Dhaka"\n', "f.csv")), false);
});

test("the address column is the one named like an address, else the longest, else the whole line", () => {
  const named = T.readTable("id,place,address\n1,x,House 12, Road 5\n", "a.csv");
  assert.equal(T.guessColumn(T.readTable("id,place,address\n1,x,y\n", "a.csv"), true), 2);
  assert.equal(named.ragged, true);

  const longest = T.readTable("a,b\n1,House 12 Road 5 Mirpur Dhaka\n2,House 3 Road 1 Banani Dhaka\n", "b.csv");
  assert.equal(T.guessColumn(longest, true), 1);

  // an UNQUOTED address in a .csv is split on its commas into rows of different lengths
  const unquoted = T.readTable("House 12, Road 5, Mirpur, Dhaka\nZindabazar, Sylhet\n", "c.csv");
  assert.equal(unquoted.ragged, true);
  assert.equal(T.guessColumn(unquoted, false), -1);

  // ...and so does an unquoted address list where every row happens to have the same number of parts
  const even = T.readTable("House 1, Road 5, Mirpur-10, Dhaka-1216\nHouse 2, Road 6, Mirpur-11, Dhaka-1216\n", "e.csv");
  assert.equal(even.ragged, false);
  assert.equal(T.guessColumn(even, T.guessHasHeader(even)), -1);

  // but a headerless two-column file with a long text column keeps that column
  const pairs = T.readTable("1,House 12 Road 5 Mirpur-10 Dhaka-1216\n2,House 3 Road 1 Banani Dhaka-1213\n", "f.csv");
  assert.equal(T.guessColumn(pairs, false), 1);

  assert.equal(T.guessColumn(T.readTable("only\nthis\n", "d.csv"), false), 0);
});

// ---- preparing rows -------------------------------------------------------------------------

test("each row becomes sendable, empty or too long; control characters become spaces", () => {
  const rows = [["House 12, Dhaka"], ["   "], ["x".repeat(51)], ["a\u0000b\u0007c"], [""]];
  const items = T.prepareItems(rows, 0, LIMITS);
  assert.deepEqual(items.map((i) => i.status), ["ok", "empty", "too_long", "ok", "empty"]);
  assert.equal(items[0].send, "House 12, Dhaka");
  assert.equal(items[3].send, "a b c");
  assert.equal(items[3].text, "a\u0000b\u0007c");                 // the original cell is kept as it was
});

test("length is counted in code points, as the server counts it", () => {
  const fifty = "ক".repeat(50);        // 50 characters, 150 UTF-8 bytes
  assert.equal(T.prepareItems([[fifty]], 0, LIMITS)[0].status, "ok");
  assert.equal(T.prepareItems([[fifty + "ক"]], 0, LIMITS)[0].status, "too_long");
  const emoji = "\u{1F3E0}".repeat(50);   // 100 UTF-16 units, but 50 code points
  assert.equal(T.prepareItems([[emoji]], 0, LIMITS)[0].status, "ok");
});

test("column -1 joins the non-empty cells of a row", () => {
  const items = T.prepareItems([["House 12", " Road 5", "", "Dhaka"]], -1, LIMITS);
  assert.equal(items[0].send, "House 12, Road 5, Dhaka");
});

// ---- grouping -------------------------------------------------------------------------------

test("groups never exceed the batch size and never lose or repeat an index", () => {
  const texts = Array.from({ length: 10 }, (_, i) => "address " + i);
  const chunks = T.makeChunks(texts, 3, 64 * 1024);
  assert.deepEqual(chunks.map((c) => c.length), [3, 3, 3, 1]);
  assert.deepEqual(chunks.flat(), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
});

test("groups also stay under the body limit, counting UTF-8 bytes", () => {
  const texts = Array.from({ length: 6 }, () => "ক".repeat(100));         // 300+ bytes each
  const maxBytes = 1400;                                                   // budget 1018 bytes: three per group
  const chunks = T.makeChunks(texts, 100, maxBytes);
  assert.deepEqual(chunks.map((c) => c.length), [3, 3]);
  chunks.forEach((chunk) => {
    const body = JSON.stringify({ texts: chunk.map((i) => texts[i]) });
    assert.ok(new TextEncoder().encode(body).length <= maxBytes);
  });
});

test("a text too big for any group still gets one of its own", () => {
  const chunks = T.makeChunks(["short", "x".repeat(5000), "short"], 10, 1024);
  assert.deepEqual(chunks, [[0], [1], [2]]);
});

// ---- sending --------------------------------------------------------------------------------

function fakeIo(answers, extra) {
  const calls = [], sleeps = [];
  const io = Object.assign({
    send: async (texts) => {
      calls.push(texts);
      const next = answers.length > 1 ? answers.shift() : answers[0];
      if (next instanceof Error) { throw next; }
      return typeof next === "function" ? next(texts) : next;
    },
    sleep: async (ms) => { sleeps.push(ms); },
    cancelled: () => false,
  }, extra);
  return { io, calls, sleeps };
}
const okAnswer = (texts) => ({ status: 200, body: { results: texts.map((t) => ({ fields: { area: [t] } })) } });

test("a 429 waits as long as the server says (within bounds) and then succeeds", async () => {
  const { io, calls, sleeps } = fakeIo([{ status: 429, retryAfter: "5" }, { status: 429, retryAfter: "500" }, { status: 429, retryAfter: null }, okAnswer]);
  const sent = await T.sendChunk(["a", "b"], io);
  assert.equal(sent.ok, true);
  assert.equal(calls.length, 4);
  assert.deepEqual(sleeps, [5000, 30000, 2000]);                // 500 is clamped to 30 s, a missing header to 2 s
});

test("a 429 that never clears gives up after a bounded number of waits", async () => {
  const { io, calls } = fakeIo([{ status: 429, retryAfter: "1" }]);
  const sent = await T.sendChunk(["a"], io);
  assert.deepEqual(sent, { ok: false, reason: "rate_limited" });
  assert.equal(calls.length, 9);
});

test("503 (model still loading) and a dropped connection are retried; a refusal is not", async () => {
  let r = await T.sendChunk(["a"], fakeIo([{ status: 503 }, okAnswer]).io);
  assert.equal(r.ok, true);
  r = await T.sendChunk(["a"], fakeIo([new Error("offline"), okAnswer]).io);
  assert.equal(r.ok, true);
  const refused = fakeIo([{ status: 422, body: { error: { code: "empty_text" } } }]);
  assert.deepEqual(await T.sendChunk(["a"], refused.io), { ok: false, reason: "rejected" });
  assert.equal(refused.calls.length, 1);
  const down = fakeIo([new Error("offline")]);
  assert.deepEqual(await T.sendChunk(["a"], down.io), { ok: false, reason: "network" });
  assert.equal(down.calls.length, 4);
});

test("an answer with the wrong number of results is never trusted", async () => {
  const { io } = fakeIo([{ status: 200, body: { results: [] } }]);
  assert.deepEqual(await T.sendChunk(["a", "b"], io), { ok: false, reason: "bad_response" });
});

test("every row gets exactly one outcome, in order, skipped rows included", async () => {
  const items = T.prepareItems([["one"], [""], ["two"], ["x".repeat(99)], ["three"], ["four"]], 0, LIMITS);
  const { io, calls } = fakeIo([okAnswer]);
  const out = await T.parseItems(items, LIMITS, io);
  assert.deepEqual(calls, [["one", "two", "three"], ["four"]]);
  assert.deepEqual(out.outcomes.map((o) => o.status), ["ok", "empty", "ok", "too_long", "ok", "ok"]);
  assert.deepEqual(out.outcomes[2].fields, { area: ["two"] });
  assert.equal(out.cancelled, false);
  assert.equal(out.aborted, false);
});

test("three failed groups in a row stop the run and leave the rest as not_run", async () => {
  const items = T.prepareItems(Array.from({ length: 15 }, (_, i) => ["row " + i]), 0, LIMITS);   // five groups of three
  const { io, calls } = fakeIo([{ status: 422 }]);
  const out = await T.parseItems(items, LIMITS, io);
  assert.equal(calls.length, 3);
  assert.equal(out.aborted, true);
  assert.deepEqual(out.outcomes.map((o) => o.status).slice(0, 9), Array(9).fill("error"));
  assert.deepEqual(out.outcomes.map((o) => o.status).slice(9), Array(6).fill("not_run"));
});

test("stopping part-way keeps what was parsed and marks the rest not_run", async () => {
  const items = T.prepareItems(Array.from({ length: 9 }, (_, i) => ["row " + i]), 0, LIMITS);
  let groups = 0;
  const { io } = fakeIo([(texts) => { groups++; return okAnswer(texts); }], { cancelled: () => groups >= 1 });
  const out = await T.parseItems(items, LIMITS, io);
  assert.equal(out.cancelled, true);
  assert.deepEqual(out.outcomes.map((o) => o.status), Array(3).fill("ok").concat(Array(6).fill("not_run")));
  const s = T.summarise(out.outcomes);
  assert.deepEqual([s.parsed, s.notRun, s.total], [3, 6, 9]);
});

test("progress is reported after each group", async () => {
  const items = T.prepareItems(Array.from({ length: 7 }, (_, i) => ["row " + i]), 0, LIMITS);
  const seen = [];
  const { io } = fakeIo([okAnswer], { onProgress: (done, total) => seen.push([done, total]) });
  await T.parseItems(items, LIMITS, io);
  assert.deepEqual(seen, [[3, 7], [6, 7], [7, 7]]);
});

// ---- writing the CSV ------------------------------------------------------------------------

test("a cell a spreadsheet would run as a formula is defused; numbers and phone numbers are left alone", () => {
  assert.equal(T.neutralise('=HYPERLINK("http-evil","x")'), "'=HYPERLINK(\"http-evil\",\"x\")");
  assert.equal(T.neutralise("@SUM(A1)"), "'@SUM(A1)");
  assert.equal(T.neutralise("+cmd|' /C calc'!A0"), "'+cmd|' /C calc'!A0");
  assert.equal(T.neutralise("-2+3+cmd"), "'-2+3+cmd");
  assert.equal(T.neutralise("+880 1712-345678"), "+880 1712-345678");
  assert.equal(T.neutralise("-12.5"), "-12.5");
  assert.equal(T.neutralise("House 12"), "House 12");
  assert.equal(T.neutralise("বাসা ১২"), "বাসা ১২");
});

test("CSV cells are quoted exactly when they need to be, and lines end with CRLF", () => {
  assert.equal(T.csvCell("plain"), "plain");
  assert.equal(T.csvCell("a,b"), '"a,b"');
  assert.equal(T.csvCell('say "hi"'), '"say ""hi"""');
  assert.equal(T.csvCell("two\nlines"), '"two\nlines"');
  assert.equal(T.csvCell(" padded "), '" padded "');
  assert.equal(T.csvCell(null), "");
  assert.equal(T.toCsv([["a", "b,c"], ["1", "2"]]), 'a,"b,c"\r\n1,2\r\n');
});

test("what is written can be read back to the same cells", () => {
  const rows = [["id", "text"], ["1", 'He said "no", then left\nat 5'], ["2", " spaced "], ["3", "বাসা ১২, ঢাকা"]];
  assert.deepEqual(T.parseDelimited(T.toCsv(rows), ",").rows, rows);
});

test("the output keeps every original column and adds parsed_ columns and a status", () => {
  const table = T.readTable("id,address\n1,House 12\n2,\n3,Nowhere\n4,Mirpur\n", "a.csv");
  const rows = T.prepareItems(table.rows.slice(1), 1, LIMITS);
  const outcomes = [
    { status: "ok", fields: { house: ["House 12"], area: ["Mirpur", "Dhaka"] } },
    { status: "empty", fields: null },
    { status: "ok", fields: {} },
    { status: "error", reason: "network", fields: null },
  ];
  const out = T.outputRows(table, true, table.rows.slice(1), outcomes);
  assert.deepEqual(out[0], ["id", "address", ...T.COLUMNS.map((c) => "parsed_" + c), "parse_status"]);
  assert.equal(out.length, 5);
  assert.deepEqual(out[1].slice(0, 2), ["1", "House 12"]);
  assert.equal(out[1][2 + T.COLUMNS.indexOf("house")], "House 12");
  assert.equal(out[1][2 + T.COLUMNS.indexOf("area")], "Mirpur | Dhaka");      // several values of one kind
  assert.deepEqual(out.map((r) => r[r.length - 1]).slice(1), ["ok", "empty", "no_parts_found", "error_network"]);
  assert.equal(rows.length, 4);
});

test("a file with no header gets column_1.. names, a text file gets 'address', short rows are padded", () => {
  const csv = T.readTable("a,b,c\nd,e\n", "x.csv");
  const first = T.outputRows(csv, false, csv.rows, [{ status: "empty" }, { status: "empty" }]);
  assert.deepEqual(first[0].slice(0, 3), ["column_1", "column_2", "column_3"]);
  assert.deepEqual(first[2].slice(0, 3), ["d", "e", ""]);
  const txt = T.readTable("Mirpur, Dhaka\n", "x.txt");
  assert.equal(T.outputRows(txt, false, txt.rows, [{ status: "empty" }])[0][0], "address");
});

test("the JSON has one object per row, with the text that was parsed", () => {
  const items = [{ text: "House 12", status: "ok" }, { text: "", status: "empty" }];
  const json = T.outputJson(items, [{ status: "ok", fields: { house: ["House 12"] } }, { status: "empty", fields: null }]);
  assert.deepEqual(json, [
    { row: 1, input: "House 12", status: "ok", fields: { house: ["House 12"] } },
    { row: 2, input: "", status: "empty", fields: {} },
  ]);
});

test("a failed row says why in both the CSV status and the JSON", () => {
  const items = [{ text: "House 12", status: "ok" }];
  const outcomes = [{ status: "error", reason: "rate_limited", fields: null }];
  assert.equal(T.outputJson(items, outcomes)[0].status, "error_rate_limited");
  assert.equal(T.outputRows(T.readTable("House 12\n", "a.txt"), false, [["House 12"]], outcomes)[1].pop(), "error_rate_limited");
  assert.equal(T.outputJson(items, [{ status: "error", fields: null }])[0].status, "error_unknown");
});

test("the download name is the file's own name plus _parsed, never a path", () => {
  assert.equal(T.downloadName("customers.csv", "csv"), "customers_parsed.csv");
  assert.equal(T.downloadName("C:\\Users\\me\\my addresses (1).txt", "json"), "my_addresses_1_parsed.json");
  assert.equal(T.downloadName("../../etc/passwd", "csv"), "passwd_parsed.csv");
  assert.equal(T.downloadName("ঠিকানা.csv", "csv"), "ঠিকানা_parsed.csv");
  assert.equal(T.downloadName("", "csv"), "addresses_parsed.csv");
  assert.ok(T.downloadName("a".repeat(300) + ".csv", "csv").length < 80);
});

test("the sample file reads back as a header and an address column, and its rows all fit", () => {
  const table = T.readTable(T.SAMPLE_CSV, "thikana_sample.csv");
  assert.equal(table.columns, 3);
  assert.equal(table.rows.length, 7);
  assert.equal(T.guessHasHeader(table), true);
  assert.equal(T.guessColumn(table, true), 2);
  const items = T.prepareItems(table.rows.slice(1), 2, T.FALLBACK_LIMITS);
  assert.deepEqual(items.map((i) => i.status), Array(6).fill("ok"));
});

test("the limits the page assumes without the server are the public deployment's", () => {
  assert.deepEqual(T.FALLBACK_LIMITS, { max_batch: 10, max_text_chars: 500, max_body_bytes: 65536 });
  assert.equal(T.FILE_LIMITS.MAX_ROWS, 500);
  assert.equal(T.FILE_LIMITS.MAX_FILES, 5);
});
