# Deep Research Eval

Lightweight LLM-as-judge eval framework for comparing deep research reports.
Inspired by the [DeepResearch Bench](https://deepresearch-bench.github.io/) RACE methodology.

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
```

## Directory Structure

```
reports/
  queries.json          # {"report_id": "original query", ...}
  tool_a/
    report_01.md
    report_02.md
    ...
  tool_b/
    report_01.md
    report_02.md
    ...
```

- Each tool gets its own subdirectory
- Report filenames must match keys in `queries.json`
- Reports can be `.md` or any text format (rename glob in `load_reports` if needed)

## Run

```bash
# Basic run
python eval.py

# Custom reports dir + save output
python eval.py --reports-dir ./my_reports --output results.json

# Suppress per-report logs
python eval.py --quiet
```

## Scoring

Each report is scored 1–10 on four dimensions, then combined into a weighted total:

| Dimension             | Weight | What it measures                              |
|-----------------------|--------|-----------------------------------------------|
| Comprehensiveness     | 30%    | Breadth — are all key aspects covered?        |
| Depth                 | 30%    | Analytical sophistication, not just facts     |
| Instruction Following | 20%    | Does it actually answer the query?            |
| Readability           | 20%    | Clarity, structure, presentation              |

**Weighted total = score out of 10**

## Sample Output

```
════════════════════════════════════════════════════════════
DEEP RESEARCH EVAL RESULTS
════════════════════════════════════════════════════════════

── Leaderboard ──────────────────────────────────────────
Tool                   N   Comp  Depth  InsFol   Read   TOTAL      ±
----------------------------------------------------------------------
tool_b                 3   8.33   8.67    8.00   8.33    8.38   0.24
tool_a                 3   5.67   5.33    6.00   5.67    5.63   0.47

── Per-report breakdown ─────────────────────────────────
  tool_b/report_01  total=8.90  [C=9 D=9 I=9 R=9]
    → Thorough, well-cited analysis with strong causal reasoning.
  tool_a/report_01  total=5.50  [C=6 D=5 I=6 R=5]
    → Covers main points but lacks analytical depth and specifics.
```
