# Security

Samar stores provider keys and brokerage keys as envelope-encrypted ciphertext. Each secret has its own data key. `SAMAR_KEK` wraps that data key. The associated data is `user_id|kind`, so a ciphertext cannot be moved to another row. API responses show the last four characters only.

Set `SAMAR_KEK` to 64 hex characters before anyone else can open the database. If it is unset and `SAMAR_ENV` is empty or `dev`, `development`, `local`, or `test`, the process uses a public development key and prints a warning. Any other `SAMAR_ENV` refuses to start when the key is missing or equal to that development key.

A Public.com key is used to read accounts and, only after a typed confirmation, to send orders from `apps/api/src/samar_api/live/`. Live mode is off by default. The model never receives the brokerage token. A kill switch cancels orders Samar recorded and turns live mode off. A broker error, three broker rejections, an unexpected position, or the daily loss stop does the same.

This can lose real money. It is experimental and it is not investment advice.

## Reporting a vulnerability

Report vulnerabilities privately. Do not open a public issue that contains a live key, a database, or steps that would expose someone else's account.

Use GitHub private vulnerability reporting on this repository. Include the file path and the commit, with the secret redacted. Revoke a leaked provider key at the provider before you report it.
