# Kenya Flood-Risk Random Forest Model

## Model identity

- Release ID: `kenya_flood_risk_rf_v1_0_0`
- Version: `1.0.0`
- Algorithm: Random Forest classifier
- Output classes: Low, Medium and High
- Prediction unit: Kenyan county-day

## Training data

The evaluated model was trained using 149,022 real county-day
records and 7,697 controlled synthetic training records from
2010 to 2021. Synthetic records were excluded from validation
and testing.

## Predictor variables

1. Maximum precipitation
2. Mean temperature
3. Mean relative humidity
4. Mean soil wetness
5. Maximum soil wetness
6. Calendar-month sine component
7. Calendar-month cosine component

## Model configuration

- Trees: 300
- Maximum depth: 24
- Minimum samples per leaf: 1
- Features considered per split: square root
- Class weighting: balanced subsample
- Random state: 42

## Decision rule

A record is classified High when its predicted High probability
is at least 0.44. Otherwise, the class with the higher probability
between Low and Medium is selected.

The threshold was selected using the real 2022–2023 validation
period. It was not changed after the 2024–2025 test evaluation.

## Final test performance

- Accuracy: 0.777943
- Balanced accuracy: 0.740312
- Macro F1: 0.745040
- Weighted F1: 0.772937
- Macro one-vs-rest ROC-AUC: 0.918973
- High precision: 0.711671
- High recall: 0.576665
- High F1: 0.637094

The final test set contains 24,854 real county-day records from
2024 and 2025.

## Intended use

The model supports county-level flood-risk screening and dashboard
display. Its outputs can assist monitoring and prioritisation but
should not be treated as a replacement for official warnings,
field observations or emergency-management decisions.

## Limitations

The target labels are weakly supervised and partly derived from
environmental thresholds and EM-DAT event evidence. The reported
metrics therefore measure reproduction of the documented risk
framework rather than independent confirmation that a physical
flood occurred.

NASA POWER provided direct coverage for 34 counties. Controlled
synthetic training records were used for the remaining 13 counties.
DAHITI water level was used as supporting label evidence where
available, but it was not included as a model predictor because
consistent county-day coverage was unavailable.

The main remaining classification difficulty is separating Medium
from High. On the final test set, High recall was
0.576665.
