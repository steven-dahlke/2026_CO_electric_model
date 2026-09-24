# Named CO2 percent paths

`co2_path="statutory"` always reads `../co2_target.csv` (Script 26). Do not
edit that file for a case.

Any other `co2_path` name reads `{name}.csv` in this folder. Required columns:

- `year`
- `co2_reduction_pct_vs_2005`

Baseline tons stay Script 26's 42.023 MMT. The mass cap is
`42.023 * (1 - pct/100)`. Missing file is a hard error.

Add a CSV here when that case actually runs (for example `cap95.csv`). This
folder may otherwise be empty.
