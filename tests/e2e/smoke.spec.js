const { test, expect } = require('@playwright/test');

test('studio upload experience renders the current upload contract', async ({ page }) => {
  await page.goto('/studio');
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

test('wrong password shows a visible, uncovered error message', async ({ page }) => {
  await page.goto('/login');
  await page.locator('input[name="username"]').fill('nobody-here');
  await page.locator('input[name="password"]').fill('wrong-password');
  await page.getByRole('button', { name: /login/i }).click();
  const alert = page.locator('#login-error');
  await expect(alert).toBeVisible();
  await expect(alert).toContainText(/invalid username/i);
  await expect(page.locator('input[name="username"]')).toHaveValue('nobody-here');
  // Nothing (e.g. the decorative aurora background) may paint over the message.
  const covered = await alert.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return !(top === el || el.contains(top));
  });
  expect(covered).toBe(false);
});
