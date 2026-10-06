# Security advisories accepted

`npm run security` (`scripts/npm_audit_check.py`) fails CI on any high/critical
`npm audit --omit=dev` finding except the reviewed ones below. `npm audit` has
no ignore list, so an unfixable advisory would otherwise keep CI red and hide
every other failure behind it. The allowlist is the `ACCEPTED` dict in that
script; each entry needs a reason and an exit condition.

## braces: GHSA-vfj7-8cjw-p6xm

- **What:** stack exhaustion in `braces` when expanding deeply nested brace
  patterns (a denial-of-service class issue).
- **Why accepted:** no fixed `braces` release exists yet. `braces` is a
  transitive dependency of `@gltf-transform/cli` (via its glob handling), a
  build/conversion-time tool that the server invokes with file paths it builds
  itself. No user-supplied glob pattern ever reaches it, so the vulnerable
  input is not attacker-reachable. It is not shipped to browsers.
- **When to remove the exception:** as soon as a patched `braces` is published
  and reachable through `@gltf-transform/cli`'s dependency range (or a newer
  `@gltf-transform/cli` pins it). Then:
  1. `npm update braces` (or bump `@gltf-transform/cli`) and commit
     `package-lock.json`.
  2. Delete the `GHSA-vfj7-8cjw-p6xm` entry from `ACCEPTED` in
     `scripts/npm_audit_check.py`.
  3. Run `npm run security`; it must pass without the exception.
- **How a fix gets proposed:** `.github/dependabot.yml` has an `npm` ecosystem
  (weekly), so Dependabot opens a PR when a fixed release becomes available.
  Review that PR as the trigger for the removal steps above. Re-check this note
  whenever `npm run security` output changes.
