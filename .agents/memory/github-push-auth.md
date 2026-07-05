---
name: GitHub push auth troubleshooting
description: How to diagnose failed git push to GitHub when the stored token/credential seems fine but push fails with "Bad credentials" / "Invalid username or token"
---

When `git push` to a GitHub remote fails with "Invalid username or token. Password authentication is not supported for Git operations." or similar, the credential embedded in the remote URL or provided token is invalid — regardless of format (username+token, x-access-token+token, etc.). Format is not the issue.

**Why:** GitHub PATs expire, get revoked, or are copy-pasted incorrectly. Retrying the same push with different URL formats wastes turns since the root cause is the token value itself, not git's auth mechanism.

**How to apply:**
- Verify a token directly against `https://api.github.com/user` (or the target repo endpoint) with `Authorization: Bearer <token>` before assuming a push will work.
- If verification returns 401 "Bad credentials", the token is invalid — ask the user for a fresh one rather than retrying git push with format variations.
- If the user pastes a secret directly into chat text (instead of the secure secret-entry field), treat it as already exposed: use it once to unblock, then re-request it through `requestEnvVar` (secure UI) and advise the user to rotate/revoke it.
