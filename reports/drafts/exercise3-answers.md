# Proposed lab answers for PR-Demo #2

These are agent-drafted review requirements, not verified project policies or actual human answers. Awaiting reviewer input.

## 1. What is the policy for password hashing in this application? Should we use a stronger algorithm than MD5?

No password-hashing policy is provided in the diff, so I cannot confirm the project policy. For this lab review, require Argon2id or bcrypt with a unique salt and a migration plan for existing password hashes; do not treat MD5 as production-ready.

## 2. How should tokens be securely stored and managed? Is encryption required for tokens?

No authoritative token-storage policy is supplied. For this review, require an OS credential store or comparably protected storage, appropriately restricted access, expiration and revocation. Tokens need cryptographic randomness rather than a deterministic username/password/PID seed. The diff has not implemented these changes.

## 3. What is the expected behavior when a user attempts to sync without being logged in? Should we provide a user-friendly error message?

For this review, report a clear not-logged-in message and ask the user to log in, without sending a sync request. Do not suppress authentication failures or fabricate a token. The current diff raises RuntimeError; no test evidence is provided.

## 4. Is there a plan to implement user session management to replace the hard-coded user ID in `_current_user_id`?

The diff only promises session management in a future comment; no implemented session binding or verified project plan is available. Require the user ID to come from an authenticated session with server-side authorization. Also retain the visible interpolated SQL in Storage.add and the HTTP SYNC_URL as unresolved concerns; the answers do not fix the code.

