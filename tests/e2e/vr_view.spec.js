const { test, expect } = require('@playwright/test');
const { uploadCubeAndGetViewerUrl } = require('./helpers/upload');

// Regression guard: the VR page loaded A-Frame from a CDN AND the app-wide CSP
// forbade 'unsafe-eval' (which A-Frame needs), so /vr/<id> rendered pitch
// black -- AFRAME never initialised. A-Frame is now vendored and the VR route
// serves a CSP that permits 'unsafe-eval'. This asserts the scene actually
// starts rendering (a real canvas with non-zero size), not a black screen.
test('VR page boots A-Frame and starts rendering', async ({ page }) => {
  const viewerUrl = await uploadCubeAndGetViewerUrl(page);
  const modelId = viewerUrl.match(/\/view\/([^/?]+)/)[1];

  await page.goto(`/vr/${modelId}`);
  await page.waitForSelector('a-scene', { state: 'attached', timeout: 15000 });

  await expect
    .poll(
      async () =>
        page.evaluate(() => {
          const scene = document.querySelector('a-scene');
          return !!(window.AFRAME && scene && scene.renderStarted);
        }),
      { timeout: 25000 }
    )
    .toBe(true);

  const canvasWidth = await page.evaluate(() => {
    const canvas = document.querySelector('a-scene canvas.a-canvas');
    return canvas ? canvas.width : 0;
  });
  expect(canvasWidth).toBeGreaterThan(0);
});
