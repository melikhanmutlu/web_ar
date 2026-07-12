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
