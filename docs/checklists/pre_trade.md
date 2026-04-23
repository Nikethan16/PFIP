# Pre-Trade Checklist

Template from plan **Appendix B**. Every new position — real or shadow — must have this
checklist attached to its journal entry (`POST /journal/entries`). If you can't answer any
item honestly, do not place the trade.

---

```
Pre-Trade Checklist — <asset>  <date>

 1. [ ] Thesis in one sentence: WHY will this trade be profitable, and over what horizon?

 2. [ ] Catalyst: what specific event or condition is expected to move the price?
        Date / earnings / macro release / on-chain event / technical break / other:
        ___________________________________________________________________

 3. [ ] Regime fit: what is the current regime for this asset (M3)?
        Does the thesis make sense in that regime? If not, justify the exception.

 4. [ ] Signal confluence: is the ML signal (M4) aligned? If misaligned, why are you
        overriding it?
        Signal direction: ____   Confidence: ____   Top 3 drivers: ____________________

 5. [ ] Position size (% of portfolio): ____%
        Below MAX_POSITION_PCT (default 10%)?                    [ ] yes  [ ] no
        Total exposure to this asset class after this add:       ____%

 6. [ ] Stop loss (price & % drawdown): ____________
        Basis (ATR-x, structural level, time-stop): _____________________________
        Invalidation: what event would tell you the thesis is wrong?

 7. [ ] Take-profit / scale-out plan: ____________
        Targets and quantities per leg:

 8. [ ] Tax impact: will this create STCG / LTCG / VDA 30% slab / foreign-asset
        obligation? See docs/TAX_REFERENCE.md.
        Estimated tax at exit (best case / base / worst):

 9. [ ] Counter-argument: what is the strongest case *against* this trade?
        Who would take the other side, and why?

10. [ ] Post-trade review trigger: when will you re-examine this position?
        Date: ____________  or condition: _______________________________________

Journal entry ID: ____________
Linked Signal ID (if any): ____________
```

---

Notes for use:

- The frontend journal form enforces all 10 items as required; no free-text submit
  without them.
- Shadow trades follow the exact same template — the discipline is what matters.
- Attach screenshots (chart, signal card, news highlight) to the journal entry for
  future post-mortem reference.
