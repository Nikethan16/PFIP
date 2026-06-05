FROM node:20-alpine AS base

# Enable pnpm via corepack
RUN corepack enable && corepack prepare pnpm@9.6.0 --activate

WORKDIR /app

# Install deps first (better caching).
# FIX 18: no `|| pnpm install` fallback — a stale lockfile must fail loudly
# rather than silently re-resolving and defeating lockfile pinning.
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile

# Copy the rest
COPY . .

EXPOSE 3000

ENV NEXT_TELEMETRY_DISABLED=1

# ---------------------------------------------------------------------------
# FIX 17c: PROD stage. Production build path — runs an optimized build, no dev
# server, no source bind-mount.
# Build & run with:
#   docker build --target prod -t pfip-frontend:prod ../frontend
#   # in compose, set the frontend service's build.target to `prod` and REMOVE the
#   # `- ../frontend:/app` bind-mount (and the node_modules/.next overlay mounts)
#   # so the baked production build is what actually runs.
# Defined BEFORE `dev` on purpose: with no build.target set, compose builds the
# LAST stage, so `dev` must stay last to keep the default behavior unchanged.
# ---------------------------------------------------------------------------
FROM base AS prod
RUN pnpm build
CMD ["pnpm", "start"]

# ---------------------------------------------------------------------------
# DEV stage (DEFAULT target — must remain the last stage). The compose file
# mounts the source read-write for hot reload. `pnpm dev` + the RW bind-mount
# are DEV-ONLY; use the `prod` target above for production.
# ---------------------------------------------------------------------------
FROM base AS dev
CMD ["pnpm", "dev"]
