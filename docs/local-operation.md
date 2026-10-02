# Local operation and API clients

CatLabel listens on `127.0.0.1:8000` by default. Open `http://localhost:8000` on the same computer. Normal local use needs no access token. The launcher opens the configured application URL after the server answers.

## Optional LAN access

Set these variables before starting CatLabel:

| Variable | Value |
| --- | --- |
| `CATLABEL_HOST` | The computer's LAN address, or `0.0.0.0` for all IPv4 interfaces |
| `CATLABEL_PORT` | Port from 1 to 65535; default `8000` |
| `CATLABEL_ACCESS_TOKEN` | A random token of at least 32 printable ASCII characters, without spaces |
| `CATLABEL_ALLOWED_ORIGINS` | Comma-separated, explicit application origins, for example `http://192.168.1.20:8000` |

A non-loopback bind fails at startup unless both a token and allowed origins are configured. Wildcards, credentials, paths, queries and fragments are rejected in origins. Put the application's accessible URL first: it is also the URL opened by the launcher for a LAN bind. Keep the token out of URLs and source control. An HTTPS reverse proxy is needed when the connection must be encrypted; the built-in HTTP listener does not encrypt the token or application traffic.

The home page presents a sign-in form. A successful sign-in sets an HttpOnly, SameSite=Strict session cookie; restarting CatLabel invalidates it. Allowed origins identify trusted browser frontends, not additional users. Foreign origins and untrusted Host headers are rejected before API handlers run.

For a separate local development frontend, explicitly add its origin, such as `http://localhost:5173`, to `CATLABEL_ALLOWED_ORIGINS`. The browser's origin includes its scheme and port. Keep the API application URL first when also enabling LAN access.

## API requests

Every `/api` request, including GET, requires `X-CatLabel-Client: 1`. The bundled frontend sends it automatically. A direct client must send it, too:

```sh
curl -H 'X-CatLabel-Client: 1' http://localhost:8000/api/health
```

If a token is configured, also send `Authorization: Bearer <token>`, or use the browser session cookie. All API methods are protected because some existing GET endpoints scan devices or initialize local data. API and sign-in responses use `Cache-Control: no-store`.

## Saved AI credentials

Provider configuration responses return `has_api_key`, never the saved key. A blank replacement field preserves the key. A nonempty replacement changes it; `clear_api_key: true` explicitly removes it. Supplying a replacement and a clear request together is rejected before changes are made.

Known provider and environment credentials are filtered from application errors, logs, histories and traces. Before a saved key is replaced, cleared or deleted, retained histories and traces are scrubbed within the same transaction. If scrubbing fails, the credential change rolls back. Redaction does not encrypt the SQLite database or protect it from another program running as the same OS user.

Startup performs the legacy provider migration once, atomically. Reading provider configuration no longer performs migration, and deleting a migrated provider does not resurrect it. The legacy row remains for recovery; routine maintenance does not delete recovery data.
