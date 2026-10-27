// Reads {"text": ..., "entities": [...]} (a real API response) on stdin and prints the labelled runs.
const T = require("../../thikana/web/render.js");
let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => (input += chunk));
process.stdin.on("end", () => {
  const { text, entities } = JSON.parse(input);
  const segs = T.segments(text, entities);
  process.stdout.write(JSON.stringify({ labelled: segs.filter((s) => s.label), joined: segs.map((s) => s.text).join("") }));
});
