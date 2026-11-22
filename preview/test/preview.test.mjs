// SPDX-License-Identifier: EUPL-1.2
// Runs the compiled preview (PREVIEW_DIR/preview.mjs) in Node and checks the frames.
import assert from "node:assert/strict";
import { test } from "node:test";
import path from "node:path";
import { pathToFileURL } from "node:url";

const dir = process.env.PREVIEW_DIR;
if (!dir) throw new Error("set PREVIEW_DIR to the folder with preview.mjs");
const createModule = (await import(pathToFileURL(path.join(dir, "preview.mjs")).href)).default;

async function preview(len) {
  const m = await createModule();
  m._preview_setup(len);
  const names = [];
  for (let id = 0; id < m._preview_effect_count(); id++) names.push(m.UTF8ToString(m._preview_effect_name(id)));
  const frame = (t) => {
    const ptr = m._preview_frame(t) >>> 2;
    return Array.from(m.HEAPU32.subarray(ptr, ptr + m._preview_length()));
  };
  return { m, names, frame };
}

test("the example usermod registers its effect at its fixed id, behind hidden placeholders", async () => {
  const { m, names } = await preview(60);
  assert.equal(names[0], "Solid");
  assert.equal(names[254], "Studio Comet");
  assert.ok(names.slice(1, 254).every((n) => n === "RSVD"));
  assert.equal(m.UTF8ToString(m._preview_effect_metadata(254)), "Speed,Tail;!;!;1;sx=128,ix=200");
});

test("the comet's head is where the effect puts it, in the effect's colour", async () => {
  const { m, frame } = await preview(60);
  assert.equal(m._preview_select(254), 254);
  m._preview_set(0, 128);              // speed
  m._preview_set(1, 200);              // tail
  m._preview_set(9, 0x00ff8000);       // colour 1 (0xWWRRGGBB)
  const period = 256 * (300 - 128);
  for (const t of [0, 11008, 22016, 33024]) {
    const px = frame(t);
    const head = Math.floor(((t % period) * 60) / period);
    assert.equal(px[head], 0x00ff8000, `t=${t}: head at ${head}`);
  }
});

test("the tail fades behind the head", async () => {
  const { m, frame } = await preview(60);
  m._preview_select(254);
  m._preview_set(0, 128);
  m._preview_set(1, 200);
  m._preview_set(9, 0x00ffffff);
  let px;
  for (let t = 0; t <= 11008; t += 172) px = frame(t);   // ~ one pixel per frame
  const brightness = (c) => ((c >> 16) & 255) + ((c >> 8) & 255) + (c & 255);
  assert.equal(px[15], 0x00ffffff);
  assert.ok(brightness(px[14]) < brightness(px[15]) && brightness(px[14]) > 0, "a fading tail");
  assert.ok(brightness(px[13]) < brightness(px[14]));
  assert.equal(px[40], 0, "nothing ahead of the head");
});

test("unknown ids are refused", async () => {
  const { m } = await preview(10);
  assert.equal(m._preview_select(999), -1);
  assert.equal(m.UTF8ToString(m._preview_effect_name(999)), "");
});
