# Runbook — Cannot advance capital ladder tier

## Symptom

A request to advance from `PAPER` → `5%` (or any next tier) via
`pfip.portfolio.precommitment.can_advance_tier()` returns `False` with one
or more reasons in the response. The risk module then refuses to allow
real-capital orders at the new tier.

## What the gate enforces

From `pfip.portfolio.precommitment.LadderTier` and `can_advance_tier()`:

| Check | Why |
|---|---|
| 4+ weeks accumulated in current tier | Forces patience; prevents impulse upgrades after a hot streak |
| Zero risk-limit breaches in current tier | Position-cap, correlation-cap, drawdown-halt — any breach invalidates progression |
| Realized Sharpe ≥ tier floor (paper 0.5 / 5% 0.7 / 10% 0.9 / 25% 1.1) | Risk-adjusted return must be defensible |
| No consecutive losing months | Two red months → freeze; the system would rather be slow than blown up |
| Signed pre-commitment file on disk + hash matches | Stage 7 contract |

## Diagnostic

```powershell
# Get the current tier + reasons for the block:
docker exec pfip-backend python -c "
from pfip.portfolio.precommitment import current_tier_state, can_advance_tier
s = current_tier_state()
print('current_tier=', s.tier, 'days_in_tier=', s.days_in_tier)
ok, reasons = can_advance_tier(s)
print('can_advance=', ok, 'reasons=', reasons)
"
```

## How to unblock — legitimately

There is no override; that's the point. Acceptable paths:

1. **Wait** until the time-in-tier requirement is met.
2. **Reset breach counter** only if the breach has been fully analysed and
   post-mortemed (`journal/post_mortems/<date>_<tag>.md` exists). The
   counter is in Redis: `ladder:breaches:<tier>`. Resetting without a
   post-mortem violates the pre-commitment contract.
3. **Drop a tier** — `LadderTier` is allowed to step backward without
   ceremony. If recent performance is poor, the right move is down.

## How NOT to unblock

Do not edit `pfip.portfolio.precommitment` constants to lower the floors
without first signing a new pre-commitment file documenting the change
and the reason. The whole module exists to make this hard.

## Related

- `backend/pfip/portfolio/precommitment.py`
- `WHY_AND_WHAT.md` §7 — Pre-commitment & capital ladder
