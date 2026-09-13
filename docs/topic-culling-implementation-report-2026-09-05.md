# Topic Workspace culling implementation report

## Outcome

The Topic Workspace culling workflow is implemented as a topic-scoped, reversible
workflow. Viewing a photo does not select it; picking and rejecting are explicit
actions persisted in the catalog. The Collage handoff now requests only persisted
picked photos and refuses an empty or invalid 2–20 photo scope.

Candidate generation is now asynchronous. The previous synchronous endpoint made
the browser wait about 70 seconds for the user’s 18-photo run with no feedback;
the UI now polls a job and shows stage/progress or a readable failure.

## Implemented

- Paginated Topic Workspace photo API with section and picks-only filters.
- Persistent `pick`, `reject`, and `clear` decisions in migration 26.
- Grid cards with separate Inspect and Pick controls.
- Loupe viewer with previous/next, fit, zoom, pan, detailed preview and optional
  original loading.
- Two-up Compare mode with synchronized zoom/pan and winner/challenger actions.
- Same-source nearby-capture grouping, explicitly labelled as a time-based aid,
  not an AI quality judgement.
- Keyboard controls: arrows, P/Space, X, C and Esc.
- Create section, add picks to an existing section, unlink picks, and preserve
  scope in session storage.
- Collage handoff with `culling=picks`, bounded to the persisted topic picks.
- Asynchronous collage generation jobs with progress polling and explicit failed
  states, so long candidate generation no longer blocks the browser request.
- Bounded grid pages and on-demand higher-resolution inspection.

## Verification

- `node --test tests/test_culling_state.test.js`: 3 passed.
- `PYTHONPATH=src python3 -m unittest tests/test_culling.py tests/test_topic_sections.py tests/test_web.py tests/test_collage_poc.py tests/test_collage_jobs.py`: 17 passed.
- JavaScript syntax checks passed for the culling controller, state helpers and
  collage handoff script.
- Isolated culling API test passed for pagination, persistence, pick filtering
  and clearing.
- Restarted the local server with the verified two-Pixel catalog and verified:
  `/api/culling/<topic>/decisions` returns HTTP 200 and Topic photo pagination
  returns the expected total and `next_offset`.
- Reproduced the user’s 18-photo / 20-candidate run: it completed in about 70
  seconds. The request now returns HTTP 202 immediately and the job endpoint
  reports progress until the same 20 candidates are available.

## Remaining limitations

- Browser automation could not complete a full click-through after the server
  restart in this environment; the HTTP/API smoke checks and automated tests are
  green, but a human should still perform one visible Grid → Compare → Pick →
  Section → Collage run.
- The current similarity aid is capture-time/source grouping. It does not claim
  face, blink, blur or expression intelligence.
- There is no configured frontend bundler/type-check command in this repository;
  validation is currently native-browser JavaScript syntax plus Node tests.
- Existing unrelated working-tree changes remain untouched and are not included
  in this feature report.

## Recommended next step

Open the running Topic Workspace, pick two or more photos, create a section, then
choose **Create collage from picks**. Confirm that the collage page says picked
photos only and that its photo count matches the pick count before generating.
