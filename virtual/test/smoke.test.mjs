// SPDX-License-Identifier: EUPL-1.2
// The virtual WLED's smoke test: every effect of the firmware runs, on WLED's own engine.
//   VIRTUAL_DIR=<folder with virtual.mjs> [EFFECTS_JSON=<the image's effects.json>] node --test virtual/test/
// Every 1D effect runs 160 frames (4 s) at two strip lengths, with WLED's simulated sound and
// with a "mic" level; a crash (a trap, or an AddressSanitizer report in a SANITIZE=1 build) fails
// it, naming the effect. With EFFECTS_JSON, the effect list must be the image's, id for id.
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { pathToFileURL } from "node:url";

const dir = process.env.VIRTUAL_DIR;
if (!dir) throw new Error("set VIRTUAL_DIR to the folder with virtual.mjs");
// a SANITIZE=1 build prints AddressSanitizer reports; they're collected here, not on the console
const sanitizer = [];
const load = async () => (await import(pathToFileURL(path.join(dir, "virtual.mjs")).href)).default({
  printErr: (line) => sanitizer.push(line),
});

/** AddressSanitizer reports by signature: the kind and the first frames of WLED's or a usermod's
 *  code (the sanitizer's own and our API's frames left out), e.g. "global-buffer-overflow READ:
 *  Segment::loadPalette < Segment::beginDraw". */
function sanitizerReports(lines) {
  const out = new Set();
  let kind = null, frames = [];
  const flush = () => { if (kind) out.add(`${kind}: ${frames.slice(0, 3).join(" < ")}`); kind = null; frames = []; };
  for (const l of lines) {
    const err = l.match(/ERROR: AddressSanitizer: ([\w-]+)/);
    if (err) { flush(); kind = err[1]; continue; }
    if (!kind) continue;
    const op = l.match(/^(READ|WRITE) of size/);
    if (op && !kind.includes(" ")) kind += ` ${op[1]}`;
    const fr = l.match(/#\d+ 0x[0-9a-f]+ in ([^+(]+)/);
    if (fr && !/^(__asan|__interceptor|preview_|virtual_|WS2812FX::service)/.test(fr[1].trim())) frames.push(fr[1].trim().replace(/\(.*$/, ""));
    if (/^SUMMARY:/.test(l)) flush();
  }
  flush();
  return [...out].sort();
}

function effects(m) {
  const out = [];
  for (let id = 0; id < m._preview_effect_count(); id++) {
    out.push({ id, name: m.UTF8ToString(m._preview_effect_name(id)), meta: m.UTF8ToString(m._preview_effect_metadata(id)) });
  }
  return out;
}
// WLED's metadata flags (after the third ";"): "1" 1D, "2" 2D; none means 1D
const flags = (meta) => (meta.split(";")[3] ?? "");
const runsOn1D = (meta) => { const f = flags(meta); return f.includes("1") || !f.includes("2"); };

test("the effect list is the firmware's", async (t) => {
  const m = await load();
  m._preview_setup(60);
  const list = effects(m);
  assert.ok(list.length > 1 && list[0].name === "Solid", `${list.length} effects`);
  if (!process.env.EFFECTS_JSON) return t.skip("no EFFECTS_JSON to compare with");
  const image = JSON.parse(readFileSync(process.env.EFFECTS_JSON, "utf8")).effects;
  assert.deepEqual(list.map((e) => `${e.id}:${e.name}`), image.map((e) => `${e.id}:${e.name}`));
});

/** Runs every 1D effect; returns what crashed ("id name: where: error") and what ran. A trapped
 *  module isn't trusted again: the next effect gets a fresh one. */
async function smoke() {
  const report = { run: [], skipped2D: [], dark: [], crashed: [], sanitizer: [] };
  for (const len of [30, 280]) {
    for (const mic of [-1, 200]) {
      let m = null;
      const fresh = async () => { m = await load(); m._preview_setup(len); m._preview_audio(mic); };
      await fresh();
      for (const e of effects(m)) {
        if (e.name === "RSVD") continue;
        if (!runsOn1D(e.meta)) { if (len === 30 && mic < 0) report.skipped2D.push(e.name); continue; }
        let lit = 0;
        try {
          m._preview_select(e.id);
          for (let f = 1; f <= 160; f++) {
            const p = m._preview_frame(f * 25) >>> 2;
            if (f > 40) for (let i = 0; i < len; i++) if (m.HEAPU32[p + i]) { lit++; break; }
          }
        } catch (err) {
          report.crashed.push(`${e.id} ${e.name}: ${len} LEDs, ${mic < 0 ? "simulated sound" : "mic " + mic}: ${String(err).split("\n")[0]}`);
          await fresh();
          continue;
        }
        if (len === 280 && mic < 0) { report.run.push(e.name); if (!lit) report.dark.push(e.name); }
      }
    }
  }
  report.sanitizer = sanitizerReports(sanitizer);
  return report;
}

// Crashes allowed because the firmware without our usermods has them too (KNOWN_CRASHES: a file
// of "id name" lines, e.g. the stock image's smoke report); anything else fails.
test("every 1D effect runs, with simulated sound and with a mic level, at two lengths", async () => {
  const report = await smoke();
  if (process.env.SMOKE_REPORT) writeFileSync(process.env.SMOKE_REPORT, JSON.stringify(report, null, 1));
  console.log(`ran ${report.run.length} effects; 2D-only, skipped: ${report.skipped2D.length}; ` +
              `dark all the time: ${report.dark.length}; crashed: ${report.crashed.length}`);
  for (const c of report.crashed) console.log("  crash:", c);
  const known = new Set((process.env.KNOWN_CRASHES ? readFileSync(process.env.KNOWN_CRASHES, "utf8") : "")
    .split("\n").map((l) => l.trim()).filter(Boolean));
  const effectOf = (c) => c.slice(0, c.indexOf(":"));
  const fresh = [...new Set(report.crashed.map(effectOf))].filter((e) => !known.has(e));
  assert.deepEqual(fresh, [], `effects that crash: ${fresh.join("; ")}`);
  // memory errors (a SANITIZE=1 build): only those the firmware without our usermods has too
  // (KNOWN_SANITIZER: a stock run's SMOKE_REPORT)
  for (const s of report.sanitizer) console.log("  memory:", s);
  const knownSan = new Set(process.env.KNOWN_SANITIZER ? JSON.parse(readFileSync(process.env.KNOWN_SANITIZER, "utf8")).sanitizer : []);
  const freshSan = report.sanitizer.filter((s) => !knownSan.has(s));
  assert.deepEqual(freshSan, [], `memory errors: ${freshSan.join("; ")}`);
  assert.ok(report.run.length > 0);
});
