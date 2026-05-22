# YTPTube Subtitle Resume-from-Window Checkpoint Implementation Plan

**Goal:** Make interrupted subtitle translation jobs resume from the last completed translate window instead of restarting from window 1.

**Architecture:** Keep the existing mounted translator workspace under `/tmp`, but make translation progress durable within that workspace. The translator will persist a checkpoint after each completed translate window, reload it on restart, and skip already completed windows. The app layer will reconcile stale `subtitle_generation.state == "running"` jobs after restart and either mark them resumable or restart them through the checkpoint-aware translator path.

**Tech Stack:** Python app layer (`aiohttp`/YTPTube app), TypeScript translator CLI/pipeline, JSON checkpoint files, existing workspace/job metadata.

---

## Scope and constraints

### In scope
- Resume **translate-window** progress for subtitle jobs
- Reuse existing mounted workspace
- Preserve current successful end-state outputs:
  - `.translation.json`
  - `.lrc`
  - `.vtt`
  - `.windows.json`
- Keep current full-workspace recovery behavior for already-finished jobs

### Out of scope
- Changing `/tmp` workspace location
- Reworking ASR pipeline semantics
- Cross-track parallel resume
- UI redesign

---

## Desired behavior

### Crash scenario
If a job crashes at:

- track 1
- window 28/41

then on next retry:

- windows 1–27 are loaded from checkpoint
- translation continues from window 28
- final outputs are regenerated from combined checkpointed + newly completed windows
- job does **not** restart from window 1

### Restart reconciliation
If the app restarts and a history item still says:

- `subtitle_generation.state == "running"`

but no job is actually alive, startup logic should:

- detect the stale running state
- inspect workspace/checkpoint state
- mark the item as interrupted/resumable, or automatically restart it through the resume-aware path

---

# Phase 1 — Translator checkpoint persistence

## Task 1: Add checkpoint read/write helpers for window progress

**Objective:** Create explicit helpers for durable per-track window checkpoint files.

**Files:**
- Modify: `translator/src/pipeline/output-writer.ts`

**Changes:**
Add helpers for:
- reading existing window checkpoint
- atomically writing updated checkpoint
- optionally validating file shape at load time

### Required API shape
Add functions roughly like:

```ts
export async function readWindowResults(
  outputDir: string,
  relativeDir: string,
  stem: string,
): Promise<WindowResult[] | null>
```

```ts
export async function writeWindowResultsAtomic(
  outputDir: string,
  relativeDir: string,
  stem: string,
  windowResults: WindowResult[],
): Promise<void>
```

### Implementation notes
- write to temp path first, then rename:
  - `${stem}.windows.json.tmp`
  - rename to `${stem}.windows.json`
- keep the final filename unchanged:
  - `${stem}.windows.json`
- tolerate missing file by returning `null`
- tolerate invalid JSON by returning `null` only if you intentionally want soft recovery; otherwise throw a clearly labeled error and let caller decide

### Verification
- unit test load of missing checkpoint returns `null`
- unit test valid checkpoint round-trips
- unit test atomic write replaces prior content cleanly

---

## Task 2: Add resumability metadata to checkpoint format

**Objective:** Store enough metadata to tell whether a checkpoint is safe to reuse.

**Files:**
- Modify: `translator/src/pipeline/translator.ts`
- Modify: `translator/src/pipeline/output-writer.ts`

**Changes:**
Extend checkpoint payload so it is not just a raw `WindowResult[]`. Store an object like:

```ts
interface TranslationCheckpoint {
  version: 1;
  trackName: string;
  mode: string;
  locale: string;
  segmentCount: number;
  inputHash: string;
  windowCount: number;
  results: WindowResult[];
}
```

### Input hash
Compute a stable hash from the effective cleaned input segments used for translation, e.g. based on:
- id
- text
- start
- end

This prevents reusing old checkpoint data when:
- ASR changed
- cleaning changed
- segmentation changed
- locale/mode changed

### Verification
- test identical segment input yields same hash
- test changed text or segment count invalidates hash
- test checkpoint mismatch causes resume rejection

---

## Task 3: Load checkpoint before window loop

**Objective:** Pre-seed translation state from prior successful windows.

**Files:**
- Modify: `translator/src/pipeline/translator.ts`

**Changes:**
Inside `translateTrack(...)`:

1. build windows as today
2. load checkpoint if present
3. validate:
   - version
   - trackName
   - mode
   - locale
   - segmentCount
   - inputHash
   - windowCount
4. if valid:
   - iterate prior `results`
   - for every window with `parsed != null`, append entries into `allEntries`
   - pre-populate `windowResults`
   - compute first incomplete window index
5. start the main translation loop from first incomplete window

### Important rule
A prior window counts as completed **only if**:
- its `parsed` field is non-null

Do **not** treat:
- `error`
- missing result
- malformed result

as completed.

### Verification
- test checkpoint with first 3 successful windows resumes at window 4
- test checkpoint with successful 1–3 and failed 4 resumes at 4
- test invalid checkpoint falls back to full rerun

---

## Task 4: Persist checkpoint after every window

**Objective:** Ensure crash after any window still leaves reusable progress on disk.

**Files:**
- Modify: `translator/src/pipeline/translator.ts`

**Changes:**
After each window reaches a terminal state in the loop:
- update in-memory `windowResults`
- immediately write checkpoint atomically

This must happen whether the window:
- succeeded with `parsed`
- exhausted retries and ended with `error`

### Recommended write moment
Right after:

```ts
windowResults.push(winResult);
```

and before moving to next window.

### Verification
- test that after simulated completion of first N windows, checkpoint file contains exactly N results
- test failed window still gets recorded with `error`
- test crash after write would still leave valid JSON file

---

## Task 5: Rebuild final outputs from resumed state

**Objective:** Preserve identical final output behavior whether run fresh or resumed.

**Files:**
- Modify: `translator/src/pipeline/translator.ts`
- Possibly modify: `translator/src/cli.ts`

**Changes:**
Keep final behavior:
- aggregate entries from checkpointed successful windows + newly translated windows
- run `stripSpeakerPrefixes(allEntries)` at end
- return final entries and full `windowResults`

The current caller in `cli.ts` can still:
- `writeWindowResults(...)`
- `writeTranslation(...)`

But after Phase 1, `writeWindowResults(...)` at track end becomes a final overwrite/normalization step, not the only persistence point.

### Verification
- fresh run and resumed run over same input produce same final `translation.json`
- resumed run still writes `.lrc` and `.vtt` as before

---

# Phase 2 — CLI integration

## Task 6: Keep final track-level write, but make it idempotent

**Objective:** Preserve current end-of-track behavior while incremental persistence exists.

**Files:**
- Modify: `translator/src/cli.ts`

**Changes:**
After:

```ts
const { entries, windowResults } = await translateTrack(...)
```

keep:
- final `writeWindowResults(...)`
- final `writeTranslation(...)`

But this should now be treated as:
- final normalization write
- not the only persistence path

### Verification
- fresh successful run still produces same outputs
- resumed successful run still produces same outputs
- no duplicate entries appear in final translation

---

## Task 7: Add resume logging

**Objective:** Make progress behavior visible in app logs and `translator.log`.

**Files:**
- Modify: `translator/src/pipeline/translator.ts`

**Changes:**
Log explicit resume messages such as:
- `[TranslateResume] Loaded 27 completed windows for <track>`
- `[TranslateResume] Resuming at window 28/41 for <track>`
- `[TranslateResume] Checkpoint invalidated: input hash mismatch`

These lines should be “interesting” enough for app progress visibility if desired.

### Verification
- resumed run writes clear checkpoint/resume lines
- invalid checkpoint explains why full rerun happened

---

# Phase 3 — App-side stale job reconciliation

## Task 8: Introduce startup scan for stale running subtitle jobs

**Objective:** Fix the case where app restarts and DB/UI still says a subtitle job is running.

**Files:**
- Modify: `app/features/translator/service.py`
- Possibly modify: `app/main.py` if startup hook placement needs adjustment

**Changes:**
Add a startup reconciliation method, e.g. called from `TranslatorService.attach(...)` or startup hook:
- scan history items
- identify items with `extras.subtitle_generation.state == "running"`
- for each:
  - inspect workspace path
  - inspect presence of `translator.log`
  - inspect presence of `.windows.json` / final outputs
- convert stale state to something truthful

### Recommended minimum behavior
If job is marked `running` but is not in `_jobs` after app boot:
- mark it as interrupted
- keep workspace/log/checkpoint metadata
- set a message like:
  - `Subtitle generation interrupted by app restart; resumable from workspace checkpoint.`

### Optional second-stage behavior
After manual rollout is proven, optionally auto-resume these jobs.

### Verification
- test app startup turns stale `running` state into interrupted/resumable state
- test already finished items are not touched
- test jobs already fully recovered from workspace outputs remain completed

---

## Task 9: Add resumable state metadata in item extras

**Objective:** Distinguish “live running process” from “stale state with resume checkpoint”.

**Files:**
- Modify: `app/features/translator/service.py`

**Changes:**
Extend `subtitle_generation` metadata with fields like:
- `state`: `queued | running | interrupted | finished | failed`
- `resumable: bool`
- `resume_reason: str | null`

You do not need a full enum refactor immediately, but stale `running` should stop being ambiguous.

### Verification
- interrupted restart case sets `resumable: true`
- fully failed no-checkpoint case sets `resumable: false` if appropriate

---

## Task 10: Manual subtitle restart should resume by default

**Objective:** Ensure `POST /api/history/{id}/subtitle` reuses checkpoint automatically.

**Files:**
- Modify: `app/features/translator/service.py`
- Route likely unchanged: `app/routes/api/history.py`

**Changes:**
Do **not** add a separate “resume” API first unless needed.
Prefer:
- normal subtitle generate endpoint
- translator resume logic automatically engages if partial checkpoint exists

Current full recovery behavior already checks for full outputs. Keep that.
New behavior should handle:
- partial checkpoint exists, final outputs do not

### Verification
- manually re-triggering interrupted item resumes at saved window
- forcing job with `force=true` can still ignore checkpoint if desired

---

# Phase 4 — Tests

## Task 11: Add translator checkpoint unit tests

**Objective:** Prove resume logic at the window layer.

**Files:**
- Create or modify translator test files in translator project

**Minimum cases:**
1. no checkpoint → starts at window 1
2. checkpoint with windows 1–3 successful → starts at 4
3. checkpoint with failed window 4 → retries 4
4. checkpoint metadata mismatch → full rerun
5. incremental write after each window produces valid JSON
6. resumed final output matches fresh final output

---

## Task 12: Add app recovery tests

**Objective:** Prove stale-running reconciliation and manual retry semantics.

**Files:**
- Modify: `app/tests/test_translator_service.py`

**Minimum cases:**
1. stale `running` state + valid checkpoint → item becomes interrupted/resumable
2. stale `running` state + full sidecars in workspace → item becomes completed/recovered
3. stale `running` state + no workspace → item becomes failed/interrupted non-resumable
4. manual restart of interrupted item resumes using checkpointed workspace
5. `force=true` bypasses checkpoint if that behavior is chosen

---

## Task 13: Add regression test for current real failure shape

**Objective:** Encode the exact failure mode you observed.

**Files:**
- Modify: `app/tests/test_translator_service.py`
- translator tests as appropriate

**Scenario to model:**
- item has:
  - `subtitle_generation.state == "running"`
  - `phase == "translate"`
  - `window_current == 28`
  - workspace exists
  - partial windows checkpoint exists with 27 successful windows
- app restarts
- next subtitle generation call resumes at 28, not 1

This should become the main regression guard.

---

# Suggested implementation details

## Checkpoint file shape
Prefer this over plain raw array:

```json
{
  "version": 1,
  "trackName": "sample.webm",
  "mode": "echo",
  "locale": "zh-tw",
  "segmentCount": 123,
  "inputHash": "sha256:...",
  "windowCount": 41,
  "results": [
    {
      "index": 1,
      "segmentCount": 4,
      "attempts": 1,
      "rawLlm": null,
      "parsed": [...]
    }
  ]
}
```

## Atomic write pattern
Use:
1. write temp file
2. fsync if you want extra safety
3. rename temp over final

## Resume skip rule
A window is resumable/skippable only if:
- checkpoint has result for same `index`
- `parsed` is non-null
- checkpoint metadata matches current input/windowing context

---

# Rollout order

## Milestone 1 — Core resume
Implement:
- checkpoint object format
- incremental write per window
- checkpoint load + skip completed windows
- final output reconstruction

**Success criterion:** manual restart after crash resumes from later window.

## Milestone 2 — App stale-state cleanup
Implement:
- startup reconciliation for stale running jobs
- clearer `subtitle_generation.state` semantics

**Success criterion:** app restart no longer leaves misleading forever-running subtitle jobs.

## Milestone 3 — Optional auto-resume
Implement only if desired after validation:
- automatic restart of stale resumable jobs on startup

**Success criterion:** crash recovery requires no manual API click.

---

# Acceptance criteria

A change is not done until all of these are true:

- [ ] crash after translate window N leaves durable checkpoint for windows `<= N`
- [ ] next subtitle retry resumes at first incomplete window, not window 1
- [ ] resumed final `.translation.json`, `.lrc`, `.vtt` are valid
- [ ] stale `subtitle_generation.state == "running"` does not remain misleading after app restart
- [ ] full finished-workspace recovery still works as before
- [ ] checkpoint mismatch safely falls back to full rerun
- [ ] regression test covers the observed 28/41 interrupted-translate case

---

# Practical first patch target

If you want the fastest high-value implementation order, do these first:

1. `translator/src/pipeline/output-writer.ts`
   - add checkpoint read + atomic write helpers

2. `translator/src/pipeline/translator.ts`
   - load checkpoint
   - skip completed windows
   - write checkpoint after each window

3. `app/tests/test_translator_service.py` + translator tests
   - add regression and resume tests

4. `app/features/translator/service.py`
   - startup stale-state reconciliation

That should get you from “restart from chunk 0” to “resume from last completed window” with the least architectural churn.
