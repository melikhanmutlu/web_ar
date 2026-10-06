const { test, expect } = require('@playwright/test');
const { registerAndLogin } = require('./helpers/auth');
const { verifyUser } = require('./helpers/db');

// Happy path: a Business owner creates an organization, invites a teammate by
// email (no SMTP in e2e, so the UI hands over the link), and the teammate
// accepts from a second browser context and shows up in the member list.

test('owner creates an org, invites a teammate who accepts and is listed', async ({ browser }) => {
  test.setTimeout(90_000);
  const ownerCtx = await browser.newContext();
  const mateCtx = await browser.newContext();
  const owner = await ownerCtx.newPage();
  const mate = await mateCtx.newPage();

  const o = await registerAndLogin(owner, 'wsowner');
  verifyUser(o.email, 'business');
  const m = await registerAndLogin(mate, 'wsmate');
  verifyUser(m.email, 'free');

  await owner.goto('/workspace');
  await owner.locator('#orgName').fill('E2E Team');
  await owner.getByRole('button', { name: /create organization/i }).click();
  await owner.waitForURL(/\/workspace\/\d+$/);
  await expect(owner.locator('h1')).toHaveText('E2E Team');

  await owner.locator('#inviteEmail').fill(m.email);
  await owner.locator('#inviteRole').selectOption('editor');
  await owner.getByRole('button', { name: /send invitation/i }).click();
  const dlg = owner.locator('.ar-dialog');
  await expect(dlg).toBeVisible();
  const link = await dlg.locator('input').inputValue();
  expect(link).toContain('/invites/');
  await dlg.locator('[data-ar-dialog-confirm]').click();
  await expect(owner.getByText(m.email, { exact: true })).toBeVisible();

  await mate.goto(new URL(link).pathname);
  await mate.locator('#acceptInvite').click();
  await mate.waitForURL(/\/workspace\/\d+$/);
  await expect(mate.locator('h1')).toHaveText('E2E Team');
  await expect(mate.locator('#inviteForm')).toHaveCount(0); // editors do not manage people

  await owner.reload();
  const row = owner.locator('.dev-row', { hasText: m.username });
  await expect(row).toBeVisible();
  await expect(row.locator('select')).toHaveValue('editor');
  await expect(owner.locator('#invites')).toContainText('No pending invitations');

  await ownerCtx.close();
  await mateCtx.close();
});
