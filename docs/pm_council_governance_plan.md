# PM Council Governance Plan

This document addresses the current weaknesses in the portfolio PM / council design and proposes concrete fixes for each one.

The target architecture is:

- The council is a judge and dispatcher, not a creative analyst.
- The council answers from recorded evidence: portfolio state, prior decisions, completed research, memory, pending jobs, and explicit human instructions.
- If evidence is missing, stale, or contradictory, the council queues a new research layer instead of inventing an answer.
- The human controls real execution. The system recommends, schedules research, records decisions, and asks for approval where needed.

---

## 1. Muddy Boundaries Between PM, Research Manager, Trader, and Advisor Council

### Weakness

The project currently has several synthesis roles:

- graph-level Research Manager
- graph-level Trader
- graph-level Portfolio Manager
- advisor-level PM council
- planner / replan LLM

This creates overlapping authority. Multiple components can interpret the same research, produce stances, and recommend follow-up work. That makes it possible for the graph PM and advisor PM to disagree without a clear rule for which answer governs the portfolio.

### Solution

Define role ownership explicitly:

- **Analysts:** gather and summarize evidence.
- **Research layer:** produces ticker-level research findings only.
- **Graph PM:** produces a structured ticker decision from a completed deep run.
- **Advisor PM council:** reads portfolio state plus recorded ticker decisions and decides what to answer, escalate, or research next.
- **Planner:** schedules routine coverage only. It does not make portfolio judgments.
- **Human:** approves and executes real trades.

Implementation steps:

1. Rename concepts in docs and prompts so "Portfolio Manager" is not used for two different authorities.
2. Extend graph-level final output to a structured ticker decision:

   ```json
   {
     "ticker": "NVDA",
     "decision_id": "uuid",
     "rating": "hold",
     "confidence": 0.72,
     "thesis": "...",
     "thesis_break_metrics": ["..."],
     "next_review": "2026-05-29T09:00:00+00:00",
     "evidence_refs": ["event:...", "file:..."]
   }
   ```

3. Make the advisor PM consume those ticker decisions instead of re-reasoning from analyst prose.
4. Add a conflict rule: if advisor PM stance differs from the latest graph decision, it must cite the new evidence that changed the stance or queue follow-up research.

Acceptance test:

- Given a latest graph decision of `hold` and no newer evidence, the advisor PM cannot output `sell` unless it also queues research or cites a newer decision/event.

---

## 2. Too Much Authority Lives Only in Prompts

### Weakness

The PM is instructed not to invent facts, dates, rules, or research findings, but prompt instructions are not enforcement. A model can still produce unsupported claims, stale conclusions, or fabricated deadlines.

### Solution

Move key governance rules from prompt text into schema and validation code.

Implementation steps:

1. Add evidence references to council outputs:

   ```json
   {
     "claim": "NVDA thesis remains intact",
     "evidence_refs": ["event:single_model_analysis:...", "pm_cycle:..."]
   }
   ```

2. Require each non-unknown stance to include at least one evidence reference.
3. Add a validator after `AdvisorPMCycleResult`:

   - Reject or downgrade unsupported stances to `unknown`.
   - Remove invented dates not present in known catalysts, jobs, decisions, or caller notes.
   - Flag `push_note` if it contains urgency language without an overdue job, catalyst within 48h, or explicit human request.

4. Add a "known dates" object to the prompt and validate against it.
5. Store validation overrides in the event log so the council can learn what was corrected.

Acceptance test:

- If a PM output says "sell before May 30" and May 30 is not present in known dates or human instructions, validation removes or rejects that sentence and logs an override.

---

## 3. Council Context Is Curated Prompt Context, Not True Retrieval

### Weakness

The council currently receives selected context blocks: portfolio snapshot, pending jobs, memory, prior PM cycles, and recent event-log summaries. That is useful, but it is not the same as being able to retrieve the exact research file, event, or decision needed for the question.

This means the council may answer from whatever happened to fit in the prompt rather than the best available evidence.

### Solution

Build a lightweight evidence index and retrieval step before each council cycle.

Implementation steps:

1. Create an evidence index over:

   - event log rows
   - PM council JSONL rows
   - deep research markdown reports
   - single-model analysis outputs
   - pending jobs
   - portfolio snapshots
   - human instructions / PM memory

2. Each indexed item should include:

   ```json
   {
     "id": "event:...",
     "ticker": "NVDA",
     "kind": "single_model_analysis",
     "timestamp": "2026-05-15T09:00:00+00:00",
     "summary": "...",
     "path": "...",
     "decision": "hold",
     "staleness_days": 0
   }
   ```

3. Add a pre-PM retrieval function:

   - For a ticker-specific question, retrieve latest decision, latest full graph run, latest single-model run, pending jobs, relevant PM memory, and known catalysts.
   - For a portfolio-wide question, retrieve top exposures, changed stances, overdue jobs, unresolved decisions, and recent outcomes.

4. Pass retrieved evidence as a structured block, not raw file tails.
5. Keep raw files available as references, but make summaries the default.

Acceptance test:

- Given a question about NVDA and an older AAPL report with similar wording, retrieval returns NVDA evidence first and excludes unrelated AAPL context unless portfolio-wide exposure is relevant.

---

## 4. Planner and PM Can Both Shape Future Work

### Weakness

Both the planner and advisor PM can influence pending jobs. That is useful, but the governance is unclear:

- Planner builds routine coverage.
- PM can request replans.
- PM can append jobs.
- Human can ask for immediate work.

Without clearer rules, routine scheduling and council judgment can overwrite or duplicate each other.

### Solution

Separate routine scheduling from council-directed research.

Implementation rules:

- **Planner owns routine cadence.** It schedules normal monitoring, weekly summaries, and catalyst-based coverage.
- **PM owns exception handling.** It appends research when evidence is missing, stale, contradictory, or requested by the human.
- **PM may request a full replan** only when portfolio composition or priorities materially changed.
- **Human request overrides cadence.** If the human asks for research now, PM appends an immediate job.

Implementation steps:

1. Add a `source` field to jobs:

   ```json
   "source": "planner|pm_missing_evidence|pm_human_request|pm_conflict|manual"
   ```

2. Add a `supersedes_job_id` field when one job replaces another.
3. Before appending a PM job, deduplicate against pending jobs for the same ticker, job type, and evidence question.
4. Require `request_replan` to include `replan_reason_code`:

   - `portfolio_changed`
   - `schedule_conflict`
   - `coverage_gap`
   - `human_requested`
   - `other`

5. Make the UI / logs show why a job exists and who asked for it.

Acceptance test:

- If the planner already scheduled NVDA `thesis_check` tomorrow and the PM wants missing-evidence research today, the PM either accelerates that job or records why a separate job is needed. It should not silently duplicate it.

---

## 5. Candidate Discovery Is Less Mature Than Portfolio Monitoring

### Weakness

The system is strongest for monitoring existing holdings. It has portfolio scans, scheduled research, due jobs, outcome sync, and PM cycles.

It is less clear how it should discover new candidates, compare them to current holdings, and decide whether something deserves a full research layer.

### Solution

Treat candidate discovery as a separate "lookout" pipeline with explicit gates.

Implementation steps:

1. Define candidate sources:

   - monthly lookout list
   - watchlist
   - human-submitted tickers
   - earnings/catalyst screens
   - news anomaly screens
   - valuation or momentum screens

2. Add a candidate schema:

   ```json
   {
     "ticker": "ASML",
     "source": "monthly_lookout",
     "reason": "semicap exposure candidate",
     "evidence_refs": ["..."],
     "status": "candidate|watch|research_queued|rejected|promoted",
     "priority": 1
   }
   ```

3. Add promotion gates:

   - enough liquidity / tradability
   - clear thesis
   - identifiable catalyst or valuation dislocation
   - portfolio fit versus existing holdings
   - no obvious policy violation

4. Let the council compare candidates against current holdings instead of evaluating them in isolation.
5. Only queue full_graph research for candidates that pass a cheap first-pass screen.

Acceptance test:

- Given five candidates, the system should reject weak ones with explicit reasons, queue light research for uncertain ones, and promote only the strongest to deep research.

---

## 6. End-to-End Behavior Needs Scenario Tests

### Weakness

Unit tests cover many pieces, but the hardest requirement is behavioral:

- Does the council refuse to invent facts?
- Does it queue research when evidence is missing?
- Does it cite existing decisions when evidence exists?
- Does it avoid duplicate jobs?
- Does it preserve human authority?

Those are end-to-end properties, not just function-level properties.

### Solution

Add scenario tests around the council loop.

Recommended scenarios:

1. **Missing evidence**

   - Input: portfolio contains NVDA, no recent research exists.
   - Expected: stance is `unknown` or cautious; PM queues `append_jobs`; no fabricated thesis.

2. **Existing decision**

   - Input: latest event says NVDA `hold`, no newer evidence.
   - Expected: PM answer cites/uses the hold decision; no contradictory sell recommendation.

3. **Stale evidence**

   - Input: latest research is older than configured freshness threshold.
   - Expected: PM says evidence is stale and queues new research.

4. **Known catalyst**

   - Input: catalyst date is within 48h.
   - Expected: PM may push urgency, but must reference the catalyst.

5. **Invented catalyst**

   - Input: no catalyst date exists.
   - Expected: validation removes urgency/date claim.

6. **Duplicate job prevention**

   - Input: matching pending job already exists.
   - Expected: PM does not append a duplicate; it updates/accelerates or leaves existing job.

7. **Human immediate request**

   - Input: human asks "run NVDA sooner."
   - Expected: PM appends immediate research without waiting for routine planner cadence.

Implementation steps:

1. Build fixtures for portfolio rows, event logs, PM memory, and pending jobs.
2. Mock the LLM output so tests focus on validation and orchestration.
3. Add one test with a deliberately bad model output to prove validation catches it.
4. Add a small golden prompt test to ensure the council sees the latest completed research results.

Acceptance test:

- A full test file can simulate all seven scenarios without live LLM calls or network access.

---

## Recommended Build Order

1. Clarify role ownership and rename ambiguous PM concepts.
2. Add evidence references to PM output schemas.
3. Add post-PM validation for unsupported claims, invented dates, and urgency.
4. Add job source / dedupe governance.
5. Build the evidence index and retrieval block.
6. Add candidate discovery gates.
7. Add end-to-end scenario tests.

This order keeps the system useful while reducing the chance that the council becomes a confident improviser. The goal is not to make the council less capable. The goal is to make it capable in the right way: grounded, explicit about uncertainty, and quick to commission research when the current record is not enough.

---

## Implementation Status

Implemented in the current governance pass:

- Advisor PM defaults to GPT-5.5 and receives explicit evidence-discipline instructions.
- PM outputs now include evidence refs, replan reason codes, append-job source metadata, and candidate comparisons.
- PM validation downgrades unsupported action stances, removes unknown evidence refs, clears unsupported urgency, flags unknown dates, enforces stale-evidence refreshes, and enforces full-graph conflict rules.
- Evidence retrieval is now a first-class module indexing portfolio membership, pending jobs, event-log research, deep report files, known dates, stale tickers, and latest full-graph decisions.
- Full-graph decisions are emitted as structured ticker-level records with rating, confidence, summary, thesis, thesis-break metrics, and decision IDs.
- Planner, PM, candidate, and human-request jobs now carry source/evidence-question metadata and dedupe checks.
- Candidate discovery has explicit gates, audit logs, latest-state JSON, market-data enrichment, light-research transitions, full-graph promotion, PM comparison handoff, and lifecycle event-log entries.
- The graph-level PM has a clearer compatible alias, `create_single_name_decision_manager`, to separate ticker-level decisions from the advisor PM council.
- Scenario tests cover missing/stale evidence, existing decisions, full-graph conflicts, candidate gates, candidate conveyor transitions, candidate PM comparisons, and duplicate job prevention.

Residual work intentionally left for later:

- Replace remaining free-form analyst reports with structured analyst outputs and data-availability gates.
- Add stronger catalyst/earnings-date extraction into `known_dates`.
- Add a UI view for candidate state and PM validation overrides.
- Consider a graph node rename from "Portfolio Manager" to "Single-Name Decision Manager" once saved artifacts and external docs can be migrated safely.
