import fs from "fs/promises";
import path from "path";
import type { TranscriptSegment, TranslationEntry, FinalMetadata, UserMetadata } from "../util/types.js";
import type { WindowResult } from "./translator.js";
import { toLrc, toVtt } from "./subtitle-exporter.js";

/** Ensure a directory exists, creating it recursively if needed. */
async function ensureDir(dir: string): Promise<void> {
  await fs.mkdir(dir, { recursive: true });
}

function windowResultsPath(outputDir: string, relativeDir: string, stem: string): string {
  return path.join(outputDir, relativeDir, `${stem}.windows.json`);
}

async function writeJsonAtomic(filePath: string, value: unknown): Promise<void> {
  const tempPath = `${filePath}.tmp`;
  await fs.writeFile(tempPath, JSON.stringify(value, null, 2), "utf-8");
  await fs.rename(tempPath, filePath);
}

/** Write the cleaned transcription for a single track. */
export async function writeTranscription(
  outputDir: string,
  relativeDir: string,
  stem: string,
  segments: TranscriptSegment[],
  mismatches?: TranscriptSegment[],
): Promise<void> {
  const dir = path.join(outputDir, relativeDir);
  await ensureDir(dir);
  await fs.writeFile(
    path.join(dir, `${stem}.transcription.json`),
    JSON.stringify({ segments, mismatches }, null, 2),
    "utf-8",
  );
}

export async function writeTranscriptSubtitles(
  outputDir: string,
  relativeDir: string,
  stem: string,
  segments: TranscriptSegment[],
): Promise<void> {
  const dir = path.join(outputDir, relativeDir);
  await ensureDir(dir);

  const entries: TranslationEntry[] = segments
    .map((segment, index) => ({
      ids: [index + 1],
      text: segment.text?.trim() || null,
      start: Math.round(segment.start_time * 1000),
      end: Math.round(segment.end_time * 1000),
    }))
    .filter((entry) => entry.text && entry.end >= entry.start);

  await Promise.all([
    fs.writeFile(
      path.join(dir, `${stem}.lrc`),
      toLrc(entries),
      "utf-8",
    ),
    fs.writeFile(
      path.join(dir, `${stem}.vtt`),
      toVtt(entries),
      "utf-8",
    ),
  ]);
}

/** Write the translation output for a single track (JSON + LRC + VTT). */
export async function writeTranslation(
  outputDir: string,
  relativeDir: string,
  stem: string,
  entries: TranslationEntry[],
): Promise<void> {
  const dir = path.join(outputDir, relativeDir);
  await ensureDir(dir);

  await Promise.all([
    fs.writeFile(
      path.join(dir, `${stem}.translation.json`),
      JSON.stringify(entries, null, 2),
      "utf-8",
    ),
    fs.writeFile(
      path.join(dir, `${stem}.lrc`),
      toLrc(entries),
      "utf-8",
    ),
    fs.writeFile(
      path.join(dir, `${stem}.vtt`),
      toVtt(entries),
      "utf-8",
    ),
  ]);
}

export async function readWindowResults(
  outputDir: string,
  relativeDir: string,
  stem: string,
): Promise<WindowResult[]> {
  const filePath = windowResultsPath(outputDir, relativeDir, stem);
  try {
    const raw = await fs.readFile(filePath, "utf-8");
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as WindowResult[]) : [];
  } catch {
    return [];
  }
}

export async function checkpointWindowResult(
  outputDir: string,
  relativeDir: string,
  stem: string,
  windowResult: WindowResult,
): Promise<void> {
  const dir = path.join(outputDir, relativeDir);
  await ensureDir(dir);
  const existing = await readWindowResults(outputDir, relativeDir, stem);
  const merged = [...existing.filter((entry) => entry.index !== windowResult.index), windowResult]
    .sort((left, right) => left.index - right.index);
  await writeJsonAtomic(windowResultsPath(outputDir, relativeDir, stem), merged);
}

/** Write per-window LLM intermediates for debugging (raw output + parsed entries). */
export async function writeWindowResults(
  outputDir: string,
  relativeDir: string,
  stem: string,
  windowResults: WindowResult[],
): Promise<void> {
  const dir = path.join(outputDir, relativeDir);
  await ensureDir(dir);
  await writeJsonAtomic(windowResultsPath(outputDir, relativeDir, stem), windowResults);
}

/** Write metadata.json at the output root. */
export async function writeMetadata(
  outputDir: string,
  metadata: FinalMetadata | UserMetadata,
): Promise<void> {
  await ensureDir(outputDir);
  await fs.writeFile(
    path.join(outputDir, "metadata.json"),
    JSON.stringify(metadata, null, 2),
    "utf-8",
  );
}

/** Write surgical repair log if any repairs were attempted. */
export async function writeSurgicalLog(
  outputDir: string,
  relativeDir: string,
  stem: string,
  surgicalLog: any[],
): Promise<void> {
  if (surgicalLog.length === 0) return;
  const dir = path.join(outputDir, relativeDir);
  await ensureDir(dir);
  await fs.writeFile(
    path.join(dir, `${stem}.surgical.json`),
    JSON.stringify(surgicalLog, null, 2),
    "utf-8",
  );
}

/** Read surgical repair log if it exists. */
export async function readSurgicalLog(
  outputDir: string,
  relativeDir: string,
  stem: string,
): Promise<any[] | null> {
  const filePath = path.join(outputDir, relativeDir, `${stem}.surgical.json`);
  try {
    const raw = await fs.readFile(filePath, "utf-8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}
