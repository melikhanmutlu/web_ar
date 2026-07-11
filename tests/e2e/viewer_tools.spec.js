const { test, expect } = require('@playwright/test');
const { isUnexpectedError, uploadCubeAndGetViewerUrl } = require('./helpers/upload');

// Safety net for the upcoming view.html inline-JS modularization: uploads a
// real model, opens the viewer, and exercises the tools panel so a refactor
// that breaks script load order or a window._x global shows up here instead
// of silently in production.

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

test('undo/redo steps a material change back and forth', async ({ page }) => {
  await uploadCubeAndGetViewerUrl(page);
  await page.locator('#toolsPanelToggle').click();
  await page.locator('#materialContainer .tp-section-header').click();

  const roughnessSlider = page.locator('#roughnessSlider');
  await expect(page.locator('#undoButton')).toBeDisabled();

  // Move the slider and commit the change. range inputs need an explicit
  // "change" dispatch (undo-redo.js snapshots on "change", not "input") --
  // fill() alone doesn't reliably fire it for <input type="range">.
  await roughnessSlider.evaluate((el) => {
    el.value = '0.4';
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await expect(page.locator('#undoButton')).toBeEnabled();
  await expect(roughnessSlider).toHaveValue('0.4');

  await page.locator('#undoButton').click();
  await expect(roughnessSlider).toHaveValue('1');
  await expect(page.locator('#redoButton')).toBeEnabled();

  await page.locator('#redoButton').click();
  await expect(roughnessSlider).toHaveValue('0.4');
});
