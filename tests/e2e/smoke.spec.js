const { test, expect } = require('@playwright/test');

test('home upload experience renders the current upload contract', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/arvision/i);
  await expect(page.locator('#uploadForm')).toHaveAttribute('action', '/upload_model');
  await expect(page.locator('#file-upload')).toHaveAttribute('accept', /\.zip/);
  await expect(page.getByRole('button', { name: /upload and convert/i })).toBeDisabled();
  await expect(page.locator('#compression')).toHaveValue('none');
});

test('health and retired endpoints expose production contracts', async ({ request }) => {
  const health = await request.get('/healthz');
  expect(health.ok()).toBeTruthy();
  expect((await health.json()).database).toBe('up');
  expect((await request.post('/upload')).status()).toBe(410);
  expect((await request.post('/convert', { data: { modelId: 'legacy' } })).status()).toBe(410);
});

test('authentication shell is usable on mobile', async ({ page }) => {
  await page.goto('/login');
  await expect(page.locator('input[name="username"]')).toBeVisible();
  await expect(page.locator('input[name="password"]')).toBeVisible();
});
