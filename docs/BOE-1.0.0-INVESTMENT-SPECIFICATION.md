# BOE-1.0.0 Investment Specification

**Status:** Frozen foundation specification

**Version:** BOE-1.0.0

**Approved scope:** Milestone 0 only

**Canonical machine-readable companion:** `contracts/boe-scorecard.v1.0.0.json`

## 1. Mandate and boundary

The Biotech Opportunity Engine (BOE) identifies U.S.-listed biotechnology equities with a credible, value-changing catalyst expected in approximately 1–12 weeks and ranks them by probability-adjusted upside/downside asymmetry.

BOE is a research and decision-support engine. It does not promise a 20% return, autonomously trade, size positions, or replace clinical, statistical, regulatory, or financial review. It must distinguish:

- **good science** — evidence and mechanism are credible;
- **good stock** — current price is below a conservative range of value;
- **good swing** — a dated catalyst and trade structure can plausibly close the expectation gap within the target window.

BOE is independent. BOE-1.0.0 must not modify or integrate with IEE v1.7.2 or SOE-1.0.0. Any future handoff requires separate approval.

## 2. Time and information discipline

Every analysis has an `as_of` timestamp. Only information publicly available at or before that timestamp may be used. Later amendments may correct provenance but may not silently rewrite a historical snapshot.

BOE uses three time concepts:

| Concept | Exact rule |
|---|---|
| Discovery horizon | Catalysts with earliest plausible date no more than 180 calendar days after `as_of` |
| Actionable BOE window | Event interval intersects days 7–84 after `as_of` |
| Too early | Earliest plausible date is more than 84 days away, or timing confidence is Low |

An event inside seven days may be analyzed, but it is not eligible for a new `HIGH_CONVICTION_CATALYST_SWING` because diligence and execution time are inadequate. It can be `CATALYST_SWING` only when all data are current within 24 hours and no gate is active.

## 3. Deterministic universe

### 3.1 Source population

Start with current Nasdaq, NYSE, and NYSE American common-equity listings. Map tickers to SEC CIKs and preserve source timestamps. ADRs are eligible if the security is U.S.-listed and the issuer provides sufficiently current English-language filings; otherwise mark `INSUFFICIENT_DATA`.

### 3.2 Security eligibility

An issuer enters the BOE research universe only if all are true:

1. The security is an operating-company common share or ADR, not an ETF, fund, warrant, right, preferred share, unit, closed-end fund, royalty trust, SPAC, shell, or OTC security.
2. The company is current in required periodic reporting or has an accepted foreign-issuer equivalent.
3. Its primary economic thesis is discovering, developing, manufacturing, licensing, or commercializing human therapeutics, biologics, vaccines, gene/cell therapies, gene editing, RNA therapeutics, or a drug-development platform.
4. At least one owned or economically material partnered therapeutic asset is active.
5. The issuer is not a mature diversified pharmaceutical company whose value is dominated by multiple established commercial franchises.

### 3.3 Deterministic business classification

The first pass uses SEC SIC and issuer descriptions. SIC 2834, 2835, and 2836 are candidates, not automatic inclusions. A rules-based filing review then applies:

- **Include:** more than 50% of disclosed pipeline/program value, R&D narrative, or management strategic emphasis relates to human therapeutics; or the lead economic asset is a therapeutic program.
- **Separate/non-rankable:** therapeutics exposure exists but is not the primary economic driver.
- **Exclude:** pure diagnostics, medical devices, CROs, healthcare services, distributors, animal-health-only businesses, nutraceuticals, cannabis, and research-tool companies.

Ambiguous classifications require a stored rationale and two independent supporting filing passages. Until resolved, the issuer is `WATCHLIST_UNIVERSE_REVIEW`, not ranked.

### 3.4 Investability floor

Universe membership and investability are separate. A candidate cannot receive an investable classification when any applies:

- last adjusted close below USD 1.00;
- 20-session median daily dollar volume below USD 2 million;
- current market capitalization below USD 50 million;
- fewer than 60 valid trading sessions of price history after a listing/reorganization;
- trading halt, bankruptcy process, or unresolved going-concern event that prevents bounded valuation.

The issuer remains auditable but is classified `REJECT` with a liquidity or continuity reason.

## 4. Catalyst definition and taxonomy

A catalyst must have a primary-source statement, a bounded time interval, an identified asset/indication, and a plausible mechanism for changing valuation by at least 20% in a success scenario. “Data this year,” routine conference attendance, ordinary earnings, or unsourced calendar entries do not qualify.

### 4.1 Taxonomy

| Code | Event | Examples | Default materiality ceiling (of 8) |
|---|---|---|---:|
| `CLIN_P1` | Phase I safety/PK/PD | SAD/MAD, dose escalation | 4 |
| `CLIN_P1_2` | Phase I/II or first efficacy signal | expansion cohort, proof of concept | 6 |
| `CLIN_P2` | Phase II efficacy | randomized or well-benchmarked readout | 7 |
| `CLIN_P2_3` | Phase II/III | registrational transition or pivotal readout | 8 |
| `CLIN_P3` | Phase III/pivotal efficacy | primary endpoint readout | 8 |
| `REG_SUBMIT` | NDA/BLA/sNDA filing acceptance | FDA validation/acceptance | 5 |
| `REG_ADCOM` | FDA advisory committee | vote and briefing materials | 8 |
| `REG_DECISION` | PDUFA/approval/CRL decision | approval, label, complete response | 8 |
| `REG_OTHER` | Material regulatory action | hold resolution, accelerated pathway decision | 7 |
| `CONF_DATA` | Major meeting data | new, decision-relevant dataset | 6 |
| `PUBLICATION` | Primary peer-reviewed data | practice/valuation-changing publication | 4 |
| `PARTNER` | Partnership/licensing event | only if specifically guided and bounded | 5 |
| `COMMERCIAL` | Material launch/coverage/label event | value-changing, not routine sales update | 5 |
| `FINANCING` | Financing or balance-sheet event | can be positive or negative; never alone investable | 3 |

The ceiling prevents weak event types from receiving full materiality absent an approved exception. An exception must be documented before outcome knowledge.

### 4.2 Timing confidence

| Confidence | Evidence |
|---|---|
| High | Exact regulator-set or conference date, or company-confirmed date/window of 14 days or less |
| Moderate | Company-confirmed quarter/month or interval of 15–45 days, corroborated by trial/regulatory status |
| Low | Uncorroborated estimate, interval over 45 days, stale guidance, or only “year/half-year” guidance |

Low-confidence catalysts are `TOO_EARLY` or `WATCHLIST`; they cannot be investable.

## 5. BOE score: exact 100 points

The score is a structured summary, not a probability. Missing inputs are never rescaled. The machine-readable contract is authoritative if a transcription conflict arises.

### 5.1 A — Catalyst Quality & Proximity (25)

| Subscore | Points | Rule |
|---|---:|---|
| Materiality | 0–8 | 0 none; 2 minor; 4 relevant but non-decisive; 6 can re-rate lead asset; 8 can change enterprise value by ≥40% |
| Timing confidence | 0–5 | 0 unverified; 2 Low; 4 Moderate; 5 High |
| Proximity | 0–4 | 0 >180d/unknown; 1 85–180d; 3 43–84d; 4 7–42d; 2 0–6d because entry diligence is compressed |
| Development/regulatory maturity | 0–5 | 1 preclinical/other; 2 P1; 3 P1/2 or filing acceptance; 4 P2 or material regulatory action; 5 P2/3, P3, AdCom, or decision |
| Novel information content | 0–3 | 0 routine/recycled; 1 incremental; 2 new decision-relevant evidence; 3 thesis-defining evidence |

### 5.2 B — Clinical/Scientific Quality (20)

| Subscore | Points | Rule |
|---|---:|---|
| Biological rationale/target validation | 0–3 | 0 contradicted; 1 plausible preclinical; 2 human/genetic/validated class support; 3 replicated human or approved-class validation with differentiation |
| Prior human evidence | 0–5 | 0 none/adverse; 1 safety/PD only; 2 early efficacy signal; 3 consistent efficacy with limitations; 4 randomized or replicated signal; 5 compelling, clinically meaningful replicated evidence |
| Trial design/endpoints | 0–5 | 0 not interpretable; 1 severe bias; 2 material limitations; 3 adequate; 4 strong; 5 pivotal-quality, clinically meaningful, appropriately powered design |
| Efficacy robustness | 0–3 | 0 absent/inconsistent; 1 fragile/subgroup; 2 coherent effect with uncertainty; 3 consistent magnitude, dose response/durability and statistical support |
| Safety/tolerability | 0–2 | 0 major unresolved signal; 1 monitorable/uncertain; 2 acceptable relative to disease and class |
| External validation/regulatory precedent | 0–2 | 0 absent/adverse; 1 partial; 2 strong independent replication, precedent, or regulator alignment |

Company-only data receive an evidence-quality flag and cannot earn 5/5 for prior human evidence or 3/3 for efficacy robustness without patient-level detail or adequate disclosed methods.

### 5.3 C — Market Impact & Expectation Gap (15)

| Subscore | Points | Rule |
|---|---:|---|
| Asset value concentration | 0–5 | 0 immaterial; 1 <10%; 2 10–24%; 3 25–49%; 4 50–74%; 5 ≥75% of conservative enterprise value |
| Success re-rating magnitude | 0–4 | 0 <10%; 1 10–19%; 2 20–39%; 3 40–74%; 4 ≥75% indicated success-case equity upside |
| Expectation gap | 0–4 | 0 success fully priced/indeterminable; 1 optimistic; 2 balanced; 3 underappreciated; 4 materially underpriced with at least two independent observable supports |
| Competitive/commercial position | 0–2 | 0 structurally weak; 1 viable; 2 differentiated with credible addressable economics |

Observable expectation supports include valuation versus comparable assets, disclosed consensus where legally/publicly available, options-implied move where available, pre-event price behavior, and specialist commentary. Social posts alone do not qualify.

### 5.4 D — Cash Runway & Dilution Risk (10)

Runway is unrestricted cash plus current marketable securities divided by normalized quarterly cash burn, multiplied by three. Normalized burn is the median of the latest four quarters of negative operating cash flow after removing specifically disclosed one-time financing, acquisition, or restructuring cash flows. If fewer than three comparable quarters exist, use the conservative higher of latest-quarter burn and available-quarter median and lower confidence.

| Subscore | Points | Rule |
|---|---:|---|
| Runway | 0–5 | 0 <12m; 1 12–17.9m; 3 18–23.9m; 4 24–29.9m; 5 ≥30m; 2 reserved for 18–23.9m with low-confidence burn |
| Financing overhang | 0–3 | 0 imminent/high dependence; 1 high; 2 moderate; 3 low |
| Balance-sheet flexibility | 0–2 | 0 net debt or restrictive obligations; 1 adequate; 2 net cash plus ≥18 months burn after the catalyst |

Runway must also be calculated at the latest plausible catalyst date. Shelf capacity alone is not a penalty; active ATM usage, offering history, covenant pressure, management guidance, and cash need determine the overhang.

### 5.5 E — Valuation Asymmetry / rNPV (10)

| Subscore | Points | Exact rule |
|---|---:|---|
| Conservative rNPV margin of safety | 0–4 | <−25%=0; −25% to <0%=1; 0% to <25%=2; 25% to <50%=3; ≥50%=4 |
| Base rNPV margin of safety | 0–3 | <0%=0; 0% to <25%=1; 25% to <75%=2; ≥75%=3 |
| Failure-value support | 0–3 | failure downside >70%=0; 51–70%=1; 31–50%=2; ≤30%=3 |

Margin of safety is `(scenario equity value / current fully diluted market value) - 1`. If value cannot be bounded, this factor scores zero and activates `UNBOUNDED_VALUATION`.

### 5.6 F — Technical Setup (10)

Use split-adjusted daily OHLCV as of the last complete session.

| Subscore | Points | Exact rule |
|---|---:|---|
| Trend | 0–2 | 2 if close > SMA20 > SMA50; 1 if close > SMA50 but full alignment absent; otherwise 0 |
| Relative strength | 0–2 | 20-session total return minus XBI ≥10pp =2; 0 to <10pp =1; <0pp =0 |
| Accumulation | 0–2 | 2 if 20d up/down dollar-volume ratio ≥1.5 and OBV slope positive; 1 if one condition; else 0 |
| Structure | 0–2 | 2 when close is 0–8% above validated support and ≥15% below base success target; 1 when 8–15% above support or 8–15% target room; else 0 |
| Extension | 0–2 | 2 if close is ≤8% above SMA20 and RSI14 is 45–70; 1 if ≤15% above SMA20 and RSI14 <75; else 0 |

Validated support is the higher of SMA20, SMA50, or a pivot tested on at least two separate sessions in the prior 60 sessions, provided it is below the current close.

### 5.7 G — Institutional & Insider Signal (5)

| Subscore | Points | Rule |
|---|---:|---|
| Specialist ownership signal | 0–3 | 0 net exit/no reliable data; 1 stable; 2 net accumulation by ≥2 versioned specialist funds; 3 meaningful accumulation by ≥3 specialists including ≥1 new/add ≥0.5% of shares |
| Insider signal | 0–2 | 0 material discretionary selling/no data; 1 neutral; 2 open-market purchase by officer/director ≥USD 50k within 180 days without offsetting discretionary sale |

Passive index changes, grants, option exercises without retained exposure, tax withholding, and 10b5-1 sales are not bullish evidence. Thirteen-F data are lagged and must carry the filing period and age.

### 5.8 H — Momentum & Sentiment (5)

| Subscore | Points | Rule |
|---|---:|---|
| Confirmed attention/volume | 0–2 | 2 if 5d median dollar volume ≥1.5× prior 60d median with attributable primary news; 1 if one condition; else 0 |
| Direction of expectations | 0–2 | 2 for at least two independent positive, thesis-relevant estimate/guidance/evidence revisions; 1 mixed/one; 0 negative or unsupported |
| Sector regime | 0–1 | 1 if XBI close > SMA50 and XBI 20d return is positive; else 0 |

Social-media enthusiasm is recorded only as a risk note and never adds points.

## 6. Probability of success (PoS)

PoS estimates the probability that the specific upcoming event produces a result the market would reasonably interpret as successful. It is not lifetime approval probability.

### 6.1 Base event probabilities

| Event | Base midpoint |
|---|---:|
| Phase I safety/PK/PD | 70% |
| Phase I/II efficacy | 45% |
| Phase II efficacy | 40% |
| Phase II/III efficacy | 50% |
| Phase III/pivotal efficacy | 55% |
| Filing acceptance (`REG_SUBMIT`) | 85% |
| Advisory committee favorable outcome | 60% |
| FDA regulatory approval decision | 75% |
| Material hold resolution/other regulatory | 50% |
| Conference/publication of previously undisclosed data | use underlying phase |
| Partnership/commercial/financing | no scientific PoS; event-specific probability capped at 50% unless contractually dated |

A company-guided future submission is not the `REG_SUBMIT` event for scoring and cannot be investable alone; the rankable regulatory event is official filing acceptance or another regulator-confirmed milestone.

These are conservative v1 priors for ranking, not claims of universal industry rates. They may be recalibrated only through an approved version change after the validation cohort is frozen.

### 6.2 Evidence adjustment

Start from the base midpoint and add:

- prior human evidence score: `(score - 2) × 4pp`;
- trial design score: `(score - 3) × 4pp`;
- efficacy robustness score: `(score - 1) × 4pp`;
- safety score: `(score - 1) × 3pp`;
- external validation score: `(score - 1) × 3pp`.

Apply a −10pp penalty for single-arm studies when a randomized comparator is reasonably required, −10pp for multiplicity/endpoint ambiguity, and −15pp for a material unresolved safety imbalance. Penalties stack. Clamp midpoint to 10–90%.

Uncertainty band:

- High evidence confidence: midpoint ±5pp;
- Moderate: midpoint ±10pp;
- Low: midpoint ±15pp.

Bounds are clamped to 5–95%. Company-only evidence cannot receive High confidence. Store the prior, each adjustment, penalties, final range, and rationale.

## 7. rNPV and Buffett-style valuation discipline

Buffett-style discipline here means price versus conservatively bounded value, survival, and margin of safety—not pretending a binary pre-revenue company has bond-like intrinsic value.

### 7.1 Asset cash-flow model

For each material asset and indication:

1. Forecast eligible patient population, diagnosis/treatment rate, peak penetration, net price, launch curve, exclusivity/erosion, royalties and milestones.
2. Calculate risk-unadjusted revenue and after-tax free cash flow after cost of goods, commercialization, maintenance R&D, milestones, and taxes.
3. Discount annual cash flows and remaining development costs to `as_of`.
4. Multiply post-development commercial cash flows by cumulative program PoS appropriate to current stage. Do not probability-adjust a cost already conditional on success twice.
5. Sum across indications while removing overlapping populations and shared costs.

### 7.2 Scenario assumptions

| Input | Conservative | Base | Bull |
|---|---|---|---|
| PoS | lower BOE PoS bound or lower externally validated stage prior | midpoint | upper bound, capped at 90% |
| Peak penetration | lower defensible comparable/epidemiology case | central evidence case | upper case with explicit capacity/competition support |
| Net price | lower observed analogue after gross-to-net | central analogue | upper analogue only with differentiation evidence |
| Launch curve | delayed/slow | central | faster but capacity-constrained |
| Discount rate | 18% | 15% | 12% |
| Terminal value | zero unless durable post-forecast economics are demonstrable | zero by default | permitted only with explicit patent/exclusivity support |
| Remaining development cost | high estimate | central | low estimate |

For partnered assets, value only the issuer’s economics. Platform optionality without a defined asset receives zero in the conservative case and a separately disclosed capped value in base/bull.

### 7.3 Equity bridge

`Equity value = sum(asset rNPV) + unrestricted cash + marketable securities - debt - financing obligations - corporate overhead PV - expected dilution cost + non-operating assets/liabilities.`

Use fully diluted shares: basic shares plus in-the-money options/warrants, RSUs, convertibles where dilutive, and a scenario estimate for financing required to reach the next value inflection. Report both total equity value and per-share value. Never hide expected financing inside an unexplained discount rate.

## 8. Catalyst expected-value framework

Inputs are success-return range, failure-return range, and PoS range. Returns are measured from current price to scenario price and include modeled dilution.

- `base_EV = p_mid × success_return_mid + (1 − p_mid) × failure_return_mid`
- `conservative_EV = p_low × success_return_low + (1 − p_low) × failure_return_worst`
- `reward_risk = success_return_mid / abs(failure_return_mid)`

If failure return is non-negative, cap reward/risk at 10 and flag the unusual assumption for review. If success upside is below 20%, the setup cannot be an investable BOE swing even if EV is positive.

## 9. Data completeness and missing data

Each scored subfactor carries `observed`, `derived`, `estimated`, or `missing`, plus source and timestamp. Missing points score zero and are not reweighted.

`coverage_pct = 100 × sum(maximum points of non-missing subfactors) / 100`.

Critical fields are ticker/CIK, security type, current price timestamp, share count, cash, debt, normalized burn, catalyst type, event interval, timing source, asset, indication, clinical phase, evidence cutoff, and failure value.

- Missing any critical field: `REJECT` with `INSUFFICIENT_CRITICAL_DATA`.
- Coverage below 80%: `REJECT`.
- Coverage 80–89%: at most `WATCHLIST`.
- Coverage ≥90%: eligible for an investable classification if all other rules pass.

Stale data rules:

- price/technical data: >1 completed trading session old is stale;
- SEC balance-sheet data: >140 days for domestic quarterly filer or superseded by a newer filing is stale;
- catalyst guidance: >120 days without corroboration is stale;
- ClinicalTrials.gov record: store both retrieved date and last update; staleness lowers confidence but company/FDA sources may supersede it;
- ownership: always disclose reporting lag; >2 reporting quarters old scores zero.

Conflicting data use the higher-priority source and preserve the conflict. No silent averaging.

## 10. Hard risk gates

Gates run after raw scoring and before classification. Raw score remains visible.

### 10.1 Disqualifying (`REJECT`)

- issuer is outside the universe or below investability floor;
- critical data missing or coverage <80%;
- unresolved clinical hold affecting the lead catalyst;
- major unexplained safety signal that makes success/failure valuation unbounded;
- materially misleading provenance, accounting uncertainty, bankruptcy, or inability to bound fully diluted shares;
- catalyst is not supported by a primary source or has no bounded interval;
- fatal trial interpretability defect: endpoint cannot answer the stated thesis, comparator is clearly inadequate, or announced analysis is not prospectively interpretable;
- conservative and base rNPV both cannot be bounded.

### 10.2 Financing risk (`FINANCING_RISK`)

Any one:

- runway at analysis date <12 months;
- cash is projected to run out within six months after the latest plausible catalyst date;
- management-guided or mathematically necessary financing is likely before the catalyst;
- active ATM/recent shelf plus runway <18 months and observed issuance dependence;
- modeled pre-catalyst dilution exceeds 15% of current fully diluted shares.

### 10.3 Binary risk — unfavorable asymmetry

Any one:

- base EV <10%;
- reward/risk <1.5;
- failure downside >70% while success upside <140%;
- success upside <20%;
- conservative EV <−20%;
- single-asset failure leaves less than 12 months cash and no credible second asset while failure downside exceeds 60%.

### 10.4 Overextended / do not chase

Any one:

- close >25% above SMA20;
- RSI14 ≥80;
- close is within 5% of base success target before the catalyst;
- price rose ≥40% over 10 sessions without new fundamental information sufficient to raise base value by at least 25%.

### 10.5 Too early

- earliest plausible catalyst date >84 days;
- timing confidence Low;
- required evidence is pending and cannot be sourced before ranking.

## 11. Deterministic classification

Apply in this precedence order:

1. `REJECT`
2. `FINANCING_RISK`
3. `BINARY_RISK_UNFAVORABLE_ASYMMETRY`
4. `OVEREXTENDED_DO_NOT_CHASE`
5. `TOO_EARLY`
6. `HIGH_CONVICTION_CATALYST_SWING`
7. `CATALYST_SWING`
8. `WATCHLIST`

### High conviction

All required:

- raw score ≥80;
- coverage ≥90%;
- catalyst ≥20/25, science ≥15/20, cash ≥7/10, valuation ≥7/10;
- timing High or Moderate and event in 7–84 days;
- base EV ≥20%, conservative EV ≥0%, reward/risk ≥2.0;
- success upside ≥30% and failure downside ≤55%;
- no gate.

### Catalyst swing

All required:

- raw score ≥70;
- coverage ≥90%;
- catalyst ≥17, science ≥12, cash ≥5, valuation ≥5;
- timing High or Moderate and event in 0–84 days;
- for events inside seven days, all critical data refreshed within 24 hours;
- base EV ≥10%, conservative EV ≥−10%, reward/risk ≥1.5;
- success upside ≥20%;
- no gate.

### Watchlist

Use when no higher-precedence label applies and either raw score is 60–69, coverage is 80–89%, entry is not yet attractive but a specific price would clear the valuation/technical test, or the thesis is credible but one non-critical uncertainty prevents investment classification.

Candidates below 60 without a disqualifying gate are `REJECT` for insufficient opportunity quality.

## 12. Entry and thesis controls

The preferred entry zone is the overlap of:

- price at or below base rNPV with at least 25% base margin of safety;
- price no more than 8% above validated support;
- price at least 15% below base success target;
- no extension gate.

The do-not-chase price is the lowest price that triggers any extension rule or reduces base EV below 10%. Targets are scenario values, not promises.

Every candidate must state:

- thesis in one falsifiable paragraph;
- what must happen;
- thesis breakers;
- scientific, financial, regulatory, and technical risks;
- source age and confidence;
- next mandatory refresh event.

## 13. Source hierarchy

1. FDA/regulator notices, labels, briefing documents, decisions, and official meeting materials.
2. SEC-filed statements and exhibits.
3. ClinicalTrials.gov registry records and results.
4. Peer-reviewed primary trial publications and official conference abstracts.
5. Issuer investor-relations releases/presentations not filed with the SEC.
6. Exchange data and documented market-data provider.
7. Reputable secondary analysis for context only.
8. Social/media posts for risk monitoring only, never evidence or score.

When sources at the same level conflict, use the later source if it explicitly supersedes the earlier one; otherwise lower confidence and retain both.

## 14. Known model limitations and conservative resolutions

| Risk of false precision | BOE-1.0.0 resolution |
|---|---|
| PoS varies by modality/indication | Event priors are broad, output ranges are mandatory, and validation recalibration requires a version change |
| rNPV is assumption-sensitive | Three scenarios, zero default terminal value, explicit dilution, and per-input provenance |
| Catalyst dates slip | Bounded intervals, timing-confidence score, freshness rules, and mandatory refresh |
| 13F data are lagged | Low 5-point weight, period disclosure, passive exclusion |
| Market expectations are not directly observable | Require two independent supports for maximum score |
| Company press releases can overstate evidence | Evidence cap and source-quality flag |
| Score can hide catastrophic risk | Gates override score and raw score remains visible |
| Technical indicators can dominate weak science | Technicals are only 10 points and cannot cure minimum science/catalyst thresholds |
| Post-hoc backtest tuning | Cohort and thresholds are frozen before outcomes are evaluated |

## 15. Change control

BOE-1.0.0 investment logic is frozen upon merge to `main`. Fixes that alter any point allocation, threshold, formula, gate, precedence, source ranking, or classification require:

1. documented issue and rationale;
2. before/after validation against the frozen cohort;
3. explicit owner approval;
4. semantic version change;
5. changelog entry and migration note.

Typographical corrections that do not change behavior may remain in 1.0.0 but must state that they are non-semantic.
