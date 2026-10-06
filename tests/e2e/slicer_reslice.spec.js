const { test, expect } = require('@playwright/test');
const { uploadCubeAndGetViewerUrl } = require('./helpers/upload');

// model-viewer re-centres the model on screen, while the slider values and the
// server cut use the file's own coordinates. The two only agree while the
// model is centred on the origin -- so the second slice of a model whose
// centre the first slice moved used to preview a cut offset by that shift.

// Lit pixels of the (white) cube; the ground shadow is dark and is drawn
// whether or not the clip hides the mesh, so it must not count.
async function cubePixels(page) {
  return page.evaluate(async () => {
    const blob = await document.querySelector('model-viewer').toBlob({ mimeType: 'image/png' });
    const img = await createImageBitmap(blob);
    const c = new OffscreenCanvas(img.width, img.height);
    const ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0);
    const px = ctx.getImageData(0, 0, img.width, img.height).data;
    let n = 0;
    for (let i = 0; i < px.length; i += 4) if (px[i + 3] > 200 && px[i] > 128) n++;
    return n;
  });
}

test('slicer preview matches the model after an earlier slice moved its centre', async ({ page }) => {
  test.setTimeout(90_000);
  const url = await uploadCubeAndGetViewerUrl(page);
  const id = url.split('/view/')[1].split(/[?#]/)[0];

  // First slice: keep x >= 0, so the saved cube spans x 0..0.1 (centre 0.05).
  const first = await page.evaluate(async (id) => (await fetch('/slice_model', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_id: id, planes: [{ plane_origin: [0, 0, 0], plane_normal: [1, 0, 0], keep_side: 'positive' }] }),
  })).json(), id);
  expect(first.success).toBe(true);

  await page.reload();
  await page.waitForFunction(() => document.querySelector('model-viewer')?.loaded);
  const onboardingDismiss = page.locator('#onboardingDismiss');
  if (await onboardingDismiss.isVisible()) await onboardingDismiss.click();

  // Preview a second cut at the slider's default -- the new centre, x = 0.05 --
  // keeping each side in turn: the two halves must look about the same size.
  // In the shifted on-screen frame the cube spans -0.05..0.05, so the old
  // preview cut it at its edge instead (measured ratio 0.24-0.31; fixed ~1.0).
  await page.locator('#toolsPanelToggle').click();
  const back = page.locator('#toolsDetailBackBtn');
  if (await back.isVisible()) await back.click();
  await page.locator('#slicerContainer .tp-section-header').click();
  await page.waitForTimeout(500);
  const whole = await cubePixels(page);

  // Poll until each preview has actually rendered (the clip shader compiles
  // asynchronously) instead of guessing a delay.
  await page.locator('.slicer-axis-toggle[data-axis="x"]').check();
  await expect(page.locator('.slicer-val[data-axis="x"]')).toHaveText('5.0 cm');
  await expect.poll(() => cubePixels(page)).toBeLessThan(whole * 0.9);
  const keepPositive = await cubePixels(page);

  await page.locator('.slicer-side-btn[data-axis="x"][data-side="negative"]').click();
  await expect.poll(() => cubePixels(page)).not.toBe(keepPositive);
  const keepNegative = await cubePixels(page);

  expect(Math.min(keepPositive, keepNegative) / Math.max(keepPositive, keepNegative),
    `keep +X: ${keepPositive}px, keep -X: ${keepNegative}px`).toBeGreaterThan(0.7);
});
