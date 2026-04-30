# Agent Notes

The following deployment and browser automation CLIs should be available in this repository environment:

- `render`: manage and inspect the Render FastAPI backend deployment.
- `netlify`: manage and inspect the Netlify static frontend deployment.
  If a prompt misspells it as `netlfiy`, use the `netlify` CLI.
- `agent-browser`: run browser smoke tests against local or deployed pages.

When changing the web UI, verify the deployed or local app with `agent-browser` before reporting success.
