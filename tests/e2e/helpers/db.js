// Test-only shortcut: flip account flags straight in the e2e SQLite DB (there is
// no UI to mark an email verified without a mailbox, or to buy a plan).
// E2E_DB overrides the default Flask instance path used by playwright.config.js.
const path = require('path');
const { execFileSync } = require('child_process');

function dbPath() {
  return process.env.E2E_DB || path.join(__dirname, '..', '..', '..', 'instance', 'e2e.db');
}

/** Marks the user's email verified and optionally sets their plan. */
function verifyUser(email, plan) {
  const script = [
    'import sqlite3, sys',
    'con = sqlite3.connect(sys.argv[1])',
    "con.execute('UPDATE \"user\" SET email_verified_at = CURRENT_TIMESTAMP WHERE email = ?', (sys.argv[2],))",
    "if sys.argv[3]: con.execute('UPDATE \"user\" SET plan = ? WHERE email = ?', (sys.argv[3], sys.argv[2]))",
    'con.commit()',
  ].join('\n');
  execFileSync(process.env.E2E_PYTHON || 'python', ['-c', script, dbPath(), email, plan || '']);
}

module.exports = { verifyUser };
