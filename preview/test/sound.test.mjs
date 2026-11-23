// SPDX-License-Identifier: EUPL-1.2
// The shim's sound: a usermod effect reads AudioReactive's data or the simulation.
// Run with SOUND_DIR pointing at the compiled preview/test/sound_probe.
import assert from "node:assert/strict";
import { test } from "node:test";
import path from "node:path";
import { pathToFileURL } from "node:url";

const dir = process.env.SOUND_DIR;
if (!dir) throw new Error("set SOUND_DIR to the folder with the sound probe's preview.mjs");
const createModule = (await import(pathToFileURL(path.join(dir, "preview.mjs")).href)).default;

async function probe(len) {
  const m = await createModule();
  m._preview_setup(len);
  assert.equal(m._preview_select(1), 1);
  m._preview_set(9, 0x00ffffff);
  const lit = (t) => {
    const ptr = m._preview_frame(t) >>> 2;
    return Array.from(m.HEAPU32.subarray(ptr, ptr + len)).filter((c) => c !== 0).length;
  };
  return { m, lit };
}

test("a level set with preview_audio is what the effect reads", async () => {
  const { m, lit } = await probe(100);
  m._preview_audio(0);
  assert.equal(lit(0), 0);
  m._preview_audio(127.5);
  assert.equal(lit(100), 50);
  m._preview_audio(255);
  assert.equal(lit(200), 100);
});

test("without a level, the simulation drives it, and the sound simulation setting changes its shape", async () => {
  const { m, lit } = await probe(100);
  m._preview_audio(-1);
  const sine = [0, 125, 250, 375].map(lit);       // the default: a 120 bpm sine
  assert.ok(Math.max(...sine) - Math.min(...sine) > 50, `sine ${sine}`);
  m._preview_set(12, 1);                          // the stomp: on or nearly off
  const stomp = [0, 60, 200, 300, 500, 560].map(lit);
  assert.deepEqual(stomp.map((n) => n > 50), [true, true, false, false, true, true]);
});
