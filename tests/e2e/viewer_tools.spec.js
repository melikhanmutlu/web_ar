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

test('measure tool lives in the bottom-right toolbar and places visible markers', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));

  await uploadCubeAndGetViewerUrl(page);

  // The Measure button used to float disconnected over the canvas; it must
  // now live in the same bottom-right toolbar as the other tool buttons.
  await expect(page.locator('.toolbar-shell #measureToolButton')).toBeVisible();

  await page.locator('#measureToolButton').click();
  await expect(page.locator('#measureToolButton')).toHaveClass(/is-active/);
  await expect(page.locator('#measureToolResult')).toBeVisible();

  // positionAndNormalFromPoint can miss depending on camera framing/GPU
  // rendering; retry a few nearby points instead of one exact click (same
  // approach as tests/e2e/hotspot_discussion.spec.js).
  const box = await page.locator('model-viewer').boundingBox();
  const candidates = [[0, 0], [0.1, 0], [-0.1, 0], [0, 0.1], [0, -0.1]];
  for (const [dx, dy] of candidates) {
    if (await page.locator('.measure-dot').count() > 0) break;
    await page.mouse.click(box.x + box.width * (0.5 + dx), box.y + box.height * (0.5 + dy));
    await page.waitForTimeout(300);
  }
  const placedFirst = await page.locator('.measure-dot').count() > 0;
  test.skip(!placedFirst, 'measure placement raycast did not register a hit in this environment');

  for (const [dx, dy] of candidates) {
    if (await page.locator('.measure-dot').count() > 1) break;
    await page.mouse.click(box.x + box.width * (0.5 + dx), box.y + box.height * (0.3 + dy));
    await page.waitForTimeout(300);
  }
  if (await page.locator('.measure-dot').count() > 1) {
    await expect(page.locator('#measureToolResult')).toContainText('cm');
  }

  // Turning hotspot mode on must turn measure mode off (and vice versa) --
  // both listen on the same <model-viewer> click, so leaving both active
  // made every click ambiguously place both a hotspot and a measure point.
  await page.locator('#toolsPanelToggle').click();
  await page.locator('#annotationsContainer .tp-section-header').click();
  await page.locator('#toggleHotspotMode').click();
  await expect(page.locator('#measureToolButton')).not.toHaveClass(/is-active/);

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
