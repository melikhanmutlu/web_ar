const path = require('path');
const { test, expect } = require('@playwright/test');

// Multi-file upload: each selected file becomes its own independent
// ConversionJob (blueprints/upload.py's /api/uploads/batch), tracked with
// its own progress row (templates/index.html's submitBatchUpload/pollBatchJob)
// instead of the single-file progress bar.

test('selecting multiple files converts each as its own job with a progress row', async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto('/');
  await page.locator('#file-upload').setInputFiles([
    path.join(__dirname, 'fixtures', 'cube.glb'),
    path.join(__dirname, 'fixtures', 'cube2.stl'),
  ]);

  await expect(page.locator('#batchNote')).toBeVisible();
  const selectedSummary = await page.locator('#selectedFileName').innerText();
  expect(selectedSummary).toContain('Selected 2 file(s)');

  await page.locator('#submitBtn').click();
  await expect(page.locator('#batchUploadList')).toBeVisible();
  await expect(page.locator('.batch-row')).toHaveCount(2);

  await expect(page.locator('.batch-row-status.is-done')).toHaveCount(2, { timeout: 30_000 });
  await expect(page.locator('.batch-row-link')).toHaveCount(2);

  const links = await page.locator('.batch-row-link').evaluateAll((els) => els.map((el) => el.href));
  expect(links.every((href) => href.includes('/view/'))).toBe(true);
});

test('a single selected file still uses the classic single-file progress UI', async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto('/');
  await page.locator('#file-upload').setInputFiles(path.join(__dirname, 'fixtures', 'cube.glb'));

  await expect(page.locator('#batchNote')).toBeHidden();
  await page.locator('#submitBtn').click();
  await page.waitForURL(/\/view\//, { timeout: 30_000 });
});
