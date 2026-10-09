# sorowatch-ai-agent

Standalone risk-scoring service for SoroWatch. Runs a real LangGraph
pipeline (gather_data -> score_risk -> decide_action) that pulls an
address's recent Stellar activity from Horizon and scores it with five
heuristics.

## Scoring heuristics (app/scoring.py)
Each heuristic is a pure function over a list of Horizon operations, so it
can be tested without a network. The five scores are added and the total is
clamped to 100 by `compute_risk_score`.

| Heuristic | Range | What it looks at | Low example | High example |
|---|---|---|---|---|
| Tx velocity | 0-40 | Operations per hour between the oldest and newest operation. 20 ops/hour or more scores the full 40. | 10 ops, one per day: **0** | 10 ops, 3 minutes apart (22 ops/hour): **40** |
| Counterparty diversity | 0-30 | Share of operations that go to or from the single most common counterparty, times 30. | 10 ops, 10 different counterparties: **3** | 8 of 10 ops with one address: **24** |
| Volume anomaly | 0-30 | Largest amount divided by the median amount. A ratio of 1 scores 0 and a ratio of 20 or more scores 30. | Five payments of 10: **0** | Payments of 10, 10, 10, 10 and 200: **30** |
| Account age | 0-20 | Age of the oldest operation we fetched. | Older than 30 days: **0** | Under 1 day: **20** (1-7 days: 10, 7-30 days: 5) |
| Round amounts | 0-10 | Share of payments that are a multiple of 100 (100 or more). Needs 3+ payments. Half or fewer round scores 0, all round scores 10. | Amounts 12.34, 87.5, 431.21: **0** | Amounts 100, 500, 1000, 2500: **10** |

Notes:
- Operations with no timestamp are skipped by velocity and age.
- Age is measured from the oldest operation fetched, so an old account with
  a long history can look slightly younger than it is. That errs towards a
  higher score, never a lower one.
- No operations at all scores 0 on every heuristic.
- `compute_risk_score(operations, now=...)` accepts a fixed `now`, which keeps
  age-based tests deterministic.

### Worked example
An address made 10 payments to the same counterparty, one every 10 minutes
(90 minutes in total). Nine were for 10 and one was for 500, and the first
operation was 5 hours ago.

| Heuristic | Score |
|---|---|
| Tx velocity (6.7 ops/hour) | 13 |
| Counterparty diversity (all to one address) | 30 |
| Volume anomaly (500 vs median 10) | 30 |
| Account age (5 hours old) | 20 |
| Round amounts (1 of 10 is round) | 0 |
| **Total** | **93** |

With the default threshold of 50 this address is flagged.

## Run
```
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Test
```
python -m pytest
```
Tests cover the scoring heuristics directly (pure functions, no network)
and the full pipeline with mocked Horizon responses (via respx), including
a high-risk case, a no-history case, and threshold sensitivity.

## API
`GET /health` returns `{"status": "ok"}`.

`POST /score` scores an address using its recent Horizon operations.

Request:
```json
{"address": "G...", "threshold": 50}
```

Response (the example above):
```json
{"address": "G...", "score": 93, "flagged": true, "operations_considered": 10}
```

`flagged` is `true` when `score >= threshold`. If Horizon keeps returning
429 after the retries, the service answers `503` with a `Retry-After: 30`
header.
