# For Developers

Arctos lets other apps act on behalf of Arctos users without ever seeing
their passwords. This page explains how to register an app, how to let
people "Sign in with Arctos", and how to call Arctos with the resulting
tokens.

Arctos is an OAuth 2.0 authorization server. If you have used "Sign in
with Google" or GitHub OAuth apps before, this works the same way.

## Registering an app

Anyone with an Arctos account can register apps on the
[Your apps](/developers/apps) page. You'll choose:

- **Name** and optional **homepage**: shown to people on the consent
  screen when they sign in.
- **Redirect URIs**: where Arctos sends people back to after they sign in.
  Each must be one of:
  - an `https://` URL,
  - an `http://127.0.0.1/...` (or `http://[::1]/...`, `http://localhost/...`)
    loopback URL, for apps running on the user's own computer. Any port
    matches, so your app can listen on whichever port is free, or
  - a reverse-domain private-use scheme like `com.example.app:/callback`
    for mobile apps.
- **Type**:
  - **Public** apps run on the user's device (desktop, mobile, and
    single-page browser apps). They can't keep a secret, so they must use
    PKCE.
  - **Confidential** apps run on a server you control. They get a
    **client secret**, which is shown once when you create the app (or
    generate a new one). Arctos only stores a hash of it.

Every app gets a **client ID**, which is not secret.

## Sign in with Arctos

Arctos implements the
[authorization code flow](https://www.rfc-editor.org/rfc/rfc6749#section-4.1)
with [PKCE](https://www.rfc-editor.org/rfc/rfc7636). Native apps should
follow [RFC 8252](https://www.rfc-editor.org/rfc/rfc8252) (open the
system browser and listen on a loopback redirect URI). Most OAuth client
libraries handle all of this for you; the endpoints are:

| Endpoint | URL |
|----------|-----|
| Authorization | `https://<arctos host>/oauth/authorize` |
| Token | `https://<arctos host>/api/oauth/token` |
| Revocation | `https://<arctos host>/api/oauth/revoke` |
| User info | `https://<arctos host>/api/oauth/userinfo` |

### 1. Send the user to Arctos

Generate a random `code_verifier` (43 to 128 characters from
`A-Z a-z 0-9 - . _ ~`) and a random `state`, then open:

```
https://<arctos host>/oauth/authorize
    ?response_type=code
    &client_id=<client id>
    &redirect_uri=<one of your redirect URIs>
    &scope=<space-separated scopes, optional>
    &state=<state>
    &code_challenge=<BASE64URL(SHA256(code_verifier)), no padding>
    &code_challenge_method=S256
```

Only `S256` is accepted as the challenge method. PKCE is required for
public apps and recommended for confidential ones.

The user logs in if needed, then sees which app is asking and what it
will be able to do, and chooses **Allow** or **Cancel**.

### 2. Handle the redirect

Arctos redirects to your `redirect_uri` with either `?code=...&state=...`
or `?error=access_denied&state=...`. Check that `state` matches what you
sent.

### 3. Exchange the code for tokens

```
POST /api/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code=<code>
&redirect_uri=<the same redirect URI>
&client_id=<client id>
&code_verifier=<code_verifier>
```

Confidential apps also authenticate, with HTTP Basic auth
(`client_id:client_secret`) or `client_secret` in the form. The response
is:

```json
{
  "access_token": "...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "...",
  "scope": "..."
}
```

Codes expire after 5 minutes and work once.

### 4. Find out who signed in

```
GET /api/oauth/userinfo
Authorization: Bearer <access token>
```

returns `{"id": "<username>", "name": "<display name>", "type": "player" | "team"}`.
`id` is the stable identifier for the account.

## Tokens

- **Access tokens** last one hour. Send them as
  `Authorization: Bearer <access token>`.
- **Refresh tokens** get a new access token when the old one expires:

  ```
  POST /api/oauth/token

  grant_type=refresh_token&refresh_token=<refresh token>&client_id=<client id>
  ```

  Every refresh returns a **new refresh token**; store it and throw the old
  one away. Using an old refresh token again is treated as theft and
  signs the user out of your app entirely. Refresh tokens expire if unused
  for 90 days.
- An access token you hand to another service of yours (for example, a
  server doing work on the user's behalf) keeps working until it expires,
  even after you refresh, so you can give out short-lived access tokens
  without ever sharing the refresh token.
- **Revoke** tokens when the user signs out:

  ```
  POST /api/oauth/revoke

  token=<refresh or access token>&client_id=<client id>
  ```

Users can see every app they've signed in to in the **Connected apps**
section of their profile, and disconnect any of them, which revokes all
of that app's tokens.

### Tokens without a user

Confidential apps that only need public data can skip the user entirely
with the client credentials grant:

```
POST /api/oauth/token
Authorization: Basic <base64(client_id:client_secret)>

grant_type=client_credentials
```

This returns an access token (no refresh token) that can read public data
but can't request any scopes.

## Scopes

Reading public Arctos data needs no scope; every token can do it. Ask
only for the scopes you need:

| Scope | Lets the app |
|-------|--------------|
| `injuries` | Read all of the user's injury records, including private ones |
| `footage` | Upload match footage to tournaments the user organizes |

## Errors

Token and revocation errors follow
[RFC 6749 section 5.2](https://www.rfc-editor.org/rfc/rfc6749#section-5.2):
a `400` or `401` with `{"error": "...", "error_description": "..."}`.
Requests with a missing, expired, or revoked access token get `401`;
tokens without a needed scope get `403`.
