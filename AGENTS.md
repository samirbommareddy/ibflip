# Agent Notes

## Local environment and hosting policy

- See `docs/local-development.md` before running local or cloud commands.
- Keep all local credentials in the Git-ignored root `.env`. Use
  `./scripts/with-env <command> [arguments...]` to load it for project commands.
  Never print credential values, commit `.env`, or copy it under `static/`.
  `.env.example` must contain empty credential placeholders only.
- Do not create a user-wide `~/.modal.toml` or export project credentials from
  shell startup files. Renew Modal credentials by updating both values in `.env`.
- Develop and test locally on MSI. Use local development branches; do not push
  experiments or use the live game for routine testing. Publish finished,
  locally verified changes only when the user requests a release.
- Hosting must remain free: no paid plans, add-ons, automatic credit recharge,
  or infrastructure requiring payment. Authentication checks must not launch
  Modal training. Check available free credit before any cloud compute.

The following deployment and browser automation CLIs should be available in this repository environment:

- `render`: manage and inspect the Render FastAPI backend deployment.
- `npx wrangler`: deploy and inspect the Cloudflare Pages static frontend
  (project `ibflip`). Netlify is no longer used.
- `agent-browser`: run browser smoke tests against local or deployed pages.

When changing the web UI, verify the deployed or local app with `agent-browser` before reporting success.
