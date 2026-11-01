# Agent Notes

The following deployment and browser automation CLIs should be available in this repository environment:

- `render`: manage and inspect the Render FastAPI backend deployment.
- `npx wrangler`: deploy and inspect the Cloudflare Pages static frontend
  (project `ibflip`). Netlify is no longer used.
- `agent-browser`: run browser smoke tests against local or deployed pages.

When changing the web UI, verify the deployed or local app with `agent-browser` before reporting success.
