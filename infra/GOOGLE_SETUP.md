# Google sign-in setup — owner console step

Current setup status: the owner supplied the public Web client ID and Render
API is deployed. Do not create duplicate credentials. Confirm the existing
client has the exact staging JavaScript origin below. Staging gateway deploy
and secure proxy-secret transfer steps are in apps/README.md; real sign-in
acceptance is still pending. Older preparation notes follow.

The API, Cloudflare gateway and sign-in preview are prepared in the development
draft. No OAuth client, hosted service or staging deployment has been created.
The Google Cloud console was unavailable in this session's browser, so complete
this account-side setup in your own browser.

## Planned staging origin

```text
https://pocket-analytics-staging.ezrealrose831.workers.dev
```

This is the planned hostname for the separate `pocket-analytics-staging` Worker
in the existing Cloudflare account. It has not been published and is not an
existing preview link. Its public and preview URLs remain disabled. Registering
this origin in Google does not deploy it. If the staging hostname changes,
update both the Google origin registration and server configuration together.

## Console steps

1. Open https://console.cloud.google.com/auth/clients with the chosen owner
   Google account. Create or select an owner-controlled Pocket Analytics project.
2. If prompted to set up Google Auth Platform, use **Pocket Analytics** as the
   application name and the owner's account for support/contact details. Use an
   external testing audience for a personal Google account and add the owner
   as a test user when that configuration requires it.
3. Create an OAuth client with application type **Web application**, named
   **Pocket Analytics staging**.
4. Under **Authorized JavaScript origins**, add the exact planned staging
   origin above, with no path. This implementation uses a JavaScript callback;
   it does not require an authorized redirect URI.
5. Save and copy the public **Client ID**, ending in
   `.apps.googleusercontent.com`. Share only that ID for configuration, not the
   downloaded credentials JSON or a client secret.

## Configuration after the client exists

The API will receive the public ID as `GOOGLE_CLIENT_ID`, the planned app origin
as `APP_ORIGIN`, and the chosen owner account as private server configuration.
The gateway uses that same app origin, the eventual staging API origin and the
matching server-only proxy secret. The browser gets the public client ID through
`GET /api/auth/challenge`; it never receives the proxy secret.

An actual Google popup/FedCM and cookie round-trip acceptance test comes after
staging deployment is explicitly authorized. Source configuration and OAuth
registration can be prepared first without deploying the full app.

Official instructions:
https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid
