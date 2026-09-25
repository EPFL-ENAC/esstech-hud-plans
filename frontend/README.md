# EssTech HUD Plans (esstech-hud-plans)

EssentialTech HUD Planning App

## Install the dependencies

```bash
yarn
# or
npm install
```

### Start the app in development mode (hot-code reloading, error reporting, etc.)

```bash
quasar dev
```

### Lint the files

```bash
yarn lint
# or
npm run lint
```

### Format the files

```bash
yarn format
# or
npm run format
```

### Build the app for production

```bash
quasar build
```

### Customize the configuration

See [Configuring quasar.config.js](https://v2.quasar.dev/quasar-cli-vite/quasar-config-js).

## Browser and installed app

Both builds use the same Vue app, hash routes, and backend. Installing is optional:
the deployed PWA works in an ordinary browser tab as well as a standalone window.

| Command             | Mode                   | Output / default URL    |
| ------------------- | ---------------------- | ----------------------- |
| `npm run dev`       | SPA, no service worker | `http://localhost:9000` |
| `npm run dev:pwa`   | PWA development        | `http://localhost:9001` |
| `npm run build`     | SPA production         | `dist/spa`              |
| `npm run build:pwa` | PWA production         | `dist/pwa`              |

Use the production build for offline/update acceptance testing. Development
service-worker behavior is not a substitute for production testing. Separate
development ports prevent the PWA worker from controlling the SPA origin.

The Login and More pages offer installation. Chromium can show a native prompt;
iOS uses Share → Add to Home Screen, and macOS Safari uses File → Add to Dock.
Browsers without installation support remain usable. An installed app may have a
different login session from the browser: sign in from the app itself.

### Offline and updates

After the service worker has installed and the page has been reopened/reloaded,
an offline launch shows a small, self-contained fallback page with a Retry button.
It honors `hud-language` (English, French, Spanish), falling back to the device
language. A first-ever offline visit cannot work because nothing is installed yet.

Only `offline.html` is precached. App assets use normal HTTP caching; `env.js`,
API/auth responses, maps, videos, and reconstruction files are not stored in
service-worker caches. Work requires a connection. Both SPA and PWA modes show a
connection-loss banner without unmounting the app or clearing forms. Recordings
and drafts still live in memory;
closing, reloading, or OS termination can lose them. There is no background upload
queue or offline authentication.

A new service worker waits until all windows controlled by its predecessor close.
There is no automatic page reload or forced worker activation during capture or
upload. Normal application code updates load on the next navigation/reload.

### Containers and HTTPS

From the repository root:

```sh
docker build -t hud-plans:pwa frontend
docker build --build-arg APP_MODE=spa -t hud-plans:spa frontend
```

The default Docker mode is PWA. Runtime configuration continues to be injected by
`entrypoint.sh`; provide the existing API and Keycloak environment variables.
Nginx revalidates HTML, the manifest, and service worker, never stores `env.js`, and
allows long-lived caching only for fingerprinted `/assets/` files.

Production and real-phone tests require HTTPS, including the API. Terminate TLS
at the existing ingress/reverse proxy. `localhost` works for desktop development;
a phone connecting to a laptop's plain HTTP LAN address does **not** receive that
exception. Use an HTTPS staging origin or a trusted local TLS proxy, and register
that origin's redirect URI with Keycloak. The app is deployed at the origin root.

Keep rollback images in PWA mode. For a strictly worker-free SPA deployment, use
a separate origin: switching an existing PWA origin to SPA files does not remove
workers from previously installed clients. For local debugging only, unregister
the worker and clear that origin's caches in browser developer tools.

The icons use the existing Material `camera_indoor` glyph and teal brand color.
`public/icons/app-icon.svg` is the editable source; the maskable PNG uses a smaller
glyph to keep it inside the mask's safe zone.

### Release checklist

An optional production browser smoke test uses an **existing** Playwright
installation and local Chrome; it adds no dependency to this project:

```sh
npm run build
npm run build:pwa
node tests/pwa.browser.mjs /absolute/path/to/playwright/index.mjs
```

It serves both builds on temporary loopback ports and checks the install UI,
manifest/icons, connection banner, offline locales and Retry, cache contents,
waiting-worker activation, and the worker-free SPA. Screenshots are saved in the
system temporary directory. It uses a temporary browser profile and does not
contact Keycloak or submit data. Run `npm test` for the dependency-free unit suite.

CI runs the Node tests, lint, and both production builds before deployment. On
the HTTPS staging deployment, verify these cases before promoting to production:

- Install and cold-launch on iPhone/iPad Safari, Android Chrome, desktop
  Chrome/Edge, and macOS Safari. Check ordinary browser use, including Firefox.
- Sign in from the installed app, return from Keycloak with valid OAuth state,
  sign out, and sign in again. Verify deep links and expired-session handling.
- Allow/deny camera permission; record, return to the form, upload, follow
  reconstruction progress, and view plans in both browser and standalone modes.
- Check portrait/landscape layouts, notches, home indicators, and drawer footers.
- After installation and reopening, disconnect and launch: the offline page
  appears; reconnect and Retry resumes the requested hash route. Test all locales.
- Disconnect during an open form/recording: the banner appears without clearing
  input. Request failures remain visible and mutations are not replayed.
- Deploy another PWA version during a recording/upload: no automatic reload or
  forced activation. Close **all** controlled tabs/windows and reopen; confirm
  the new worker activates. Cache Storage must contain only the offline page.
- Verify `/sw.js` and `/manifest.json` return real files with JavaScript/manifest
  MIME types and `no-cache`; `/env.js` returns `no-store`. Missing static files
  must return 404 rather than the app HTML.

Real-device permissions, installation, Keycloak redirects, and staging promotion
require release verification; emulation alone does not establish support.
