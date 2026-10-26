### Forward window, January to June 2026

| Replay | Fill | Stockout days | Jobs held | Rush lines | Rush spend | Avg inventory | Days of usage | Service backorders | Active-short item-weeks |
|---|---|---|---|---|---|---|---|---|---|
| Reference (current features and policy) | 97.9% | 2,550 | 57 | 267 | $94,725 | $3,352,299 | 145 | 1.88% | 3.7% |
| S1, static horizon | 98.0% | 2,478 | 57 | 238 | $86,643 | $3,455,867 | 150 | 2.08% | 3.7% |
| S1, pooled horizon | 97.7% | 2,657 | 51 | 239 | $85,557 | $3,451,244 | 150 | 2.61% | 3.9% |
| S6, pooled horizon | 98.0% | 2,616 | 50 | 235 | $84,543 | $3,577,164 | 155 | 2.08% | 3.9% |
| Rule on corrected masters (same in every replay) | 96.9% | 3,624 | 84 | 350 | $125,562 | $3,203,826 | 139 | | |

### Against the reference and the rule

| Replay | Stockout days vs ref | vs rule | Jobs held vs ref | Rush spend vs ref | Avg inventory vs ref | vs rule |
|---|---|---|---|---|---|---|
| S1, static horizon | -2.8% | -31.6% | +0 | -8.5% | +3.1% | +7.9% |
| S1, pooled horizon | +4.2% | -26.7% | -6 | -9.7% | +3.0% | +7.7% |
| S6, pooled horizon | +2.6% | -27.8% | -7 | -10.7% | +6.7% | +11.7% |

### Expectations (a miss is a finding; nothing is retuned)

| Replay | Model inventory vs Run 01 (within ±5%) | Forward service backorders (at most 1.5%) | Active-short item-weeks (at most 1.5%) |
|---|---|---|---|
| Reference (current features and policy) | +7.5% (MISS) | 1.88% (MISS) | 3.71% (MISS) |
| S1, static horizon | +10.8% (MISS) | 2.08% (MISS) | 3.69% (MISS) |
| S1, pooled horizon | +10.6% (MISS) | 2.61% (MISS) | 3.85% (MISS) |
| S6, pooled horizon | +14.7% (MISS) | 2.08% (MISS) | 3.90% (MISS) |

### Drift-supplier items (11 parts), forward window, S1 model

| Replay | Stockout days | Avg inventory |
|---|---|---|
| S1, static horizon | 213 | $21,274 |
| S1, pooled horizon | 226 | $17,731 |
| Reference | 217 | $22,019 |
| Rule | 226 | $22,139 |

| Part | Static: stockout days / avg inventory | Pooled: stockout days / avg inventory |
|---|---|---|
| ELE-00383 | 169 / $120 | 181 / $0 |
| ELE-00581 | 0 / $4,542 | 0 / $3,936 |
| ELE-00900 | 22 / $1,049 | 23 / $937 |
| MEC-00130 | 22 / $639 | 22 / $550 |
| MEC-00183 | 0 / $468 | 0 / $468 |
| MEC-00282 | 0 / $659 | 0 / $320 |
| MEC-00529 | 0 / $67 | 0 / $67 |
| MEC-00660 | 0 / $2,478 | 0 / $1,624 |
| MEC-00756 | 0 / $243 | 0 / $232 |
| MEC-00777 | 0 / $6,916 | 0 / $5,505 |
| MEC-01118 | 0 / $4,092 | 0 / $4,092 |
