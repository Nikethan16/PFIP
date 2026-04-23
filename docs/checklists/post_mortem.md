# Post-Mortem Checklist

Template from plan **Appendix C**. Every closed position — win, loss, or scratch — must
have this post-mortem attached to its journal close entry
(`POST /journal/entries/{id}/close`). No exceptions.

---

```
Post-Mortem — <asset>  opened <date>  closed <date>  P&L <amount>  (<pct>%)

 1. [ ] Outcome: [ ] win  [ ] loss  [ ] scratch
        Held for: ____ days. Horizon hypothesis was: ____ days. Deviation: ____%.

 2. [ ] Thesis review: did the trade work for the reason you expected?
        [ ] yes, as predicted
        [ ] yes, but for a different reason  (explain)
        [ ] no, stopped out on opposite move  (explain)
        [ ] no, time-stopped without catalyst  (explain)

 3. [ ] Execution grade:
        Entry timing:   [ ] excellent  [ ] ok  [ ] poor
        Stop discipline:[ ] held  [ ] moved once  [ ] moved repeatedly
        Exit timing:    [ ] planned  [ ] emotional early  [ ] emotional late
        Sizing:         [ ] correct  [ ] too large  [ ] too small

 4. [ ] Was the ML signal (M4) right or wrong for this one?
        If wrong, capture feature values at entry for later calibration review.

 5. [ ] Was the regime (M3) correctly labelled throughout? Any regime flips during hold?

 6. [ ] Lessons — what did you actually learn (not what you already knew)?
        Rule changes, if any: __________________________________________________

 7. [ ] Bias check: which behavioural bias, if any, influenced this trade?
        [ ] confirmation  [ ] loss aversion  [ ] anchoring  [ ] FOMO
        [ ] revenge  [ ] recency  [ ] overconfidence  [ ] other: _____________
        None?  [ ]

 8. [ ] Tax: realised STCG / LTCG / VDA-30% / foreign? Amount per bucket:
        (See docs/TAX_REFERENCE.md; posted to /tax/summary.)

 9. [ ] Would you take this trade again given the same pre-trade data?
        [ ] yes, same way  [ ] yes, but smaller/larger  [ ] no  (why)

10. [ ] Follow-up action items:
        - __________________________________________________________________
        - __________________________________________________________________
        Due date: ____________

Journal close entry ID: ____________
Linked open entry ID:   ____________
Shadow-portfolio copy on file? [ ] yes  [ ] no  [ ] n/a
```

---

Notes:

- The frontend close form enforces items 1, 2, 3, 6, 7, 9 as required; the rest are
  strongly recommended but free.
- Run `pfip.analytics.bias_drift` monthly against the last 30 closed entries to watch
  for repeated biases.
- Snapshot the signal card + features at entry before closing, so later recalibration
  has the exact values.
