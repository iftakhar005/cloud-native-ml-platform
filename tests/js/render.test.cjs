// Unit tests for thikana/web/render.js, run with:  node --test tests/js/render.test.cjs
// (tests/test_web.py runs this from pytest and skips it when Node is not installed.)
const test = require("node:test");
const assert = require("node:assert/strict");
const T = require("../../thikana/web/render.js");

const join = (segs) => segs.map((s) => s.text).join("");

test("segments cover the text exactly, in order, with plain runs between entities", () => {
  const text = "House 12, Road 5, Dhaka";
  const segs = T.segments(text, [
    { label: "HOUSE", start: 0, end: 8 }, { label: "ROAD", start: 10, end: 16 }, { label: "DISTRICT", start: 18, end: 23 },
  ]);
  assert.deepEqual(segs, [
    { text: "House 12", label: "HOUSE" }, { text: ", ", label: null }, { text: "Road 5", label: "ROAD" },
    { text: ", ", label: null }, { text: "Dhaka", label: "DISTRICT" },
  ]);
  assert.equal(join(segs), text);
});

test("offsets are CODE POINTS: an emoji before the address must not shift the highlights", () => {
  // Python (and so the API) counts the emoji as ONE character. In a JavaScript string it is two
  // UTF-16 units, so text.slice(2, 8) would start one character late.
  const text = "\u{1F3E0} Road 5, Dhaka";
  const segs = T.segments(text, [{ label: "ROAD", start: 2, end: 8 }, { label: "DISTRICT", start: 10, end: 15 }]);
  assert.deepEqual(segs.filter((s) => s.label), [{ text: "Road 5", label: "ROAD" }, { text: "Dhaka", label: "DISTRICT" }]);
  assert.notEqual(text.slice(2, 8), "Road 5");                       // proof that the naive way is wrong
  assert.equal(join(segs), text);
});

test("Bangla text is sliced by code point, including combining signs", () => {
  const text = "বাসা ১২, ঢাকা";      // বাসা ১২, ঢাকা
  const chars = Array.from(text);
  const segs = T.segments(text, [{ label: "HOUSE", start: 0, end: 7 }, { label: "DISTRICT", start: 9, end: chars.length }]);
  assert.equal(segs[0].text, chars.slice(0, 7).join(""));
  assert.equal(join(segs), text);
});

test("an entity the API should never send is skipped, never invented or duplicated", () => {
  const text = "abcdef";
  const bad = [
    { label: "ROAD", start: -1, end: 2 }, { label: "ROAD", start: 2, end: 2 }, { label: "ROAD", start: 4, end: 9 },
    { label: "ROAD", start: 1.5, end: 3 }, { label: "ROAD", start: "1", end: 3 }, { label: "NOPE", start: 0, end: 2 },
    { label: "ROAD", start: 3, end: 1 }, null === 0 ? null : { start: 0, end: 2 },
  ];
  assert.deepEqual(T.segments(text, bad), [{ text, label: null }]);
  assert.deepEqual(T.segments(text, undefined), [{ text, label: null }]);
  assert.deepEqual(T.segments("", []), []);
});

test("overlapping entities keep the earlier, longer one and drop the rest", () => {
  const segs = T.segments("abcdef", [{ label: "AREA", start: 1, end: 4 }, { label: "ROAD", start: 2, end: 5 }, { label: "HOUSE", start: 4, end: 6 }]);
  assert.deepEqual(segs, [
    { text: "a", label: null }, { text: "bcd", label: "AREA" }, { text: "ef", label: "HOUSE" },
  ]);
});

test("entities given out of order are sorted", () => {
  const segs = T.segments("ab cd", [{ label: "ROAD", start: 3, end: 5 }, { label: "HOUSE", start: 0, end: 2 }]);
  assert.deepEqual(segs.map((s) => s.label), ["HOUSE", null, "ROAD"]);
});

test("PROPERTY: whatever junk is thrown in, the runs always join back to the original text", () => {
  let seed = 12345;                                           // fixed seed: the same cases every run
  const rand = (n) => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed % n; };
  const alphabet = ["a", "b", " ", ",", "\u{1F3E0}", "ঢ", "া", "1"];
  const labels = T.LABELS.concat(["BOGUS", "", undefined]);
  for (let round = 0; round < 400; round++) {
    const text = Array.from({ length: rand(30) }, () => alphabet[rand(alphabet.length)]).join("");
    const entities = Array.from({ length: rand(8) }, () => ({
      label: labels[rand(labels.length)], start: rand(40) - 5, end: rand(40) - 5,
    }));
    const segs = T.segments(text, entities);
    assert.equal(join(segs), text, `round ${round}`);
    segs.forEach((s) => assert.ok(s.text.length > 0, "no empty runs"));
  }
});

test("fieldRows returns the labels in a fixed order and omits the empty ones", () => {
  const rows = T.fieldRows({ district: ["Dhaka"], house: ["House 12", "7"], road: [], postcode: ["1216"], bogus: ["x"] });
  assert.deepEqual(rows.map((r) => r.label), ["HOUSE", "DISTRICT", "POSTCODE"]);
  assert.deepEqual(rows[0], { label: "HOUSE", name: "House", values: ["House 12", "7"] });
  assert.deepEqual(T.fieldRows(null), []);
  assert.deepEqual(T.fieldRows({}), []);
});

test("error messages come from the status and CODE only, and never echo the server's own text", () => {
  const hostile = { error: { code: "text_too_long", message: "<img src=x onerror=alert(1)>" } };
  assert.equal(T.describeError(422, hostile), "That is too long for the demo (500 characters at most).");
  assert.equal(T.describeError(422, { error: { code: "empty_text" } }), "Type an address first.");
  assert.match(T.describeError(429, null, "12"), /wait 12 seconds/);
  assert.match(T.describeError(429, null, null), /wait a few seconds/);
  assert.match(T.describeError(503, null), /not ready yet/);
  assert.match(T.describeError(413, null), /too large/);
  assert.match(T.describeError(422, { error: { code: "something_new", message: "<script>" } }), /could not use that input/);
  assert.match(T.describeError(500, { error: { message: "<script>alert(1)</script>" } }), /HTTP 500/);
  for (const status of [200, 404, 418, 422, 429, 500, 503]) {
    assert.ok(!/[<>]/.test(T.describeError(status, hostile, "5")), `status ${status}`);
  }
});

test("formatMs switches to seconds at one second", () => {
  assert.equal(T.formatMs(12.4), "12 ms");
  assert.equal(T.formatMs(999.6), "1000 ms");
  assert.equal(T.formatMs(1500), "1.5 s");
});
