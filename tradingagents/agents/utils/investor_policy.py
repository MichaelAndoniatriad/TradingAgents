"""User-defined portfolio mandate injected into agent prompts.

Edit INVESTOR_POLICY_FULL to change exit rules, growth framework, and checklist
for all agents that import it.
"""

# Shorter block for early-stage analysts (market/news/sentiment) so prompts stay focused.
INVESTOR_POLICY_ANALYST_SUPPLEMENT = """
## Desk mandate (context for your report)

Downstream agents apply: **5+ year** growth horizon; staged entry (**half** intended size, add over **2–4 weeks**); **≤5%** of portfolio per new position; **average up, not down**; pre-earnings trim if **≥+15%** before print (sell half, hold half through); at **2×** entry sell half; **thesis break** (2–3 predefined metrics) → full exit within **48 hours** when any metric breaks on earnings or material news; **−30%** from entry with thesis intact → one review at **next scheduled earnings**; **−40%** from entry → **full exit**, no exceptions.

Call out catalysts (earnings, guidance), drawdown vs a plausible entry, red-flag patterns (deteriorating growth, cash flow vs revenue, heavy dilution), and anything that would fail the desk's pre-buy checklist.
""".strip()

INVESTOR_POLICY_FULL = """
## Exit Policy (Standardized — applies to all eToro positions)

Three triggers. Any one fires, act immediately.

**Trigger 1: Pre-earnings trim**
If a position is 15% or more above entry going into an earnings event, sell half before the print. Hold the other half through earnings. This rule is binding and applies regardless of conviction level.

**Trigger 2: Thesis break**
Every position must have 2 to 3 defined thesis-break metrics written in the portfolio Notes column. If any one of those metrics breaks on an earnings print or material news event, exit the full position within 48 hours. No deliberating. Before adding analysis to any position, confirm thesis-break metrics are written down first.

**Trigger 3: Double from entry**
When a position reaches 2x the entry price, sell half and let the remainder run. Capital is recovered. The rest is house money. No rule required to exit the remainder unless Trigger 1 or 2 fires.

**Drawdown floor (applies to all positions)**
If a position falls 30% from entry and the thesis is unchanged, one review window is allowed (next scheduled earnings). If a position falls 40% from entry for any reason, exit in full regardless of thesis. No exceptions. This rule exists because averaging down into losers is the most repeated mistake in this portfolio.

---

# Stock Evaluation Framework — 10-Step Growth Process

## Step 1: Generate Ideas

Scan for companies encountered in daily life, industry trends, or emerging technologies. Use screeners (Finviz, TradingView, Yahoo Finance) filtered for: revenue growth >20% YoY, EPS growth >15% over 3 to 5 years, market cap >$1B, relative strength rating >80. Apply the Snap Test: if this company vanished overnight, would millions of people notice? If no, move on.

## Step 2: Confirm Market Leadership

Verify the company is top dog or clear first mover in its space. Confirm the industry has secular tailwinds (AI, electrification, cloud, ageing populations, fintech in emerging markets), not cyclical demand. Disqualify any company ranked third or fourth in a crowded market with no clear differentiation.

## Step 3: Evaluate the Competitive Moat

Identify which moat source applies: network effects, switching costs, intangible assets (patents, brands, licences), cost advantages, or efficient scale. Test pricing power: can the company raise prices 2 to 4% annually without losing customers? If not, moat is weak. Moat must be structural, not person-dependent.

## Step 4: Run the Numbers

Pull data from SEC filings, Yahoo Finance, or TIKR.

- Revenue: growing 20%+ YoY consistently over 3 to 5 years? Accelerating or decelerating?
- Earnings: EPS compounding 15%+ annually? Quarterly EPS up 25%+ vs same quarter last year?
- PEG ratio: below 1.0 ideal, below 1.5 acceptable, above 2.0 needs a compelling reason.
- Margins: gross margins above 50% (above 70% for SaaS)? Operating margins improving over time?
- ROIC: above 15%? Exceeding cost of capital? ROIC below WACC means growth destroys value.
- FCF: positive and growing? If negative, credible path to positive within 2 to 3 years?
- For SaaS/subscription: NRR above 110%, LTV:CAC above 3:1, Rule of 40 met.

## Step 5: Assess Management Quality

Research CEO and leadership. Is the company founder led? Does the CEO own meaningful personal stock? Does management communicate transparently in bad quarters? Is R&D above industry average? Check Glassdoor. Has there been unexplained C suite turnover (especially CFO)? Fisher's filter: any doubt on integrity, pass.

## Step 6: Size the Opportunity (TAM)

Top down: industry report total market narrowed to the actual served segment. Bottom up: price per customer multiplied by total potential customers worldwide. A company with 2% of a $500B TAM has massive runway. A company with 40% of a $10B TAM is approaching saturation. Bonus: does the company actively expand its TAM into adjacent markets?

## Step 7: Check Red Flags

Disqualify if: revenue growth decelerating 2+ consecutive quarters, cash flow declining while revenue rises, SBC exceeding 15% of revenue, share count increasing 5%+ annually, insider selling at unusual scale, NRR below 100% in subscription businesses, rising CAC quarter on quarter, accounting policy changes or auditor switches, loss of competitive position, or acquisitions outside core competency.

## Step 8: Value the Stock

Quick check: PEG below 1.5. Forward P/E vs own 5-year average and sector peers. Run a reverse DCF: what growth rate is the market implying for the next 10 years? If it requires 30%+ sustained growth and the company grows at 20%, the stock is priced for perfection. For pre-profit companies: EV/Revenue vs peers, and model earnings at industry average margins on current revenue.

## Step 9: Build the Position

Start with half the intended allocation. Add the other half over 2 to 4 weeks as the stock confirms the thesis. Never invest more than 5% of portfolio in a single new position. Average up, not down. Rising price after purchase confirms the thesis. Falling price means wait for clarity.

## Step 10: Hold and Monitor

Minimum holding period: 5 years. Review quarterly earnings but only act on fundamental changes, not price movements.

Hold through: market corrections, temporary earnings misses if thesis is intact, media panic.

Sell only when: thesis is broken (market share loss, structural revenue decline, management integrity failure), company is acquired for cash, significantly better opportunity exists and capital is needed, or concentration risk exceeds sleep number.

Never sell because: price dropped, price doubled, a TV pundit said to, to lock in gains, or the overall market is falling.

---

## Pre-Buy Checklist

Before buying any growth stock, confirm all of the following:

- Top dog or first mover in a growing industry
- At least one durable competitive moat source identified
- Revenue growth >20% YoY sustained over 3+ years
- Earnings growth >15% annually (or clear path to profitability)
- PEG ratio <1.5 (or reverse DCF shows reasonable implied growth)
- ROIC >15% and exceeding cost of capital
- Strong or improving margins
- Founder led or management with significant skin in the game
- TAM large enough to support 5 to 10x current revenue
- No red flags from the disqualifier scan
- You can explain the business and why it wins in two sentences

If all boxes cannot be checked, either do more research or move to the next idea.
""".strip()
