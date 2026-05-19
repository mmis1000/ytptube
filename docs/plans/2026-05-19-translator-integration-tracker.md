# Translator / Subtitle Integration Tracker

> Durable repo-side tracker for resumable ytptube translator integration work.

## Acceptance checklist

- [x] Standalone translator CLI MTP flow works end-to-end
- [x] Backend app mounts a translator service into lifecycle
- [x] Backend app exposes a history subtitle-generation API
- [x] UI/history page exposes an action for old-task subtitle generation
- [x] App/UI surfaces live subtitle-generation progress for history items
- [x] New download flow can request subtitle behavior explicitly
- [x] Task model persists subtitle behavior for scheduled/manual reruns
- [ ] UI exposes task/new-download controls for subtitle run modes
- [ ] Aborted subtitle tasks can resume without unnecessary redo
- [ ] Browser automation validates the integrated behavior
- [ ] Changes are committed in coherent tested commits

## Validated so far

- translator build passes
- Python ASR dependencies import successfully
- standalone MTP e2e succeeded for https://www.youtube.com/watch?v=gOJTw2dpVR4
- history subtitle route tests pass
- frontend history integration changes pass `npm run typecheck`
- frontend history integration changes pass `npm run lint:ci -- app/composables/useHistoryState.ts app/pages/history.vue`

## Latest progress

- Added history-page "Generate subtitles" action wired to `POST /api/history/{id}/subtitle`.
- Added `item_updated` handling in `useHistoryState` so history entries refresh from websocket updates without a reload.
- Updated history status/icon rendering to surface subtitle-generation states like queued, running, error, and finished.
- Extended frontend store typing for `extras.subtitle_generation` and related fields.

## Next focus

1. Wire subtitle mode through new-download flow.
2. Wire subtitle mode through task schema/model/UI and dispatch extras.
3. Implement resume semantics for interrupted subtitle jobs.
4. Browser-verify integrated behavior.
5. Commit tested MTP support changes.

- Added `download_mode` and `subtitle_mode` to task model/schema/frontend types plus a DB migration.
- Wired task dispatch and manual task "Run now" to carry subtitle workflow extras into history items.
- Added new-download and task-form subtitle workflow selectors for current supported integrated mode choices.
- Added translator workspace recovery so completed sidecars in a previous workspace can be copied back without rerunning the whole pipeline.
