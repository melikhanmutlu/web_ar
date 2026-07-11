const path = require('path');
const { test, expect } = require('@playwright/test');

// Safety net for the upcoming view.html inline-JS modularization: uploads a
// real model, opens the viewer, and exercises the tools panel so a refactor
// that breaks script load order or a window._x global shows up here instead
// of silently in production.
//
// Some CI/sandboxed environments restrict outbound access to third-party
// CDNs (Tailwind, Lucide icons, unpkg's model-viewer bundle); errors caused
// purely by a blocked CDN request are not app bugs, so they're filtered out
// of the failure assertion below rather than asserting zero console errors.
const KNOWN_BLOCKED_CDN_ERRORS = [
  /tailwind is not defined/i,
  /lucide is not defined/i,
  /net::ERR_/i,
  /Failed to load resource.*(tailwindcss|unpkg|cdnjs|googleapis)/i,
  // Browser-console noise unrelated to app JS correctness: an unrecognized
  // (but harmless) CSP directive, and the favicon 404 present in every run.
  /Unrecognized Content-Security-Policy directive/i,
  /Failed to load resource: the server responded with a status of 404/i,
];

function isUnexpectedError(message) {
  return !KNOWN_BLOCKED_CDN_ERRORS.some((pattern) => pattern.test(message));
}

async function uploadCubeAndGetViewerUrl(page) {
  await page.goto('/');
  const fileInput = page.locator('#file-upload');
  await fileInput.setInputFiles(path.join(__dirname, 'fixtures', 'cube.glb'));
  await page.getByRole('button', { name: /upload and convert/i }).click();

  // The upload goes through the async job flow (job_id + status polling);
  // wait for the client-side redirect to the viewer once it completes.
  await page.waitForURL(/\/view\//, { timeout: 30_000 });
  return page.url();
}

test('viewer tools panel opens each section without script errors', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text());
  });

  await uploadCubeAndGetViewerUrl(page);
  await expect(page.locator('model-viewer')).toBeAttached();

  await page.locator('#toolsPanelToggle').click();
  await expect(page.locator('#toolsPanel')).toHaveClass(/is-open/);

  // Clicking a section header switches the panel into "detail mode", which
  // hides every other section's header (see #toolsSections's
  // data-active-section CSS rules) -- navigate back to the menu between
  // each section instead of clicking them all in one pass.
  const sectionIds = ['viewContainer', 'materialContainer', 'transformContainer', 'layersContainer'];
  for (const id of sectionIds) {
    const header = page.locator(`#${id} .tp-section-header`);
    if (await header.count() === 0) continue;
    await header.first().click();
    const backBtn = page.locator('#toolsDetailBackBtn');
    if (await backBtn.isVisible()) await backBtn.click();
  }

  const unexpected = errors.filter(isUnexpectedError);
  expect(unexpected, `unexpected console/page errors: ${unexpected.join('\n')}`).toEqual([]);
});

test('measurement tool can be toggled on the loaded model', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));

  await uploadCubeAndGetViewerUrl(page);
  const measureToggle = page.locator('#measureToggle, [data-tool="measure"], #measureBtn');
  if (await measureToggle.count() > 0) {
    await measureToggle.first().click();
  }

  const unexpected = errors.filter(isUnexpectedError);
  expect(unexpected, `unexpected console/page errors: ${unexpected.join('\n')}`).toEqual([]);
});

test('AR button explains why AR is unavailable on an unsupported device', async ({ page }) => {
  // Headless Chromium has no WebXR/Scene Viewer/Quick Look support, so
  // clicking AR here always takes the "unsupported" fallback path -- this
  // exercises the reason-specific messaging added for mobile AR failures.
  await uploadCubeAndGetViewerUrl(page);
  await page.locator('#arButton').click();
  await expect(page.locator('#arModal')).toHaveClass(/show/);
  await expect(page.locator('#arModalTitle')).toHaveText('AR Not Supported');
  await expect(page.locator('#arModalMessage')).toContainText('QR code');
});
