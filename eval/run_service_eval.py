"""服务级黄金集回归 harness(Task 6):58 条问题走 ChatPipeline 全链路。

与 poc/eval/run_eval.py(规划层)的区别:本题经 状态机+门禁+澄清模板+真实执行 出应答,
判定沿用 poc/eval/judge.py 的三维口径(工具选择/参数/行为)。

用法:
  python eval/run_service_eval.py                    # 全量 58 条
  python eval/run_service_eval.py --limit 6          # 抽样冒烟
  python eval/run_service_eval.py --layers 口径歧义   # 分层回归
  python eval/run_service_eval.py --tag m1-service   # 结果落盘标签
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
POC_DIR = REPO_ROOT / "poc"
sys.path.insert(0, str(POC_DIR))  # judge.py 内部依赖 poc 的 planner.time_expand
sys.path.insert(0, str(REPO_ROOT))  # chatbi 包

_spec = importlib.util.spec_from_file_location(
    "poc_judge", POC_DIR / "eval" / "judge.py"
)
poc_judge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(poc_judge)

from chatbi.executor import WrenCliExecutor
from chatbi.gate import FileGateStateRepository, GovernanceGate
from chatbi.pipeline import ChatPipeline
from chatbi.planner.core import MDL_PATH
from chatbi.planner.schema import load_mdl
from chatbi.store.memory import InMemoryMiningRepository, InMemorySessionRepository

GOLDEN_PATH = REPO_ROOT / "poc" / "eval" / "golden_questions.jsonl"
RESULTS_DIR = POC_DIR / "eval" / "results"
MULTI_TURN_LAYERS = {"多轮-时间变更", "多轮-维度变更", "多轮-指标变更", "多轮-指代消解"}


@dataclass(frozen=True)
class JudgeShim:
    """服务载荷 → judge.PlanResult 形状的适配对象(仅含判定所需字段)。"""

    question: str
    behavior: str
    cube_query: dict | None = None
    clarify_question: str | None = None
    clarify_options: tuple[str, ...] = ()
    reply: str | None = None
    validation: str = "passed"


def payload_to_judge(payload) -> JudgeShim:
    """把 ChatPipeline 应答载荷映射为判定器可判的形状。"""
    t = payload.type
    if t == "answer":
        return JudgeShim(
            question="",
            behavior="query",
            cube_query=payload.cube_query,
            reply=payload.message or None,
        )
    if t == "clarification":
        return JudgeShim(
            question="",
            behavior="clarify",
            clarify_question=payload.question_text,
            clarify_options=tuple(payload.options),
        )
    if t == "miss":
        return JudgeShim(question="", behavior="miss", reply=payload.message)
    if t == "reply":
        return JudgeShim(question="", behavior="chitchat", reply=payload.text)
    return JudgeShim(
        question="", behavior="error", reply=getattr(payload, "message", "")
    )


def build_pipeline() -> ChatPipeline:
    """评测装配:内存会话/候选 + 默认文件门禁 + 真实 wren CLI 执行。"""
    gate = GovernanceGate(FileGateStateRepository(), load_mdl(MDL_PATH))
    return ChatPipeline(
        session_store=InMemorySessionRepository(),
        mining_store=InMemoryMiningRepository(),
        gate=gate,
        executor=WrenCliExecutor(),
        llm=None,  # 默认客户端(环境变量凭据)
    )


def load_golden() -> list[dict]:
    return [
        json.loads(line)
        for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_item(pipe: ChatPipeline, item: dict, session_id: str) -> dict:
    """单题全链路:ask → 载荷 → 判定。"""
    started = time.monotonic()
    try:
        payload = pipe.ask(session_id, item["question"])
    except Exception as exc:  # noqa: BLE001 — 单题异常不拖垮全量
        shim = JudgeShim(
            question=item["question"], behavior="error", reply=str(exc)[:300]
        )
        latency = int((time.monotonic() - started) * 1000)
        return _record(item, shim, latency, error=str(exc)[:300])
    latency = int((time.monotonic() - started) * 1000)
    shim = payload_to_judge(payload)
    return _record(item, shim, latency)


def _record(
    item: dict, shim: JudgeShim, latency_ms: int, error: str | None = None
) -> dict:
    verdict = poc_judge.judge_item(item["expected"], shim)
    return {
        "id": item["id"],
        "layer": item["layer"],
        "question": item["question"],
        "expected": item["expected"],
        "behavior": shim.behavior,
        "cube_query": shim.cube_query,
        "clarify_question": shim.clarify_question,
        "clarify_options": list(shim.clarify_options),
        "reply": (shim.reply or "")[:300],
        "latency_ms": latency_ms,
        "error": error,
        "verdict": verdict,
        "attribution": (
            None
            if verdict["all_ok"]
            else poc_judge.attribute_failure(item["expected"], shim)
        ),
    }


def run_all(pipe: ChatPipeline, questions: list[dict]) -> list[dict]:
    """全量执行:单题独立会话;多轮链共享会话(槽位继承走真实状态机)。"""
    records: list[dict] = []
    singles = [q for q in questions if "chain" not in q]
    chains: dict[str, list[dict]] = {}
    for q in questions:
        if "chain" in q:
            chains.setdefault(q["chain"], []).append(q)
    for q in singles:
        records.append(run_item(pipe, q, session_id=f"eval-{q['id']}"))
    for chain_id in sorted(chains):
        sid = f"eval-chain-{chain_id}"
        for item in sorted(chains[chain_id], key=lambda x: x["turn"]):
            records.append(run_item(pipe, item, session_id=sid))
    return records


def aggregate(records: list[dict]) -> dict:
    """服务级指标汇总(门槛对齐 PRD §7.2)。"""

    def rate(num: int, den: int) -> float | None:
        return round(num / den, 4) if den else None

    query_items = [r for r in records if r["expected"]["behavior"] == "query"]
    clarify_items = [r for r in records if r["expected"]["behavior"] == "clarify"]
    miss_items = [r for r in records if r["expected"]["behavior"] == "miss"]
    chitchat_items = [r for r in records if r["expected"]["behavior"] == "chitchat"]
    turn2 = [
        r for r in records if r["layer"].startswith("多轮-") and r["id"].endswith("T2")
    ]
    latencies = sorted(r["latency_ms"] for r in records if r["latency_ms"] > 0)

    tool_correct = sum(1 for r in query_items if r["verdict"]["tool_ok"])
    param_correct = sum(1 for r in query_items if r["verdict"]["params_ok"])
    clarify_triggered = sum(1 for r in clarify_items if r["behavior"] == "clarify")
    clarify_options_ok = sum(
        1 for r in clarify_items if r["verdict"]["clarify_options_ok"]
    )
    miss_correct = sum(1 for r in miss_items if r["behavior"] == "miss")
    chitchat_correct = sum(1 for r in chitchat_items if r["behavior"] == "chitchat")
    multi_correct = sum(1 for r in turn2 if r["verdict"]["all_ok"])

    return {
        "总条数": len(records),
        "全对条数": sum(1 for r in records if r["verdict"]["all_ok"]),
        "工具选择准确率": rate(tool_correct, len(query_items)),
        "参数准确率": rate(param_correct, len(query_items)),
        "应未命中正确率": rate(miss_correct, len(miss_items)),
        "旁路正确率": rate(chitchat_correct, len(chitchat_items)),
        "澄清触发率": rate(clarify_triggered, len(clarify_items)),
        "澄清选项机械合格率": rate(clarify_options_ok, len(clarify_items)),
        "多轮继承正确率": rate(multi_correct, len(turn2)),
        "P95延迟ms": latencies[int(len(latencies) * 0.95) - 1] if latencies else None,
        "失败归因": dict(
            Counter(r["attribution"] for r in records if r["attribution"])
        ),
        "分层正确率": {
            layer: f"{sum(1 for r in records if r['layer'] == layer and r['verdict']['all_ok'])}/{sum(1 for r in records if r['layer'] == layer)}"
            for layer in sorted({r["layer"] for r in records})
        },
    }


def write_report(
    metrics: dict, records: list[dict], out_path: Path, wall_s: float
) -> None:
    """门槛表 + 失败明细(格式对齐 poc 报告纪律)。"""
    thresholds = {
        "工具选择准确率": ("≥90%", 0.90),
        "参数准确率": ("≥90%", 0.90),
        "应未命中正确率": ("100%(红线)", 1.0),
        "旁路正确率": ("100%", 1.0),
        "澄清触发率": ("≥95%", 0.95),
        "多轮继承正确率": ("≥85%", 0.85),
    }
    lines = [
        "# 服务级黄金集回归报告(M1 Task 6,自动生成)",
        "",
        f"- 评测日期:{date.today().isoformat()}",
        "- 链路:ChatPipeline 全链路(状态机+门禁+澄清模板+真实执行)",
        f"- 墙钟:{wall_s:.0f}s",
        "",
        "## 指标达标表",
        "",
        "| 指标 | 实测 | 门槛 | 达标 |",
        "|---|---|---|---|",
    ]
    for name, (label, th) in thresholds.items():
        v = metrics.get(name)
        ok = "✅" if v is not None and v >= th else "❌"
        lines.append(f"| {name} | {v} | {label} | {ok} |")
    p95 = metrics["P95延迟ms"]
    lines.append(
        f"| P95延迟 | {p95}ms | ≤5000ms(服务级含执行,红线在 M5) | "
        f"{'✅' if (p95 or 99999) <= 5000 else '❌'} |"
    )
    lines += [
        "",
        "## 全对红线",
        "",
        f"- 全对: {metrics['全对条数']}/{metrics['总条数']}(门槛 58/58)",
    ]
    lines += ["", "## 分层正确率", ""] + [
        f"- {k}: {v}" for k, v in metrics["分层正确率"].items()
    ]
    lines += ["", "## 失败归因", ""] + (
        [f"- {k}: {v}" for k, v in metrics["失败归因"].items()] or ["- 无失败"]
    )
    failed = [r for r in records if not r["verdict"]["all_ok"]]
    lines += ["", "## 失败明细", ""]
    if not failed:
        lines.append("无")
    for r in failed:
        lines.append(
            f"### {r['id']} ({r['layer']}) {r['question']}\n"
            f"- 期望: {json.dumps(r['expected'], ensure_ascii=False)}\n"
            f"- 实际: behavior={r['behavior']} cube_query={json.dumps(r['cube_query'], ensure_ascii=False)} "
            f"clarify_options={json.dumps(r['clarify_options'], ensure_ascii=False)} reply={r['reply']}\n"
            f"- 归因: {r['attribution']}\n"
        )
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--layers", type=str, default=None, help="逗号分隔层名")
    parser.add_argument("--tag", type=str, default="service")
    args = parser.parse_args()

    questions = load_golden()
    if args.layers:
        wanted = {l.strip() for l in args.layers.split(",")}
        questions = [q for q in questions if q["layer"] in wanted]
    if args.limit:
        questions = questions[: args.limit]

    pipe = build_pipeline()
    started = time.monotonic()
    records = run_all(pipe, questions)
    wall = time.monotonic() - started
    metrics = aggregate(records)

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = date.today().isoformat()
    results_path = RESULTS_DIR / f"results_service_{args.tag}_{stamp}.json"
    results_path.write_text(
        json.dumps(
            {"metrics": metrics, "records": records}, ensure_ascii=False, indent=1
        ),
        encoding="utf-8",
    )
    report_path = RESULTS_DIR / f"report_service_{args.tag}_{stamp}.md"
    write_report(metrics, records, report_path, wall)
    print(json.dumps(metrics, ensure_ascii=False, indent=1))
    print(f"\nresults -> {results_path}\nreport  -> {report_path}\nwall={wall:.0f}s")


if __name__ == "__main__":
    main()
