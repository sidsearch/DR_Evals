"""
Custom-dimension Deep Research Eval
Evaluate reports on any set of criteria defined in a JSON config file.

Usage:
    python eval_custom.py --dimensions dimensions/factual_rigor.json
    python eval_custom.py --dimensions dimensions/citation_quality.json --output results.json

Dimension config format (see dimensions/ for examples):
    {
      "name": "Human-readable label for this rubric",
      "description": "Optional explanation of what this rubric tests",
      "dimensions": {
        "dimension_key": {
          "weight": 0.40,
          "description": "What the judge should assess for this dimension"
        },
        ...
      }
    }

Weights must sum to 1.0. Scores are 1–10 per dimension; weighted total is out of 10.
"""

import boto3
import json
import os
import re
import argparse
from pathlib import Path
from dataclasses import dataclass, asdict


# ── Bedrock defaults (same as eval.py) ──────────────────────────────────────

JUDGE_MODEL = os.environ.get(
    "BEDROCK_MODEL",
    "us.anthropic.claude-opus-4-5-20251101-v1:0",
)

JUDGE_PROMPT_TEMPLATE = """\
You are an expert research evaluator. Score the following research report on the dimensions listed below.

## Original Query
{query}

## Report
{report}

## Scoring Instructions
Score each dimension from 1–10 (integers only):
- 1–3: Poor
- 4–6: Adequate
- 7–9: Good
- 10: Exceptional

## Dimensions to Score
{dimensions_block}

Respond ONLY with a JSON object in this exact format (one key per dimension, plus rationale):
{json_template}
"""


# ── Dimension config loader ──────────────────────────────────────────────────

def load_dimensions(path: Path) -> dict:
    with open(path) as f:
        config = json.load(f)

    dims = config.get("dimensions")
    if not dims:
        raise ValueError(f"No 'dimensions' key found in {path}")

    total_weight = sum(d["weight"] for d in dims.values())
    if abs(total_weight - 1.0) > 0.01:
        raise ValueError(
            f"Dimension weights must sum to 1.0, got {total_weight:.3f} in {path}"
        )

    return config


# ── Prompt builder ───────────────────────────────────────────────────────────

def build_prompt(query: str, report: str, dimensions: dict) -> str:
    dims_lines = "\n".join(
        f"- **{key}** ({int(meta['weight']*100)}% weight): {meta['description']}"
        for key, meta in dimensions.items()
    )

    json_keys = "\n  ".join(f'"{k}": <int>,' for k in dimensions)
    json_template = "{\n  " + json_keys + '\n  "rationale": "<1-2 sentence summary of overall quality>"\n}'

    return JUDGE_PROMPT_TEMPLATE.format(
        query=query,
        report=report,
        dimensions_block=dims_lines,
        json_template=json_template,
    )


# ── Bedrock call ─────────────────────────────────────────────────────────────

def judge_report(client, query: str, report: str, dimensions: dict) -> tuple[dict, str]:
    prompt = build_prompt(query, report, dimensions)

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "messages": [{"role": "user", "content": prompt}],
    })

    response = client.invoke_model(modelId=JUDGE_MODEL, body=body)
    result = json.loads(response["body"].read())
    raw = result["content"][0]["text"].strip()

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"Could not parse JSON from judge response:\n{raw}")

    parsed = json.loads(match.group())
    return parsed, raw


def weighted_total(scores: dict, dimensions: dict) -> float:
    return sum(
        scores[dim] * dimensions[dim]["weight"]
        for dim in dimensions
        if dim in scores
    )


# ── Loader (shared structure with eval.py) ───────────────────────────────────

def load_reports(reports_dir: Path) -> tuple[dict, dict]:
    queries_path = reports_dir / "queries.json"
    if not queries_path.exists():
        raise FileNotFoundError(
            f"queries.json not found in {reports_dir}. "
            "Create it with {report_id: query} mappings."
        )

    with open(queries_path) as f:
        queries = json.load(f)

    tools_reports = {}
    for tool_dir in sorted(reports_dir.iterdir()):
        if not tool_dir.is_dir():
            continue
        reports = {}
        for report_file in sorted(tool_dir.glob("*.md")):
            reports[report_file.stem] = report_file.read_text()
        if reports:
            tools_reports[tool_dir.name] = reports

    return tools_reports, queries


# ── Eval runner ──────────────────────────────────────────────────────────────

def run_eval(
    reports_dir: Path,
    dimensions: dict,
    region: str = "us-east-1",
    profile: str = None,
    verbose: bool = True,
) -> dict:
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    client = session.client("bedrock-runtime", region_name=region)
    tools_reports, queries = load_reports(reports_dir)

    all_scores = []

    for tool, reports in tools_reports.items():
        for report_id, report_text in reports.items():
            query = queries.get(report_id, "")
            if not query:
                print(f"  [warn] No query found for {report_id}, skipping.")
                continue

            if verbose:
                print(f"  Judging {tool}/{report_id} ...", end=" ", flush=True)

            try:
                scores, raw = judge_report(client, query, report_text, dimensions)
            except Exception as e:
                print(f"ERROR: {e}")
                continue

            wt = round(weighted_total(scores, dimensions), 3)

            entry = {
                "tool": tool,
                "report_id": report_id,
                "query": query,
                "weighted_total": wt,
                "rationale": scores.get("rationale", ""),
                "raw_response": raw,
            }
            for dim in dimensions:
                entry[dim] = scores.get(dim)

            all_scores.append(entry)

            if verbose:
                print(f"score={wt:.2f}")

    return summarize(all_scores, dimensions)


# ── Summary ──────────────────────────────────────────────────────────────────

def _mean(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else 0.0


def _std(vals):
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return 0.0
    m = sum(vals) / len(vals)
    return round((sum((x - m) ** 2 for x in vals) / len(vals)) ** 0.5, 3)


def summarize(scores: list[dict], dimensions: dict) -> dict:
    by_tool: dict[str, list[dict]] = {}
    for s in scores:
        by_tool.setdefault(s["tool"], []).append(s)

    summaries = []
    for tool, tool_scores in by_tool.items():
        summary = {
            "tool": tool,
            "n": len(tool_scores),
            "mean_weighted_total": _mean([s["weighted_total"] for s in tool_scores]),
            "std_weighted_total": _std([s["weighted_total"] for s in tool_scores]),
        }
        for dim in dimensions:
            summary[f"mean_{dim}"] = _mean([s.get(dim) for s in tool_scores])
        summaries.append(summary)

    summaries.sort(key=lambda x: x["mean_weighted_total"], reverse=True)

    return {
        "rubric": None,  # filled in by caller
        "summaries": summaries,
        "per_report": scores,
        "dimension_weights": {k: v["weight"] for k, v in dimensions.items()},
    }


# ── Reporting ────────────────────────────────────────────────────────────────

def print_results(results: dict, dimensions: dict):
    rubric = results.get("rubric") or "Custom"
    print("\n" + "=" * 60)
    print(f"DEEP RESEARCH EVAL — {rubric.upper()}")
    print("=" * 60)
    print(f"\nWeights: " + ", ".join(
        f"{k}={v['weight']:.0%}" for k, v in dimensions.items()
    ))

    dim_keys = list(dimensions.keys())
    # Leaderboard header
    print("\n── Leaderboard ──────────────────────────────────────────")
    dim_header = "  ".join(f"{k[:6]:>6}" for k in dim_keys)
    header = f"{'Tool':<20} {'N':>3}  {dim_header}  {'TOTAL':>6}  {'±':>5}"
    print(header)
    print("-" * len(header))

    for s in results["summaries"]:
        dim_vals = "  ".join(f"{s.get(f'mean_{k}', 0):>6.2f}" for k in dim_keys)
        print(
            f"{s['tool']:<20} {s['n']:>3}  {dim_vals}  "
            f"{s['mean_weighted_total']:>6.2f}  {s['std_weighted_total']:>5.2f}"
        )

    print("\n── Per-report breakdown ─────────────────────────────────")
    for s in results["per_report"]:
        dim_scores = " ".join(f"{k[:2].upper()}={s.get(k)}" for k in dim_keys)
        print(f"  {s['tool']}/{s['report_id']}  total={s['weighted_total']:.2f}  [{dim_scores}]")
        if s.get("rationale"):
            print(f"    → {s['rationale']}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate research reports on custom dimensions using LLM-as-judge"
    )
    parser.add_argument(
        "--dimensions", type=Path, required=True,
        help="Path to dimensions JSON config file (see dimensions/ for examples)",
    )
    parser.add_argument(
        "--reports-dir", type=Path, default=Path("./reports"),
        help="Directory containing tool subdirs and queries.json",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Optional path to save results JSON",
    )
    parser.add_argument(
        "--region", default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )
    parser.add_argument("--profile", default=None)
    parser.add_argument(
        "--model", default=None,
        help="Bedrock model ID override",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.model:
        global JUDGE_MODEL
        JUDGE_MODEL = args.model

    config = load_dimensions(args.dimensions)
    dimensions = config["dimensions"]
    rubric_name = config.get("name", args.dimensions.stem)

    print(f"Rubric:  {rubric_name}")
    print(f"Reports: {args.reports_dir}")
    print(f"Model:   {JUDGE_MODEL}  Region: {args.region}")

    results = run_eval(
        args.reports_dir,
        dimensions,
        region=args.region,
        profile=args.profile,
        verbose=not args.quiet,
    )
    results["rubric"] = rubric_name

    print_results(results, dimensions)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
