const { test, expect } = require('@playwright/test');
const { registerAndLogin } = require('./helpers/auth');
const { uploadCubeAndGetViewerUrl } = require('./helpers/upload');
const path = require('path');

test('STEP upload converts to a loaded Viewer model', async ({ page }) => {
  test.setTimeout(90000);
  await page.goto('/studio');
  await page.locator('#file-upload').setInputFiles(path.join(__dirname, '..', 'fixtures', 'featuretype.step'));
  await page.getByRole('button', { name: /upload and convert/i }).click();
  await page.waitForURL(/\/view\//, { timeout: 60000 });
  await page.waitForFunction(() => document.querySelector('model-viewer')?.loaded, { timeout: 20000 });
});

test('mobile navigation dismisses with Escape and outside click', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  const burger = page.locator('#navBurger');
  const menu = page.locator('#mobileMenu');
  await burger.click();
  await expect(menu).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(menu).toBeHidden();
  await expect(burger).toHaveAttribute('aria-expanded', 'false');
  await expect(burger).toBeFocused();
  await burger.click();
  await page.locator('h1').click();
  await expect(menu).toBeHidden();
});

test('static demo does not request null model endpoints', async ({ page }) => {
  const invalid = [];
  page.on('request', request => {
    if (/\/api\/models\/(null|undefined)\//.test(request.url())) invalid.push(request.url());
  });
  await page.goto('/demo/viewer');
  await expect(page.locator('model-viewer')).toBeVisible();
  await page.waitForTimeout(2000);
  expect(invalid).toEqual([]);
});

test('Scene Builder selected model fields are editable and hide on deselection', async ({ page }) => {
  test.setTimeout(60000);
  await registerAndLogin(page, 'scene-v45');
  await uploadCubeAndGetViewerUrl(page);
  await page.goto('/scenes/new');
  const checkbox = page.locator('.scene-item-checkbox').first();
  const x = page.locator('.scene-pos-x').first();
  await expect(x).toBeHidden();
  await checkbox.check();
  await expect(x).toBeVisible();
  await x.fill('0.5');
  await expect(x).toHaveValue('0.5');
  await checkbox.uncheck();
  await expect(x).toBeHidden();
  await uploadCubeAndGetViewerUrl(page);
  await page.goto('/scenes/new');
  await page.locator('.scene-item-checkbox').nth(0).check();
  await page.locator('.scene-item-checkbox').nth(1).check();
  await page.locator('.scene-pos-x').nth(1).fill('0.5');
  await page.locator('#buildSceneBtn').click();
  await page.waitForURL(/\/view\//);
  await page.waitForFunction(() => document.querySelector('model-viewer')?.loaded);
});
