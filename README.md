# IB-Flip

Pure Python IB-Flip game engine, PettingZoo wrapper, and lightweight human-vs-random-bots web UI.

## Backend

Run the FastAPI server locally:

```bash
uv run uvicorn ibflip_web.main:app --reload
```

API:

- `POST /start`
- `GET /state/{session_id}`
- `POST /play/{session_id}` with `{"action_id": 0}`

## Frontend

The static frontend lives in `static/`. Open `static/index.html` locally while the backend is running, or deploy it with Netlify.

## Tests

```bash
uv run pytest -q
```
