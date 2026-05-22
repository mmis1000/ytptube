import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { checkpointWindowResult, readWindowResults } from "../src/pipeline/output-writer.js";
import { getResumeCheckpoint, type WindowResult } from "../src/pipeline/translator.js";

test("checkpointWindowResult appends and replaces window checkpoints in index order", async () => {
  const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), "ytptube-resume-"));

  try {
    const window1: WindowResult = {
      index: 1,
      segmentCount: 2,
      attempts: 1,
      rawLlm: null,
      parsed: [{ ids: [1], text: "a", start: 0, end: 1000 }],
    };
    const window2: WindowResult = {
      index: 2,
      segmentCount: 2,
      attempts: 2,
      rawLlm: null,
      parsed: [{ ids: [2], text: "b", start: 1000, end: 2000 }],
    };
    const replacement2: WindowResult = {
      ...window2,
      attempts: 3,
      parsed: [{ ids: [2], text: "b2", start: 1000, end: 2000 }],
    };

    await checkpointWindowResult(tmpDir, "", "sample", window2);
    await checkpointWindowResult(tmpDir, "", "sample", window1);
    await checkpointWindowResult(tmpDir, "", "sample", replacement2);

    const stored = await readWindowResults(tmpDir, "", "sample");
    assert.deepEqual(stored, [window1, replacement2]);
  } finally {
    await fs.rm(tmpDir, { recursive: true, force: true });
  }
});

test("getResumeCheckpoint only resumes the contiguous successful prefix", () => {
  const checkpoint = getResumeCheckpoint([
    {
      index: 1,
      segmentCount: 1,
      attempts: 1,
      rawLlm: null,
      parsed: [{ ids: [1], text: "first", start: 0, end: 1000 }],
    },
    {
      index: 2,
      segmentCount: 1,
      attempts: 4,
      rawLlm: null,
      parsed: null,
      error: "boom",
    },
    {
      index: 3,
      segmentCount: 1,
      attempts: 1,
      rawLlm: null,
      parsed: [{ ids: [3], text: "third", start: 2000, end: 3000 }],
    },
  ]);

  assert.equal(checkpoint.nextWindowIndex, 1);
  assert.deepEqual(checkpoint.windowResults.map((window) => window.index), [1]);
  assert.deepEqual(checkpoint.entries, [{ ids: [1], text: "first", start: 0, end: 1000 }]);
});

test("getResumeCheckpoint resumes all parsed windows when checkpoint is complete", () => {
  const checkpoint = getResumeCheckpoint([
    {
      index: 1,
      segmentCount: 1,
      attempts: 1,
      rawLlm: null,
      parsed: [{ ids: [1], text: "first", start: 0, end: 1000 }],
    },
    {
      index: 2,
      segmentCount: 1,
      attempts: 1,
      rawLlm: null,
      parsed: [{ ids: [2], text: "second", start: 1000, end: 2000 }],
    },
  ]);

  assert.equal(checkpoint.nextWindowIndex, 2);
  assert.deepEqual(checkpoint.windowResults.map((window) => window.index), [1, 2]);
  assert.deepEqual(checkpoint.entries, [
    { ids: [1], text: "first", start: 0, end: 1000 },
    { ids: [2], text: "second", start: 1000, end: 2000 },
  ]);
});
