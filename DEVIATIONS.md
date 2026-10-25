# Deviations

Realism checks that fall outside their expected range, with the measured value, the range, and how each is handled. A check listed here keeps running with its original range.

| Check | Range | Measured | Since | Handling |
|---|---|---|---|---|
| Adjustment share of quantity moved (%) | 15.0 to 25.0 | 26.8 | before the demand signal update (archived reference, commit `91392ce`) | Pre-existing. `T2_ADJ_SHARE_OF_QTY` is not retuned. The check does not gate a run on its own, but a run that moves it more than 3 percentage points from 26.8 in either direction (below 23.8 or above 29.8) stops for review, because that would mean a change elsewhere is affecting the ledger. |
