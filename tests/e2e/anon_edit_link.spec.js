const { test, expect } = require('@playwright/test');
const { uploadCubeAndGetViewerUrl } = require('./helpers/upload');

test('anonymous upload: edit_token is removed from the URL, editing still works, banner offers the edit link', async ({ page }) => {
  test.setTimeout(60_000);
  const viewerUrl = await uploadCubeAndGetViewerUrl(page);
  const modelId = viewerUrl.match(/\/view\/([^/?]+)/)[1];

  // Address bar and canonical (QR / copy) URL are token-free.
  expect(page.url()).not.toContain('edit_token');
  expect(await page.evaluate(() => window.canonicalViewerUrl())).not.toContain('edit_token');

  // The session still carries the edit capability.
  const ok = await page.evaluate(async (id) => (await fetch(`/api/models/${id}/viewer-settings`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ show_ar: true }),
  })).ok, modelId);
  expect(ok).toBeTruthy();

  const banner = page.locator('#anonOwnerBanner');
  await expect(banner).toBeVisible();
  await expect(banner.getByRole('link', { name: /create an account/i })).toHaveAttribute('href', /\/register\?next=/);
  await banner.getByRole('button', { name: 'Dismiss' }).click();
  await expect(banner).toBeHidden();
});
