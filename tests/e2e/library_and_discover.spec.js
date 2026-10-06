const { test, expect } = require('@playwright/test');
const { registerAndLogin } = require('./helpers/auth');
const { uploadCubeAndGetViewerUrl } = require('./helpers/upload');

test('public model appears on the Discover page', async ({ page }) => {
  // Two extra full page loads (register + login) beyond the anonymous-only
  // upload flow other specs use push this past the default 30s budget.
  test.setTimeout(60_000);
  await registerAndLogin(page, 'discoverer');
  const viewerUrl = await uploadCubeAndGetViewerUrl(page);
  const modelId = viewerUrl.match(/\/view\/([^/?]+)/)[1];

  // No UI exists yet to flip visibility to public from the viewer page, so
  // drive the existing sharing API directly. Use the page's own fetch() (the
  // app's global wrapper attaches the CSRF token): page.request doesn't send
  // the Secure session cookie over plain http, which the e2e server uses.
  const patchOk = await page.evaluate(async (id) => {
    const resp = await fetch(`/api/models/${id}/sharing`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ visibility: 'public' }),
    });
    return resp.ok;
  }, modelId);
  expect(patchOk).toBeTruthy();

  await page.goto('/discover');
  await expect(page.locator(`article.model-card[data-model-id="${modelId}"]`)).toBeVisible();
});

test('library select mode reveals bulk action buttons', async ({ page }) => {
  test.setTimeout(60_000);
  await registerAndLogin(page, 'librarian');
  await uploadCubeAndGetViewerUrl(page);

  await page.goto('/my_models');
  await page.locator('#selectModeBtn').click();
  await page.locator('.model-checkbox').first().click();

  await expect(page.locator('#moveSelectedBtn')).toBeVisible();
  await expect(page.locator('#visibilitySelectedBtn')).toBeVisible();
  await expect(page.locator('#tagSelectedBtn')).toBeVisible();
  await expect(page.locator('#deleteSelectedBtn')).toBeVisible();
});

test('New Scene link opens the scene builder with the uploaded model listed', async ({ page }) => {
  test.setTimeout(60_000);
  await registerAndLogin(page, 'scenebuilder');
  await uploadCubeAndGetViewerUrl(page);

  await page.goto('/my_models');
  await page.getByRole('link', { name: /new scene/i }).click();
  await page.waitForURL(/\/scenes\/new/);
  await expect(page.locator('.scene-item-checkbox')).toHaveCount(1);
});
