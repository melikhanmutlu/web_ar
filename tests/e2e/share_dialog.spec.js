const { test, expect } = require('@playwright/test');
const { uploadCubeAndGetViewerUrl } = require('./helpers/upload');
const { registerAndLogin } = require('./helpers/auth');

test('owner can create, copy and revoke a share link from the viewer Share dialog', async ({ page }) => {
  test.setTimeout(60_000);
  await registerAndLogin(page, 'sharedlg');
  await uploadCubeAndGetViewerUrl(page);

  await page.locator('#shareButton').click();
  const dialog = page.getByRole('dialog', { name: /share model/i });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute('aria-modal', 'true');

  // Visibility defaults to private for new account uploads; switching shows the link + QR.
  await expect(dialog.getByRole('radio', { name: /private/i })).toBeChecked();
  await dialog.getByRole('radio', { name: /unlisted/i }).check();
  await expect(dialog.locator('#sdUrl')).toHaveValue(/\/view\//);
  await expect(dialog.locator('#sdQr img')).toBeVisible();

  // Secure link: create, then it shows in the active list and can be revoked.
  await dialog.getByRole('button', { name: 'Create link' }).click();
  await expect(dialog.locator('#sdNew input')).toHaveValue(/\/s\//);
  await expect(dialog.locator('#sdList .sd-link')).toHaveCount(1);
  await dialog.getByRole('button', { name: /revoke/i }).click();
  await expect(dialog.locator('#sdList .sd-link')).toHaveCount(0);

  // Esc closes and focus returns to the Share button.
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(page.locator('#shareButton')).toBeFocused();
});
