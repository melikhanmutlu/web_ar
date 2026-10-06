// Shared helper: register a fresh throwaway account (registration logs in)
// via the real
// UI forms (not an API shortcut), so CSRF/session wiring is exercised the
// same way a real user would hit it.
async function registerAndLogin(page, usernamePrefix) {
  const username = `${usernamePrefix}${Date.now()}`;
  const email = `${username}@example.com`;
  const password = 'TestPassword123!';

  await page.goto('/register');
  await page.locator('input[name="username"]').fill(username);
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(password);
  await page.locator('input[name="confirm_password"]').fill(password);
  await page.getByRole('button', { name: /register/i }).click();
  // Registration signs the new user in and lands on the home page.
  await page.waitForURL((url) => !url.pathname.includes('/register'));

  return { username, email, password };
}

module.exports = { registerAndLogin };
