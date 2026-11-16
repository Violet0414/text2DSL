"""PoC 评测 harness:50 条黄金问题 + 4 组多轮链 → 指标汇总 + 失败归因 + 落盘。

用法:
  python eval/run_eval.py                 # 全量 58 条
  python eval/run_eval.py --limit 10      # 抽样
  python eval/run_eval.py --layers 口径歧义,缺参澄清   # 分层回归
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import date
from pathlib import Path
from sys import path as sys_path

sys_path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.judge import attribute_failure, judge_item  # noqa: E402
from planner.core import plan  # noqa: E402

GOLDEN_PATH = Path(__file__).resolve().parent / "golden_questions.jsonl"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
TODAY = date(2026, 11, 16)

MULTI_TURN_LAYERS = {"多轮-时间变更", "多轮-维度变更", "多轮-指标变更", "多轮-指代消解"}


def _error_result(question: str, exc: Exception):
    """Build a PlanResult-shaped record for a crashed planning call."""
    from planner.core import PlanResult

    return PlanResult(
        question=question,
        behavior="error",
        llm_error=f"{type(exc).__name__}: {exc}",
    )


def load_golden() -> list[dict]:
    return [
        json.loads(line)
        for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_chain(chain: list[dict]) -> list[dict]:
    """Run a multi-turn chain, feeding each turn's result into the next."""
    records = []
    history: list[dict] = []
    for item in chain:
        try:
            result = plan(item["question"], history=history)
        except Exception as exc:  # noqa: BLE001 — 单题异常不拖垮全量回归
            result = _error_result(item["question"], exc)
        verdict = judge_item(item["expected"], result)
        records.append(
            {
                "id": item["id"],
                "layer": item["layer"],
                "question": item["question"],
                "expected": item["expected"],
                "behavior": result.behavior,
                "cube_query": result.cube_query,
                "clarify_question": result.clarify_question,
                "clarify_options": list(result.clarify_options),
                "reply": result.reply,
                "validation": result.validation,
                "latency_ms": result.llm_latency_ms,
                "llm_error": result.llm_error,
                "raw_output": result.raw_output[:2000],
                "verdict": verdict,
                "attribution": (
                    None
                    if verdict["all_ok"]
                    else attribute_failure(item["expected"], result)
                ),
            }
        )
        history.append(
            {"question": item["question"], "result": {"behavior": result.behavior, "cube_query": result.cube_query}}
        )
    return records


def run_all(questions: list[dict]) -> list[dict]:
    """Run all single questions and multi-turn chains, return records."""
    records: list[dict] = []
    singles = [q for q in questions if "chain" not in q]
    chains: dict[str, list[dict]] = {}
    for q in questions:
        if "chain" in q:
            chains.setdefault(q["chain"], []).append(q)
    for q in singles:
        try:
            result = plan(q["question"])
        except Exception as exc:  # noqa: BLE001 — 单题异常不拖垮全量回归
            result = _error_result(q["question"], exc)
        verdict = judge_item(q["expected"], result)
        records.append(_record(q, result, verdict))
    for chain_id in sorted(chains):
        records.extend(run_chain(sorted(chains[chain_id], key=lambda x: x["turn"])))
    return records


def _record(q: dict, result, verdict: dict) -> dict:
    return {
        "id": q["id"],
        "layer": q["layer"],
        "question": q["question"],
        "expected": q["expected"],
        "behavior": result.behavior,
        "cube_query": result.cube_query,
        "clarify_question": result.clarify_question,
        "clarify_options": list(result.clarify_options),
        "reply": (result.reply or "")[:300],
        "validation": result.validation,
        "latency_ms": result.llm_latency_ms,
        "llm_error": result.llm_error,
        "raw_output": result.raw_output[:2000],
        "verdict": verdict,
        "attribution": None if verdict["all_ok"] else attribute_failure(q["expected"], result),
    }


def aggregate(records: list[dict]) -> dict:
    """Compute the §四 metric table from per-item records."""
    n = len(records)
    latencies = sorted(r["latency_ms"] for r in records if r["latency_ms"] > 0)

    def rate(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    query_items = [r for r in records if r["expected"]["behavior"] == "query"]
    clarify_items = [r for r in records if r["expected"]["behavior"] == "clarify"]
    miss_items = [r for r in records if r["expected"]["behavior"] == "miss"]
    chitchat_items = [r for r in records if r["expected"]["behavior"] == "chitchat"]
    multi_turn = [r for r in records if r["layer"] in MULTI_TURN_LAYERS and r["question"] != r["expected"].get("first_turn_question", r["question"])]

    # 多轮继承:只统计每链 turn≥2 的追问轮
    turn2 = [r for r in records if r["layer"].startswith("多轮-") and r["id"].endswith("T2")]

    tool_correct = sum(1 for r in query_items if r["verdict"]["tool_ok"])
    param_correct = sum(1 for r in query_items if r["verdict"]["params_ok"])
    miss_correct = sum(1 for r in miss_items if r["behavior"] == "miss")
    chitchat_correct = sum(1 for r in chitchat_items if r["behavior"] == "chitchat")
    clarify_triggered = sum(1 for r in clarify_items if r["behavior"] == "clarify")
    clarify_options_ok = sum(1 for r in clarify_items if r["verdict"]["clarify_options_ok"])
    multi_correct = sum(1 for r in turn2 if r["verdict"]["all_ok"])

    # 幻觉拦截率:应未命中正确 + 编译层拦截,红线 100%
    hallucination_blocked = miss_correct + sum(
        1 for r in records if r["validation"] == "intercepted"
    )

    return {
        "总条数": n,
        "全对条数": sum(1 for r in records if r["verdict"]["all_ok"]),
        "工具选择准确率": rate(tool_correct, len(query_items)),
        "工具选择分子": f"{tool_correct}/{len(query_items)}",
        "参数准确率": rate(param_correct, len(query_items)),
        "参数分子": f"{param_correct}/{len(query_items)}",
        "幻觉拦截率": rate(hallucination_blocked, max(len(miss_items), 1)),
        "应未命中正确率": rate(miss_correct, len(miss_items)),
        "澄清触发率": rate(clarify_triggered, len(clarify_items)),
        "澄清分子": f"{clarify_triggered}/{len(clarify_items)}",
        "澄清选项机械合格率": rate(clarify_options_ok, len(clarify_items)),
        "旁路正确率": rate(chitchat_correct, len(chitchat_items)),
        "多轮继承正确率": rate(multi_correct, len(turn2)),
        "多轮分子": f"{multi_correct}/{len(turn2)}",
        "P95延迟ms": latencies[int(len(latencies) * 0.95) - 1] if latencies else None,
        "失败归因": dict(Counter(r["attribution"] for r in records if r["attribution"])),
        "分层正确率": {
            layer: f"{sum(1 for r in records if r['layer'] == layer and r['verdict']['all_ok'])}/{sum(1 for r in records if r['layer'] == layer)}"
            for layer in sorted({r["layer"] for r in records})
        },
    }


def write_report(metrics: dict, records: list[dict], out_path: Path) -> None:
    """Render a markdown report: metric table vs thresholds + failures."""
    thresholds = {
        "工具选择准确率": ("≥90%", 0.90),
        "参数准确率": ("≥90%", 0.90),
        "幻觉拦截率": ("100%(红线)", 1.0),
        "应未命中正确率": ("100%(红线)", 1.0),
        "澄清触发率": ("≥95%", 0.95),
        "多轮继承正确率": ("≥85%", 0.85),
    }
    lines = [
        "# PoC 评测报告(自动生成)",
        "",
        f"- 评测日期:2026-11-16(冻结日)",
        f"- 规划器 LLM:{records[0].get('llm_model', 'doubao-seed-2-1-turbo(经 ANTHROPIC_BASE_URL 代理)')}",
        "",
        "## 指标达标表",
        "",
        "| 指标 | 实测 | 门槛 | 达标 |",
        "|---|---|---|---|",
    ]
    for name, (label, th) in thresholds.items():
        v = metrics.get(name)
        ok = "✅" if v is not None and v >= th else "❌"
        denom = {"工具选择准确率": metrics["工具选择分子"], "参数准确率": metrics["参数分子"], "澄清触发率": metrics["澄清分子"], "多轮继承正确率": metrics["多轮分子"]}.get(name, "")
        lines.append(f"| {name} | {v} {denom} | {label} | {ok} |")
    lines.append(f"| P95延迟 | {metrics['P95延迟ms']}ms | ≤5000ms | {'✅' if (metrics['P95延迟ms'] or 99999) <= 5000 else '❌'} |")
    lines += [
        "",
        "## 分层正确率",
        "",
    ]
    lines += [f"- {k}: {v}" for k, v in metrics["分层正确率"].items()]
    lines += ["", "## 失败归因(分类计数)", ""]
    lines += [f"- {k}: {v}" for k, v in metrics["失败归因"].items()] or ["- 无失败"]
    lines += ["", "## 失败明细", ""]
    failed = [r for r in records if not r["verdict"]["all_ok"]]
    if not failed:
        lines.append("无")
    for r in failed:
        lines.append(
            f"### {r['id']} ({r['layer']}) {r['question']}\n"
            f"- 期望: {json.dumps(r['expected'], ensure_ascii=False)}\n"
            f"- 实际: behavior={r['behavior']} validation={r['validation']} "
            f"cube_query={json.dumps(r['cube_query'], ensure_ascii=False)} "
            f"clarify_options={json.dumps(r['clarify_options'], ensure_ascii=False)}\n"
            f"- 归因: {r['attribution']}\n"
        )
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--layers", type=str, default=None, help="逗号分隔层名")
    parser.add_argument("--tag", type=str, default="full")
    args = parser.parse_args()

    questions = load_golden()
    if args.layers:
        wanted = {l.strip() for l in args.layers.split(",")}
        questions = [q for q in questions if q["layer"] in wanted]
    if args.limit:
        questions = questions[: args.limit]

    started = time.monotonic()
    records = run_all(questions)
    metrics = aggregate(records)
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = date.today().isoformat()
    results_path = RESULTS_DIR / f"results_{args.tag}_{stamp}.json"
    results_path.write_text(
        json.dumps({"metrics": metrics, "records": records}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    report_path = RESULTS_DIR / f"report_{args.tag}_{stamp}.md"
    write_report(metrics, records, report_path)
    wall = time.monotonic() - started
    print(json.dumps(metrics, ensure_ascii=False, indent=1))
    print(f"\nresults -> {results_path}\nreport  -> {report_path}\nwall={wall:.0f}s")


if __name__ == "__main__":
    main()
