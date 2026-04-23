# PFIP Frontend

Next.js 14 (App Router) UI for the Personal Financial Intelligence Platform.

Stack: TypeScript, Tailwind CSS, shadcn/ui, Tremor, Recharts, TanStack Query,
NextAuth (credentials, single-user).

## Dev commands

```bash
# install deps (Node 20+, pnpm 9+)
pnpm install

# run the dev server on :3000
pnpm dev

# typecheck / lint / format
pnpm typecheck
pnpm lint
pnpm format

# production build
pnpm build
pnpm start
```

Set up `.env.local` first:

```bash
cp .env.local.example .env.local
# then edit NEXTAUTH_SECRET and confirm NEXT_PUBLIC_API_URL points to the
# FastAPI backend (default: http://localhost:8000/api/v1).
```

## Layout

- `app/` — App Router pages, one directory per top-level route.
- `components/` — UI primitives (`ui/`), layout (`nav/`), and feature modules
  (`charts/`, `portfolio/`, `agent/`, `journal/`, `morning-brief/`).
- `lib/contracts.ts` — Zod schemas + TS types mirroring
  `backend/pfip/core/contracts.py`.
- `lib/api.ts` — TanStack Query hooks. All backend calls go through here.
- `lib/auth.ts` — NextAuth config (credentials provider calling the backend).
- `lib/sse.ts` — SSE client used for streaming chat.

## Mobile-first

Every page was built against 390×844, 360×780, and 768×1024 viewports. Desktop
sidebar collapses to a bottom tab bar at `< md`. Tables re-render as stacked
cards at the same breakpoint.

## TODOs the user will want to tune

- Agent persona + morning-brief tone (backend prompts).
- Risk-limit defaults (`Settings` page; currently localStorage-only until the
  backend `/settings` endpoint is implemented).
- Correlation heatmap — placeholder on Portfolio page, needs backend endpoint.
