const { test, expect } = require('@playwright/test');
const { uploadCubeAndGetViewerUrl } = require('./helpers/upload');

test('measure tool draws line, XYZ breakdown, and saves', async ({ page }) => {
  await uploadCubeAndGetViewerUrl(page); // /view/<id>?edit_token=... (canEdit)

  await page.waitForFunction(() => {
    const mv = document.getElementById('modelViewer');
    return mv && mv.loaded;
  }, { timeout: 20000 });

  // Auto-confirm the "name this measurement" prompt.
  page.on('dialog', d => d.accept('my-measure'));

  await page.click('#measureToolButton');
  await expect(page.locator('#measureToolResult')).toBeVisible();

  // Click two points on the cube (centre-ish, offset apart).
  const mv = page.locator('#modelViewer');
  const box = await mv.boundingBox();
  await page.mouse.click(box.x + box.width * 0.42, box.y + box.height * 0.45);
  await page.mouse.click(box.x + box.width * 0.58, box.y + box.height * 0.58);

  // Panel shows the distance rows.
  await expect(page.locator('.mt-row-total')).toContainText('Distance:', { timeout: 5000 });
  await expect(page.locator('.mt-row-x')).toBeVisible();

  // The straight line is drawn.
  const totalVisible = await page.getAttribute('.mt-line-total', 'visibility');
  expect(totalVisible).toBe('visible');

  // Toggle XYZ breakdown -> axis lines become visible.
  await page.locator('#mtXYZ').check();
  await expect.poll(async () => page.getAttribute('.mt-line-x', 'visibility')).toBe('visible');

  // Save -> appears in the saved list, and reload shows it persisted.
  await page.locator('#mtSave').click();
  await expect(page.locator('.mt-saved-load')).toContainText('my-measure', { timeout: 5000 });

  await page.reload();
  await page.waitForFunction(() => {
    const m = document.getElementById('modelViewer');
    return m && m.loaded;
  }, { timeout: 20000 });
  await page.click('#measureToolButton');
  await expect(page.locator('.mt-saved-load')).toContainText('my-measure', { timeout: 5000 });
});

test('measure mode disables tap-to-recenter, sets cursor, and shows point instantly', async ({ page }) => {
  await uploadCubeAndGetViewerUrl(page);
  await page.waitForFunction(() => {
    const mv = document.getElementById('modelViewer');
    return mv && mv.loaded;
  }, { timeout: 20000 });

  const mv = page.locator('#modelViewer');

  // Enter measure mode: disable-tap set + crosshair cursor class present.
  await page.click('#measureToolButton');
  expect(await mv.evaluate(el => el.hasAttribute('disable-tap'))).toBe(true);
  await expect(mv).toHaveClass(/measure-cursor/);

  // Camera must NOT move when clicking a measure point.
  const before = await mv.evaluate(el => el.getCameraOrbit().toString() + '|' + el.getCameraTarget().toString());
  const box = await mv.boundingBox();
  await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.5);
  // First point shows immediately.
  await expect(page.locator('.measure-dot')).toHaveCount(1, { timeout: 3000 });
  const after = await mv.evaluate(el => el.getCameraOrbit().toString() + '|' + el.getCameraTarget().toString());
  expect(after).toBe(before);

  // Leaving measure mode restores tap + clears cursor.
  await page.click('#measureToolButton');
  expect(await mv.evaluate(el => el.hasAttribute('disable-tap'))).toBe(false);
  await expect(mv).not.toHaveClass(/measure-cursor/);
});

test('mesh/wireframe overlay toggles when internal scene is reachable', async ({ page }) => {
  await uploadCubeAndGetViewerUrl(page);
  await page.waitForFunction(() => {
    const mv = document.getElementById('modelViewer');
    return mv && mv.loaded;
  }, { timeout: 20000 });

  const hasInternals = await page.evaluate(() => !!(window._getMvInternals && window._getMvInternals()));
  test.skip(!hasInternals, 'model-viewer internal scene not reachable in this build');

  await page.click('#measureToolButton');
  const countWire = () => page.evaluate(() => {
    let n = 0;
    window._getMvInternals().scene.traverse(o => { if (o.userData && o.userData._measureWire) n++; });
    return n;
  });
  expect(await countWire()).toBe(0);
  await page.locator('#mtWire').check();
  await expect.poll(countWire).toBeGreaterThan(0);
  await page.locator('#mtWire').uncheck();
  await expect.poll(countWire).toBe(0);
});
