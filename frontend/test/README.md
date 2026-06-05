# Frontend test suite

Vitest tests for the PFIP frontend. **These were written but NOT executed**
(pnpm was offline when authored). To run them:

```bash
pnpm install   # pulls in @vitejs/plugin-react + existing vitest/jsdom/testing-library
pnpm test      # runs `vitest run` (see package.json "test" script)
```

## What's covered

- `utils.test.ts` — pure formatters in `lib/utils.ts`: `formatINR`
  (negatives/zero/null, en-IN lakh grouping, fraction digits), `formatPct`
  (signed prefix, no division by 100), `formatIST`/`formatISTDate` (UTC→IST
  +5:30 shift, invalid-date em-dash), `cn` (tailwind-merge conflict
  resolution), `confidenceTone` buckets.
- `contracts.test.ts` — Zod schemas in `lib/contracts.ts`: representative valid
  backend payloads PARSE and malformed ones are REJECTED (enum violations,
  range bounds, uuid/url validation, defaults applied).
- `url-normalization.test.ts` — pins the backend base-URL `/api/v1`
  normalization logic shared by `lib/api.ts` and `lib/auth.ts` (via a local
  mirror, since the helper isn't exported).
- `middleware.test.ts` — smoke test of the auth route-guard matcher regex
  (`/login`, `/api/auth`, `/_next`, and static files excluded; `/portfolio`
  guarded).

## Notes

- Config: `frontend/vitest.config.ts` (jsdom env, `@/` alias → project root to
  match tsconfig `paths`, `@testing-library/jest-dom` matchers via
  `test/setup.ts`).
- `lib/api.ts` is owned by another agent; tests only IMPORT exported schemas
  from `lib/contracts.ts` (where the schemas actually live) and never modify
  application code.
