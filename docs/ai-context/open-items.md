# Open items

## Blocking promotion

1. Populate and independently verify source-backed USD/gold news confirmations
   for every candidate trading date. Do not fabricate broad clear intervals.
2. Rerun the frozen pipelines only after that source exists. Preserve config
   hashes and partition locks; do not tune rejected v1.0 or v1.1.
3. Obtain a successful read-only broker-property snapshot from
   `C:\Program Files\FBS MetaTrader 5\terminal64.exe` on `FBS-Demo` before any
   future shadow parity work.

## Strategy research

- Pullback v1.1 is rejected and must not proceed to shadow or demo.
- A future v1.2 is optional and must be a separately preregistered hypothesis,
  not an after-the-fact relaxation of v1.1.
- Validation (`2023-11-30` through `2025-03-24`) and test (`2025-03-25`
  through `2026-07-15`) remain untouched for pullback v1.1.

## Safety

- Keep configuration in shadow/read-only state.
- Do not enable demo execution, submit orders, or begin the ten-session shadow
  gate from a rejected or news-bypassed result.
