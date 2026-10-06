# v45 QA fixes

Base: main `504caca79550e9e38e0cd42ca84dc5771c25d294`. Existing main/v44 branches are unchanged. v44's zero-rotation preset behavior is already implemented on this main baseline through pending camera persistence; no blind cherry-pick was performed.

## Addressed findings

- QA-01: STEP/STP were missing from both staging extensions and conversion dispatch. Direct/ZIP/batch staging now recognizes them; dispatch uses STEPConverter (embedded units preserved). Added staging/dispatch regressions and a real STEP upload-to-loaded-Viewer browser test.
- QA-02: Scene selection now removes the `hidden` class. Browser regression selects/deselects fields, sets position, builds two models and loads the resulting scene.
- QA-03: Daily admin analytics uses portable date rendering instead of Windows-incompatible `%-d`.
- QA-04: main already excludes the AR/slicer script from the marketing demo. Added a null-ID guard in the shared status poll and a browser assertion against null/undefined model API calls.
- QA-05: Mobile site navigation closes on Escape (returning focus) and outside click with synchronized expanded state.
- QA-06: Captured stack identifies model-viewer 4.2.0 ARRenderer.onUpdateScene creating an XR menu with presentedScene=null during ordinary transform updates. The vendored bundle now returns early outside an active AR presentation. `scripts/patch_model_viewer_ar.cjs` documents and reproducibly applies the exact guarded change; it fails closed on an unexpected vendor layout. Re-evaluate this patch on vendor upgrades. Physical AR still requires device validation.
- Additional reproduced issue: measurement result overlay intercepted Tools controls. It now sits below Tools.
- Additional reproduced issue: on a 1280x720 desktop, the QR toolbar intercepted the Save button. Desktop Tools now reserves bottom-toolbar space; mobile sheet rules remain intact.
- Upload E2E helper uses Studio, waits for a loaded model and dismisses onboarding. Hotspot regression closes the overlapping Tools sheet. Transform regression uses a real numeric input and asserts no page errors, preserving the actual save-payload assertions.
- Reviewed npm advisories and updated the lockfile within existing declared semver ranges (no force/major override). npm audit reports zero advisories. glTF Transform CLI is 4.5.0; runtime requirements remain compatible with the Node 20 Docker setup (sharp requires >=20.9).

## Verification

- 43 focused Python tests passed: upload staging, STEP conversion with real dimensional checks, scenes, admin daily analytics and demo rendering.
- 12 desktop/mobile Chromium checks passed: real STEP upload, mobile navigation dismissal, demo requests, two-model scene build, measurements and undo-to-baseline transform-only save. The last save check also asserts absence of page errors.
- Wider desktop Viewer run initially passed 9/11; its two failures exposed the measurement/save overlaps above. Both passed after fixes and are included in the final 12 checks.
- JavaScript/inline template lint passed. npm audit: 0 vulnerabilities.
- Full Python suite and entire cross-browser matrix were not rerun in this change set. Prior v44 results must not be relabeled as v45 results.

## Still requires separate acceptance

No claim of exhaustive feature acceptance: the original report's Not tested rows remain pending unless covered above. Physical Android/iOS AR, real FBX assets, advanced sharing/organization/admin mutation flows and paid-provider integration require the original acceptance checklist. Local USDZ conversion is blocked by missing Blender, not repaired by this frontend patch. No production data, deployment or paid-provider actions were performed.

## Repeat

```powershell
$env:PYTHON_DOTENV_DISABLED='1'
python -m pytest -q tests/test_upload_staging.py tests/test_step_converter.py tests/test_scenes.py tests/test_admin_analytics_day.py tests/test_home_viewer_demo.py
npm run lint
npm audit
npx playwright test tests/e2e/qa_v45.spec.js tests/e2e/viewer_tools.spec.js --workers=1 --grep 'STEP upload|mobile navigation|static demo|Scene Builder selected|undo back to baseline|measure tool lives'
```

Use only isolated local test data. Playwright traces can contain disposable credentials and capability tokens; do not publish raw traces.
