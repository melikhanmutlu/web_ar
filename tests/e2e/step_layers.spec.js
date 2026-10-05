const path = require('path');
const { test, expect } = require('@playwright/test');
const { isUnexpectedError, uploadFileAndGetViewerUrl } = require('./helpers/upload');

// Same fixture as tests/test_step_converter.py: 5 parts, one bolt placed 4
// times, ISO 10303-21 escaped (Turkish) part names.
const STEP_ASSEMBLY = path.join(__dirname, '..', 'fixtures', 'step', 'assembly_unicode.step');

test('STEP assembly uploads as grouped, toggleable layers with a filled section', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));

  await uploadFileAndGetViewerUrl(page, STEP_ASSEMBLY);

  await page.locator('#toolsPanelToggle').click();
  await page.locator('#layersContainer .tp-section-header').click();
  const rows = page.locator('#layersList > div');
  await expect(rows).toHaveCount(5);
  const bolts = rows.filter({ hasText: 'Cıvata' });
  await expect(bolts).toContainText('×4');

  // One click hides all four bolt instances.
  await bolts.locator('.layer-vis-btn').click();
  const hidden = await page.evaluate(() => {
    let count = 0;
    window._getMvInternals?.()?.scene?._model?.traverse((o) => { if (o.isMesh && !o.visible) count++; });
    return count;
  });
  expect(hidden).toBe(4);

  const back = page.locator('#toolsDetailBackBtn');
  if (await back.isVisible()) await back.click();
  await page.locator('#slicerContainer .tp-section-header').click();
  await expect(page.locator('#slicerFillCaps')).toBeChecked();
  await page.locator('.slicer-axis-toggle[data-axis="z"]').check();

  const unexpected = errors.filter(isUnexpectedError);
  expect(unexpected, `unexpected page errors: ${unexpected.join('\n')}`).toEqual([]);
});
