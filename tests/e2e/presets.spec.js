const { test, expect } = require('@playwright/test');
const { uploadCubeAndGetViewerUrl } = require('./helpers/upload');

test('material + lighting presets apply live', async ({ page }) => {
  await uploadCubeAndGetViewerUrl(page); // lands on /view/<id>?edit_token=... (canEdit)

  await page.waitForFunction(() => {
    const mv = document.getElementById('modelViewer');
    return mv && mv.loaded;
  }, { timeout: 20000 });

  await page.click('#toolsPanelToggle');

  // ── Lighting preset: Dramatic → exposure 0.7, shadow 2.2 ──
  await page.click('#lightingContainer .tp-section-header');
  await page.click('.lighting-preset-btn[data-preset="dramatic"]');
  expect(await page.evaluate(() => document.getElementById('modelViewer').exposure)).toBeCloseTo(0.7, 2);
  expect(await page.evaluate(() => document.getElementById('modelViewer').shadowIntensity)).toBeCloseTo(2.2, 2);
  expect(await page.textContent('#exposureValue')).toBe('0.70');

  // Manual exposure slider (real keyboard input → trusted event) drives
  // model-viewer live and clears the active preset highlight.
  await page.focus('#exposureSlider');
  await page.keyboard.press('ArrowRight');
  expect(await page.evaluate(() => document.getElementById('modelViewer').exposure)).toBeGreaterThan(0.7);
  expect((await page.$$('.lighting-preset-btn.is-active')).length).toBe(0);

  // ── Save Lighting persists (owner via edit_token) ──
  await page.click('#saveLighting');
  await expect(page.locator('#saveLightingStatus')).toContainText('Lighting saved.', { timeout: 5000 });

  // ── Material preset: Gold → metalness 1, roughness 0.28, gold color ──
  await page.click('#toolsDetailBackBtn');
  await page.click('#materialContainer .tp-section-header');
  await page.click('.material-preset-btn[data-preset="gold"]');
  expect(parseFloat(await page.$eval('#metalnessSlider', el => el.value))).toBeCloseTo(1.0, 2);
  expect(parseFloat(await page.$eval('#roughnessSlider', el => el.value))).toBeCloseTo(0.28, 2);
  expect((await page.$eval('#materialColorHex', el => el.value)).toUpperCase()).toBe('#E6B800');

  // The preset actually reached the live material.
  const liveMetal = await page.evaluate(() =>
    document.getElementById('modelViewer').model.materials[0].pbrMetallicRoughness.metallicFactor);
  expect(liveMetal).toBeCloseTo(1.0, 2);

  // ── Ground shadow on/off toggle ──
  await page.click('#toolsDetailBackBtn');
  await page.click('#lightingContainer .tp-section-header');
  const shadowNow = () => page.evaluate(() => document.getElementById('modelViewer').shadowIntensity);
  expect(await shadowNow()).toBeGreaterThan(0);
  await page.locator('#shadowToggle').uncheck();
  expect(await shadowNow()).toBe(0);
  await page.locator('#shadowToggle').check();
  expect(await shadowNow()).toBeGreaterThan(0);
});
