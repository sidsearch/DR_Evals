"""
Lightweight Deep Research Eval Framework
Inspired by DeepResearch Bench (RACE methodology)

Usage:
    python eval.py --reports-dir ./reports --output results.json

Report directory structure:
    reports/
        tool_a/
            report_01.md
            report_02.md
            ...
        tool_b/
            report_01.md
            report_02.md
            ...
        queries.json   # {"report_01": "original query/question", ...}
"""

import boto3
import json
import os
import re
import argparse
from pathlib import Path
from dataclasses import dataclass, asdict


# ── Scoring dimensions (RACE-inspired) ─────────────────────────────────────

DIMENSIONS = {
    "comprehensiveness": {
        "weight": 0.30,
        "description": "Breadth of coverage: does the report address all key aspects of the query?",
    },
    "depth": {
        "weight": 0.30,
        "description": "Sophistication of analysis: nuanced reasoning, not just surface facts.",
    },
    "instruction_following": {
        "weight": 0.20,
        "description": "Does the report directly answer the original query and follow any implicit constraints?",
    },
    "readability": {
        "weight": 0.20,
        "description": "Clarity, structure, and presentation quality.",
    },
}

# Bedrock cross-region inference profile ID for Claude Opus 4
# Override via --model or BEDROCK_MODEL env var
JUDGE_MODEL = os.environ.get(
    "BEDROCK_MODEL",
    "us.anthropic.claude-opus-4-5-20251101-v1:0",
)

JUDGE_PROMPT_TEMPLATE = """\
You are an expert research evaluator. Score the following research report on four dimensions.

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

Dimensions:
1. comprehensiveness — {comprehensiveness}
2. depth — {depth}
3. instruction_following — {instruction_following}
4. readability — {readability}

Respond ONLY with a JSON object in this exact format:
{{
  "comprehensiveness": <int>,
  "depth": <int>,
  "instruction_following": <int>,
  "readability": <int>,
  "rationale": "<1-2 sentence summary of overall quality>"
}}
"""


# ── Data structures ─────────────────────────────────────────────────────────

@dataclass
class ReportScore:
    tool: str
    report_id: str
    query: str
    comprehensiveness: int
    depth: int
    instruction_following: int
    readability: int
    weighted_total: float
    rationale: str
    raw_response: str


@dataclass
class ToolSummary:
    tool: str
    n: int
    mean_comprehensiveness: float
    mean_depth: float
    mean_instruction_following: float
    mean_readability: float
    mean_weighted_total: float
    std_weighted_total: float


# ── Judge ───────────────────────────────────────────────────────────────────

def judge_report(client, query: str, report: str) -> dict:
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        query=query,
        report=report,
        **{k: v["description"] for k, v in DIMENSIONS.items()},
    )

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "messages": [{"role": "user", "content": prompt}],
    })

    response = client.invoke_model(modelId=JUDGE_MODEL, body=body)
    result = json.loads(response["body"].read())
    raw = result["content"][0]["text"].strip()

    # Extract JSON even if model adds surrounding text
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"Could not parse JSON from judge response:\n{raw}")

    parsed = json.loads(match.group())
    return parsed, raw


def weighted_total(scores: dict) -> float:
    return sum(
        scores[dim] * DIMENSIONS[dim]["weight"]
        for dim in DIMENSIONS
    )


# ── Loader ──────────────────────────────────────────────────────────────────

def load_reports(reports_dir: Path) -> tuple[dict, dict]:
    """
    Returns:
        tools_reports: {tool_name: {report_id: report_text}}
        queries:       {report_id: query_string}
    """
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
            report_id = report_file.stem
            reports[report_id] = report_file.read_text()
        if reports:
            tools_reports[tool_dir.name] = reports

    return tools_reports, queries


# ── Evaluation runner ───────────────────────────────────────────────────────

def run_eval(reports_dir: Path, region: str = "us-east-1", profile: str = None, verbose: bool = True) -> dict:
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    client = session.client("bedrock-runtime", region_name=region)
    tools_reports, queries = load_reports(reports_dir)

    all_scores: list[ReportScore] = []

    for tool, reports in tools_reports.items():
        for report_id, report_text in reports.items():
            query = queries.get(report_id, "")
            if not query:
                print(f"  [warn] No query found for {report_id}, skipping.")
                continue

            if verbose:
                print(f"  Judging {tool}/{report_id} ...", end=" ", flush=True)

            try:
                scores, raw = judge_report(client, query, report_text)
            except Exception as e:
                print(f"ERROR: {e}")
                continue

            wt = weighted_total(scores)

            score = ReportScore(
                tool=tool,
                report_id=report_id,
                query=query,
                comprehensiveness=scores["comprehensiveness"],
                depth=scores["depth"],
                instruction_following=scores["instruction_following"],
                readability=scores["readability"],
                weighted_total=round(wt, 3),
                rationale=scores.get("rationale", ""),
                raw_response=raw,
            )
            all_scores.append(score)

            if verbose:
                print(f"score={wt:.2f}")

    return summarize(all_scores)


# ── Summary ─────────────────────────────────────────────────────────────────

def _mean(vals):
    return round(sum(vals) / len(vals), 3) if vals else 0.0


def _std(vals):
    if len(vals) < 2:
        return 0.0
    m = sum(vals) / len(vals)
    return round((sum((x - m) ** 2 for x in vals) / len(vals)) ** 0.5, 3)


def summarize(scores: list[ReportScore]) -> dict:
    by_tool: dict[str, list[ReportScore]] = {}
    for s in scores:
        by_tool.setdefault(s.tool, []).append(s)

    summaries = []
    for tool, tool_scores in by_tool.items():
        wts = [s.weighted_total for s in tool_scores]
        summaries.append(ToolSummary(
            tool=tool,
            n=len(tool_scores),
            mean_comprehensiveness=_mean([s.comprehensiveness for s in tool_scores]),
            mean_depth=_mean([s.depth for s in tool_scores]),
            mean_instruction_following=_mean([s.instruction_following for s in tool_scores]),
            mean_readability=_mean([s.readability for s in tool_scores]),
            mean_weighted_total=_mean(wts),
            std_weighted_total=_std(wts),
        ))

    summaries.sort(key=lambda x: x.mean_weighted_total, reverse=True)

    return {
        "summaries": [asdict(s) for s in summaries],
        "per_report": [asdict(s) for s in scores],
        "dimension_weights": {k: v["weight"] for k, v in DIMENSIONS.items()},
    }


# ── Reporting ────────────────────────────────────────────────────────────────

def print_results(results: dict):
    print("\n" + "=" * 60)
    print("DEEP RESEARCH EVAL RESULTS")
    print("=" * 60)
    print(f"\nScoring: each dimension 1–10, weighted total out of 10")
    print(f"Weights: " + ", ".join(
        f"{k}={v['weight']:.0%}" for k, v in DIMENSIONS.items()
    ))

    print("\n── Leaderboard ──────────────────────────────────────────")
    header = f"{'Tool':<20} {'N':>3}  {'Comp':>5}  {'Depth':>5}  {'InsFol':>6}  {'Read':>5}  {'TOTAL':>6}  {'±':>5}"
    print(header)
    print("-" * len(header))

    for s in results["summaries"]:
        print(
            f"{s['tool']:<20} {s['n']:>3}  "
            f"{s['mean_comprehensiveness']:>5.2f}  "
            f"{s['mean_depth']:>5.2f}  "
            f"{s['mean_instruction_following']:>6.2f}  "
            f"{s['mean_readability']:>5.2f}  "
            f"{s['mean_weighted_total']:>6.2f}  "
            f"{s['std_weighted_total']:>5.2f}"
        )

    print("\n── Per-report breakdown ─────────────────────────────────")
    for s in results["per_report"]:
        print(
            f"  {s['tool']}/{s['report_id']}  "
            f"total={s['weighted_total']:.2f}  "
            f"[C={s['comprehensiveness']} D={s['depth']} "
            f"I={s['instruction_following']} R={s['readability']}]"
        )
        if s["rationale"]:
            print(f"    → {s['rationale']}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Deep Research LLM-as-Judge Eval")
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
        help="AWS region for Bedrock (default: us-east-1)",
    )
    parser.add_argument(
        "--profile", default=None,
        help="AWS CLI profile name (default: uses default credential chain)",
    )
    parser.add_argument(
        "--model", default=None,
        help="Bedrock model ID override (default: BEDROCK_MODEL env var or built-in default)",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.model:
        global JUDGE_MODEL
        JUDGE_MODEL = args.model

    print(f"Loading reports from: {args.reports_dir}")
    print(f"Model: {JUDGE_MODEL}  Region: {args.region}")
    results = run_eval(args.reports_dir, region=args.region, profile=args.profile, verbose=not args.quiet)
    print_results(results)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
