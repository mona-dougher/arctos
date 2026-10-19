# Environment Variables

This is a list of all environment variables that can be used to
configure Arctos. For local development, copy `.env.example` to `.env`
and fill only the values you need.

`SECRET_KEY`
: Flask session signing secret. Format: any long random string. Generate
  one with `python -c "import os; print(os.urandom(32).hex())"`.

`ARCTOS_CORS_DEV`
: (default `0`) Set to `1` when the frontend and backend run on
  different local origins during development. Leave unset or `0` in
  production.

`ARCTOS_PORT`
: (default `5006`) Backend port when running `python run_app.py`.

`SQLALCHEMY_DATABASE_URI`
: SQLAlchemy database URI. Format: `sqlite:///tournament.db` for a local
  SQLite file, or any SQLAlchemy-supported database URI.

`SCRIPT_NAME`
: URL path prefix for subpath deployments. Format: leading slash, no
  trailing slash; e.g. `/arctos`.

`EXTERNAL_BASE_URL`
: Public URL where this Arctos instance is reachable. Format: absolute
  URL without a trailing slash; e.g. `https://arctos.example.org`.

`ARCTOS_LOG_LEVEL`
: (default `INFO`) Python logging level; e.g. `DEBUG`, `INFO`,
  `WARNING`, `ERROR`.

`MAX_CONTENT_LENGTH_BYTES`
: (default `104857600`) Max upload/request size in bytes.

`SILLY_USERS`
: Colon-separated account ids/usernames. These are the `Player.id` or
  `Team.id` slug values used to log in, not display names and not
  numeric database row ids; e.g. `alice:team-slug`.


## Scoreboard overlay rendering

The scoreboard overlay endpoint
(`GET /_api/tournaments/<url>/matches/<match_id>/scoreboard-overlay`)
renders the SPA's `/scoreboard-render` page in headless Chromium. See
[DEPLOY.md](DEPLOY.md#scoreboard-overlay-rendering) for server setup.

`ARCTOS_FRONTEND_URL`
: Origin serving the SPA, as reachable from the backend host. Format:
  absolute URL without a trailing slash; e.g. `https://arctos.example.org`
  in production (the same public origin), or `http://127.0.0.1:8080` in
  development. When unset the overlay endpoint returns 503.

`ARCTOS_CHROMIUM_PATH`
: Optional path to a system Chromium/Chrome executable; e.g.
  `/usr/bin/chromium`. When unset, Playwright's bundled Chromium is used
  (install it with `uv run playwright install chromium`).


## Google Oauth2 info

go to google cloud console for these

`GOOGLE_CLIENT_ID`
: OAuth client id from Google Cloud Console.

`GOOGLE_CLIENT_SECRET`
: OAuth client secret from Google Cloud Console.

Google OAuth callback URLs are derived from the incoming request host. If the
same server is reachable on multiple public domains, add each domain's
`/_api/auth/google/callback` URL to the authorized redirect URIs in Google
Cloud Console.


## Sign in with Arctos

Arctos's own OAuth provider (see [For Developers](developers.md)) refuses
requests that don't arrive over HTTPS. Production gets HTTPS from
gunicorn's TLS (`just run`) or from a proxy that forwards to it over
HTTPS. The reverse proxy must also forward `/api/` to gunicorn, like
`/_api/`.

`AUTHLIB_INSECURE_TRANSPORT`
: Set to `1` to allow the OAuth endpoints over plain HTTP, e.g. with
  `just dev`. Never set it in production.


## Youtube config

`YOUTUBE_UPLOAD_CLIENT_ID`
: Optional OAuth client id for upload. If unset, Arctos uses
  `GOOGLE_CLIENT_ID`.

`YOUTUBE_UPLOAD_CLIENT_SECRET`
: Optional OAuth client secret for upload. If unset, Arctos uses
  `GOOGLE_CLIENT_SECRET`.

`YOUTUBE_UPLOAD_REFRESH_TOKEN`
: OAuth refresh token for the upload account. Generate one with the
  Google OAuth playground or your preferred OAuth flow using the upload
  client id and secret.

`YOUTUBE_UPLOAD_PRIVACY_STATUS`
: (default `unlisted`) YouTube privacy status, usually `private`,
  `unlisted`, or `public`.

`YOUTUBE_UPLOAD_CATEGORY_ID`
: (default `22`) Numeric YouTube category id. The local example uses
  `17` for Sports.
