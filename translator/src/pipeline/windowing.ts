import type { Segment } from "../util/types.js";
import { formatTranscriptionJson } from "./prompt-builder.js";

// Character-budget windowing: grow each window until the estimated total
// character count (fixed prompt overhead + transcription JSON) exceeds maxChars.
//
// v0.2 continues the models at a native total sequence length of 8192 tokens.
// These are intentionally input-side character budgets, not attempts to fill n_ctx.
// Held-out validation showed that concatenating noisy/repetitive source windows near
// 8k can amplify repetition and cross-window contamination, especially in zh-cn echo.
// Keep the established shorter windows and let translator.ts reserve generation room;
// retries can sub-chunk further when collapse or malformed output is detected.
//
// Echo uses a larger budget than base because its source-echo output is typically
// better anchored, while still staying well below the total runtime context limit.
export const MAX_CHARS_BASE = 2500;
export const MAX_CHARS_ECHO = 3500;
const MIN_WINDOW = 3;

export interface InferenceWindow {
  /** Segments with IDs renumbered from 1 within this window. */
  segments: Segment[];
  /** Map from window-local ID → global segment ID. */
  idMap: Map<number, number>;
}

/**
 * Slice segments into character-budget windows for inference.
 * IDs are renumbered from 1 within each window (matching training format).
 *
 * @param allSegments  All cleaned transcript segments with global IDs.
 * @param getOverheadChars  Returns the prompt header length for a given set of segments
 *                          (glossary + fixed rules). Called per candidate slice so that
 *                          the filtered glossary is used for sizing.
 */
export function makeInferenceWindows(
  allSegments: Segment[],
  getOverheadChars: (segs: Segment[]) => number,
  maxChars = MAX_CHARS_BASE,
  minWindow = MIN_WINDOW,
): InferenceWindow[] {
  const windows: InferenceWindow[] = [];

  function sliceChars(start: number, end: number): number {
    const slice = allSegments.slice(start, end);
    return getOverheadChars(slice) + formatTranscriptionJson(slice).length;
  }

  let wiStart = 0;
  while (wiStart < allSegments.length) {
    // Must have at least minWindow segments left
    if (wiStart + minWindow > allSegments.length) break;

    // Start with minWindow, then greedily grow
    let wiEnd = wiStart + minWindow;
    while (wiEnd < allSegments.length) {
      if (sliceChars(wiStart, wiEnd + 1) > maxChars) break;
      wiEnd++;
    }

    const rawSegs = allSegments.slice(wiStart, wiEnd);

    // Renumber IDs from 1 within window, store reverse mapping
    const idMap = new Map<number, number>(); // local → global
    const segments: Segment[] = rawSegs.map((s, i) => {
      const localId = i + 1;
      idMap.set(localId, s.id);
      return { ...s, id: localId };
    });

    windows.push({ segments, idMap });
    wiStart = wiEnd;
  }

  return windows;
}
