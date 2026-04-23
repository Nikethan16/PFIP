# Tax Reference — India Quick-Card

Condensed from plan **Appendix F**. Operational cheatsheet; **not** a substitute for your
CA. Rules apply to a Resident Indian individual (not NRI, not HUF, not company). Verify
every number against the live Finance Act / Budget for the financial year you're filing.
Assessment year (AY) = financial year (FY) + 1.

Last reviewed: 2026-04-21. **TODO(user): CA to re-verify at the start of each FY.**

---

## 1. Asset class matrix

| Asset class                          | Short-term holding | Short-term rate (STCG) | Long-term holding | Long-term rate (LTCG) |
| ------------------------------------ | ------------------ | ---------------------- | ----------------- | --------------------- |
| Listed Indian equity / equity MF     | < 12 months        | 20% (Sec 111A, post Jul 2024) | >= 12 months | 12.5% above Rs 1.25L exempt (Sec 112A) |
| Unlisted Indian equity               | < 24 months        | slab                   | >= 24 months      | 12.5% (no indexation, post Jul 2024) |
| Debt MF (units bought on/after 1 Apr 2023) | any              | slab (Sec 50AA)        | any               | slab (no LTCG benefit) |
| Debt MF (units bought before 1 Apr 2023)  | < 36 months       | slab                   | >= 36 months      | 12.5% (no indexation) |
| Listed bonds / G-Secs                | < 12 months        | slab                   | >= 12 months      | 12.5% (no indexation) |
| Sovereign Gold Bonds (SGB)           | n/a at maturity    | —                      | Held to maturity  | **Fully exempt**; early exit LTCG 12.5% |
| Gold / silver ETFs & MFs             | < 12 months        | slab                   | >= 12 months      | 12.5% (no indexation, post Jul 2024) |
| Physical gold                        | < 24 months        | slab                   | >= 24 months      | 12.5% (no indexation) |
| Real estate                          | < 24 months        | slab                   | >= 24 months      | 12.5% flat or 20% with indexation (grandfather option) |
| Foreign stocks / ETFs                | < 24 months        | slab                   | >= 24 months      | 12.5% (no indexation) |
| **VDA (crypto, NFTs)**               | any                | **30% flat**           | any               | **30% flat** (Sec 115BBH) |

Surcharge + 4% cess apply on top of every rate above.

---

## 2. Virtual Digital Assets (VDA) — Sec 115BBH

- Flat **30%** tax on *gains*, whether short- or long-term.
- **No loss set-off** — VDA losses cannot offset any income, not even other VDA gains
  across assets.
- **No deductions** except cost of acquisition.
- **1% TDS** on every sale above Rs 50,000 per year (Rs 10,000 for some categories)
  under Sec 194S; exchange usually deducts. Self-custody P2P: you deduct yourself.
- Airdrops / staking rewards / forks = ordinary income at FMV on receipt, then VDA rules
  apply at disposal.
- Wallet-to-wallet transfers (same owner) = not a taxable event.

---

## 3. Foreign assets — Schedule FA & Form 67

If you held **any** foreign asset at any point during the FY (calendar-year basis: 1 Jan –
31 Dec *of the FY's later calendar year*, per current ITR instructions — **CA to
reconfirm window**):

- Disclose in **Schedule FA** of the ITR: broker account IDs, country, peak balance,
  closing balance, income during the year. Missed disclosure = Rs 10L penalty per year
  (Black Money Act).
- Foreign dividends / interest taxed at slab rate in India.
- Claim **DTAA** relief for taxes withheld abroad via **Form 67**, filed **before** the
  ITR is filed. TRC (Tax Residency Certificate) from India may be needed by the foreign
  payer to avoid the higher non-treaty withholding rate.

PFIP surfaces: `/tax/schedule-fa?fy=YYYY-YY` and `/tax/form-67?fy=YYYY-YY`.

---

## 4. FX rate rules (for INR conversions)

- For purchase / sale of foreign shares, use **SBI TT buying rate** on the last day of the
  month **preceding** the transaction month (Rule 115 of Income Tax Rules).
- For DTAA / Form 67, use the TT buying rate on the date of the foreign tax payment.
- PFIP stores FX rates from the RBI reference rate feed and SBI TT (see `/fx` tables);
  calculator uses whichever rule the jurisdiction mandates.

---

## 5. Set-off & carry-forward cheatsheet

| Type of loss                 | Can set off against                                         | Carry forward years |
| ---------------------------- | ----------------------------------------------------------- | ------------------- |
| STCL (listed equity/MF)      | STCG, LTCG (any)                                            | 8                   |
| LTCL (listed equity/MF)      | LTCG only                                                   | 8                   |
| Speculative (intraday equity)| Speculative gains only                                      | 4                   |
| F&O (non-speculative biz)    | Any head except salary                                      | 8                   |
| VDA (crypto)                 | **Nothing — see Sec 115BBH**                                | not allowed         |
| Foreign stocks (LTCG)        | LTCG any                                                    | 8                   |

Filed ITR must be on or before the due date to preserve carry-forward.

---

## 6. Advance tax schedule (individuals)

If annual tax liability > Rs 10,000 you owe advance tax:

| Due date       | Cumulative %    |
| -------------- | --------------- |
| 15 June        | 15%             |
| 15 September   | 45%             |
| 15 December    | 75%             |
| 15 March       | 100%            |

Interest u/s 234C on shortfall; 234B if full tax not paid by year-end; 234A if return is
late.

PFIP nudges: `/tax/summary` panel shows running liability and the next advance-tax date
highlighted.

---

## 7. Forms you file

- **ITR-2** for most cases with capital gains, foreign assets, no business income.
- **ITR-3** if you treat F&O / intraday as business income.
- **Form 67** *before* ITR to claim foreign tax credit (DTAA).
- **Schedule FA** inside ITR for foreign assets.
- **Schedule VDA** inside ITR for crypto / NFTs.
- **Schedule CG** inside ITR for all capital gains detail.

---

## 8. What PFIP gives your CA

From `/tax/summary?fy=YYYY-YY` and `/tax/import/<broker>`:

- Consolidated STCG / LTCG per asset class (with Sec 111A / 112A / 112 / 115BBH bucketing).
- VDA ledger with cost basis, proceeds, 1% TDS matched to broker statements.
- Schedule FA ready-to-copy block per foreign broker.
- Form 67 draft with DTAA credits per country.
- XIRR summary across the whole portfolio.
- Advance-tax liability estimate at every quarterly due date.

Export: CSV + PDF. Both include a signed hash so your CA can verify the file hasn't been
edited post-export.

---

## 9. Living checklist for the operator

- [ ] Every sale recorded with cost basis, ISIN, trade date, broker contract note ref.
- [ ] 1% TDS for every VDA sale captured in `portfolio_tx.tax_withheld`.
- [ ] Foreign dividend + interest logged (ex-dividend date, FX rate of receipt).
- [ ] FX rates updated daily (RBI + SBI TT).
- [ ] Advance-tax reminder calendar on the 10th of Jun / Sep / Dec / Mar.
- [ ] CA handoff packet generated by 15 May (plenty of buffer before 31 Jul deadline).

---

**Disclaimer:** Tax law changes at every budget. Always verify with your CA and the
current Income Tax Act / Finance Act before filing. PFIP is a data aggregator, not a tax
opinion.
