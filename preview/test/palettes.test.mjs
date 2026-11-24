// SPDX-License-Identifier: EUPL-1.2
// Exact colours: a preview built with a WLED checkout (WLED_SRC) shows WLED's palettes as that
// checkout defines them. EXACT_DIR: the palette probe built with WLED_SRC; APPROX_DIR: built without.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { pathToFileURL } from "node:url";

const load = async (dir) => (await import(pathToFileURL(path.join(dir, "preview.mjs")).href)).default();
const src = process.env.WLED_SRC;
if (!src || !process.env.EXACT_DIR || !process.env.APPROX_DIR) throw new Error("set WLED_SRC, EXACT_DIR and APPROX_DIR");
const palettesCpp = readFileSync(path.join(src, "wled00", "palettes.cpp"), "utf8");
// CRGB's named colours (CRGB::Blue …), as fastled_slim defines them
const named = Object.fromEntries([...readFileSync(path.join(src, "wled00", "src", "dependencies", "fastled_slim", "fastled_slim.h"), "utf8")
  .matchAll(/\b(\w+)\s*=\s*0x([0-9A-Fa-f]{6})\b/g)].map((m) => [m[1], parseInt(m[2], 16)]));

/** A 16-entry palette from palettes.cpp, as 0x00RRGGBB numbers (hex values or CRGB::Name). */
function palette16(name) {
  const body = palettesCpp.match(new RegExp(`${name}\\s*PROGMEM\\s*=\\s*\\{([^}]*)\\}`))[1];
  const out = [...body.matchAll(/0x([0-9A-Fa-f]{6})|CRGB::(\w+)/g)].map((m) => m[1] ? parseInt(m[1], 16) : named[m[2]]);
  assert.equal(out.length, 16, `${name}: 16 entries`);
  assert.ok(out.every((c) => c !== undefined), `${name}: every colour known`);
  return out;
}
/** The order of the 16-entry palettes in fastledPalettes[] (ids 6..12). */
const fastledOrder = [...palettesCpp.match(/fastledPalettes\[\][^{]*\{([^}]*)\}/)[1].matchAll(/&(\w+)/g)].map((m) => m[1]);

function run(m, effect, settings = {}) {
  m._preview_setup(16);
  assert.equal(m._preview_select(effect), effect);
  for (const [k, v] of Object.entries(settings)) m._preview_set(Number(k), v);
  const ptr = m._preview_frame(0) >>> 2;
  return Array.from(m.HEAPU32.subarray(ptr, ptr + 16)).map((c) => c & 0xffffff);
}

test("the palettes by id are WLED's own: each 16-entry palette matches palettes.cpp", async () => {
  const m = await load(process.env.EXACT_DIR);
  assert.ok(fastledOrder.length >= 7, `fastledPalettes: ${fastledOrder}`);
  fastledOrder.forEach((name, k) => {
    assert.deepEqual(run(m, 1, { 8: 6 + k }), palette16(name), `palette ${6 + k} (${name})`);
  });
});

test("palette 0 shows the effect's default: Party, or its pal= default", async () => {
  const m = await load(process.env.EXACT_DIR);
  assert.deepEqual(run(m, 1, { 8: 0 }), palette16("PartyColors_gc22"));
  assert.deepEqual(run(m, 2, { 8: 0 }), run(m, 2, { 8: 11 }));
  assert.notDeepEqual(run(m, 2, { 8: 0 }), palette16("PartyColors_gc22"));
});

test("WLED's blending maths: a still palette is remapped not to wrap, and blends entries", async () => {
  const m = await load(process.env.EXACT_DIR);
  const party = palette16("PartyColors_gc22");
  // LED 1: index 16, remapped to (16 * 0xF0) >> 8 = 15: entry 0 blended with entry 1 by 15/16
  const f2 = 15 << 4, f1 = 256 - f2;
  const mix = (s) => (((party[0] >> s) & 255) * f1 + ((party[1] >> s) & 255) * f2) >> 8;
  assert.equal(run(m, 4, { 8: 6 })[1], (mix(16) << 16) | (mix(8) << 8) | mix(0));
});

test("gradient palettes and the colour palettes load", async () => {
  const m = await load(process.env.EXACT_DIR);
  const red = 0xff0000, blue = 0x0000ff;
  assert.deepEqual(new Set(run(m, 1, { 8: 2, 9: red })), new Set([red]), "palette 2: colour 1 only");
  const two = run(m, 1, { 8: 3, 9: red, 10: blue });
  assert.equal(two[0], red);
  assert.equal(two[15], blue);
  const grad = run(m, 1, { 8: 13 });
  assert.ok(new Set(grad).size > 4, `a gradient palette has many colours: ${grad.map((c) => c.toString(16))}`);
});

test("the preview reports WLED's palette names in exact mode, none in approximate mode", async () => {
  const exact = await load(process.env.EXACT_DIR), approx = await load(process.env.APPROX_DIR);
  const names = JSON.parse(exact.UTF8ToString(exact._preview_palette_names()));
  assert.equal(names[0], "Default");
  assert.ok(names.length >= 72, `${names.length} names`);
  assert.equal(approx.UTF8ToString(approx._preview_palette_names()), "");
});

test("approximate mode differs from WLED's palettes: what exact mode is for", async () => {
  const approx = await load(process.env.APPROX_DIR);
  assert.notDeepEqual(run(approx, 1, { 8: 6 }), palette16(fastledOrder[0]));
});
