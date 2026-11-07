# Local development on MSI

Work in `/home/samir/projects/ibflip`. Keep credentials in this checkout's
`.env` only; it is ignored by Git and must never be copied under `static/`.
The committed `.env.example` contains empty placeholders. For a new checkout:

```bash
cp .env.example .env
chmod 600 .env
```

Edit `.env` locally in VS Code or T3 Code. It uses shell-compatible assignments:
quote credential values with single quotes. Do not paste credentials into chat,
commit them, print the file in agent logs, or enable shell tracing while loading it.

## Run commands with the project environment

```bash
uv sync --locked --group dev
./scripts/with-env uv run --locked uvicorn ibflip_web.main:app --host 127.0.0.1 --port 8000 --reload
```

Open `http://127.0.0.1:8000`. This backend serves both the API and frontend;
local gameplay does not require any cloud credentials. Stop it with Ctrl-C.
Do not substitute the production backend for a missing local server.

### Open the MSI server from another computer

In VS Code Remote SSH, forward port `8000` from the Ports panel. Alternatively,
run this on your own computer while connected to Tailscale:

```bash
ssh -N -L 8000:127.0.0.1:8000 samir@100.79.130.34
```

Keep that terminal open and visit `http://127.0.0.1:8000` on your computer.
If local port 8000 is occupied, use `-L 8080:127.0.0.1:8000` and visit port
8080 instead. The development server stays bound to MSI's loopback interface.

### Review Claude's design studies

The playable game uses `static/`. The Blue direction and motion lab are separate
mockups under `designs/`; they are not integrated into the playable UI yet.
Serve that directory alone in another MSI terminal:

```bash
.venv/bin/python -m http.server 8080 --bind 127.0.0.1 --directory designs
```

Forward port 8080 as well (`-L 8080:127.0.0.1:8080`) to review `/blue/` and
`/lab/`. Never serve the repository root: it contains the private `.env`.

The launcher loads `.env` for its command and children only. It does not change
your parent shell or automatically expose the credentials in other projects.
Run agent commands through this launcher instead of sourcing `.env` globally.
Processes running as the same Linux user can still deliberately read the file.
The application and CLI tools do not automatically load this file on their own.
The launcher clears inherited Modal authentication and disables the user-wide
Modal configuration before loading `.env`. Each invocation uses a fresh client;
changing both Modal values switches the account on the next command. Removing
them leaves Modal unauthenticated rather than falling back to another account.

## Credentials and read-only checks

- `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`: the account hosting the
  `ibflip` Cloudflare Pages project. Deployment needs Pages Edit; DNS changes
  additionally need the relevant zone permissions.
- `RENDER_API_KEY`: optional Render service administration. Not used by the game.
- `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`: a matched pair for the intended
  workspace. Replace both values when renewing or switching accounts. Confirm
  the workspace and expiry with the read-only token info command below.
- `IBFLIP_MODAL_CPU`: optional training container size, default 64. It does
  not limit spending. Do not start training to test credentials.
- `TRUSTED_PROXY_HOPS=0`: appropriate for direct local access; do not copy
  this setting to the Render environment, where the application defaults to 1.

Authentication checks that do not deploy or launch compute:

```bash
./scripts/with-env uv run --locked --with modal modal token info
./scripts/with-env npx wrangler whoami
```

The Modal command displays token metadata; do not share its raw output in logs
or chat without removing token identifiers. Local `.env` changes do not update
GitHub Actions secrets; the Pages workflow uses its separate repository secrets.
Never put deployment/admin keys into frontend JavaScript or public assets.

## Verification and releases

```bash
uv run --locked pytest -q
```

Develop and test locally. Keep hosting free: no paid plans, paid add-ons,
automatic credit recharge, or training beyond available free credit.
Push or publish only when the user requests a release. Pushes that change
`static/` can trigger Cloudflare preview deployments even on branches;
`main` can trigger production deployments. Use the browser against the local
app when changing the UI.
