# Refactor Plan (Netlify + Supabase, 100% Free Tier)

## Goals
- Netlify-ready static deployment.
- Improved UI/graphics.
- Simple login (name + session ID).
- Create/join party flow.
- Free-tier backend for sessions and party state.

## Proposed Architecture
- **Frontend:** Vite + React (static build output for Netlify).
- **Backend:** Supabase (free tier) for parties, players, and session state.
- **Realtime (optional but recommended):** Supabase Realtime for lobby updates.

## Work Phases

### 1) Scaffold modern front-end (Netlify-ready build)
:::task-stub{title="Scaffold modern front-end (Vite + React) with Netlify-ready build"}
1. Create a `/web` (or `/client`) directory and scaffold with Vite + React.
2. Set build output to `dist/` and confirm `npm run build` works locally.
3. Add `netlify.toml` with build command and publish directory.
4. Verify SPA routing works with Netlify (add `_redirects` to route all to `index.html`).
:::

### 2) UI foundation (layout + reusable components)
:::task-stub{title="Add UI foundation (global styles, layout, reusable components)"}
1. Add a styling approach (Tailwind or CSS modules + variables).
2. Create basic layout components (PageShell, Card, Button, Input).
3. Define primary theme (colors, fonts, background gradient).
4. Add responsive layout support for mobile/desktop.
:::

### 3) Login screen (name + session ID)
:::task-stub{title="Build login screen (name + session ID) and local session storage"}
1. Add a login route (`/login`) with inputs: `displayName`, `sessionId`.
2. Validate inputs (min length, allowed characters).
3. Store values in localStorage and global app state.
4. Redirect to lobby after submit.
:::

### 4) Party/lobby flow (create/join + roster)
:::task-stub{title="Create party/join party lobby flow"}
1. Build `/lobby` screen with “Create Party” and “Join Party” actions.
2. On create, generate a short code or request from backend.
3. On join, validate code and load party state.
4. Show players list, host indicator, and “Start Game” button.
:::

### 5) Supabase backend (free tier)
:::task-stub{title="Add Supabase backend for parties, players, and session state"}
1. Create Supabase project (free tier) and obtain URL + anon key.
2. Add tables: `parties`, `players`, `sessions` (or similar).
3. Add basic row-level security rules (allow join by party code).
4. Implement API helpers in front-end for CRUD operations.
:::

### 6) Wire UI to backend state
:::task-stub{title="Connect lobby and login to Supabase state"}
1. On login, insert/update player record in Supabase.
2. On create party, insert a party row and link creator as host.
3. On join party, insert player into party and subscribe to party roster.
4. Sync lobby display to real-time Supabase updates.
:::

### 7) Refactor game logic into a clean module
:::task-stub{title="Extract game logic into isolated module"}
1. Identify legacy game logic functions/objects.
2. Move logic into `/game` module with clean API.
3. Update UI to use the module via hooks or controller functions.
4. Add simple unit tests for core game rules (optional).
:::

### 8) Visual polish (graphics + animations)
:::task-stub{title="Add graphic polish (backgrounds, icons, animations)"}
1. Add a subtle animated background or gradient.
2. Add icons for party, user, and status indicators.
3. Add button hover/press animations.
4. Improve typography, spacing, and UI readability.
:::

### 9) Deployment + documentation
:::task-stub{title="Finalize Netlify deployment + documentation"}
1. Add `README` instructions: install, run, build, deploy.
2. Document Supabase setup and required environment variables.
3. Confirm `npm run build` works and Netlify deploy succeeds.
4. Optional: add a `setup` script to initialize local env.
:::
