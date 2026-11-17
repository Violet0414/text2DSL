# Plan: M1 对话问数核心（P0）

**Source PRD**: `.claude/prds/smart-bi.prd.md`
**Selected Milestone**: M1 — 对话问数核心（FR-A1–A5、FR-B1–B4、FR-D1–D4、NFR-2）
**Complexity**: Large

## Summary

将 PoC 冻结基线（`poc/planner/`，58/58 全对）升级为服务化 ChatBI 核心模块：在 PoC 规划器之上补齐 PoC 未覆盖的三块——①分步澄清引擎（规则模板生成，先口径后时间）；②会话状态机 + `/api/ask` 服务化（统一信封、AnswerCard 口径五要素、MissResponse、挖掘候选落库）；③治理门禁前置校验 + 查询执行层（wren CLI JSONL 适配）。`poc/` 保持冻结不动，作为 PoC 证据基线；新代码落顶层 `chatbi/` 包。退出标准：服务级黄金集回归 58/58 全对、状态机全路径用例跑通、幻觉拦截率与应未命中正确率两条红线 100%。

## 现状与差距（PoC → M1）

| PRD 需求 | PoC 现状 | M1 待补 |
|---|---|---|
| FR-A3 规划器 | `poc/planner/core.py` 已实现（K1/K2/K3） | 升级为 `chatbi/planner/`，行为保持一致 |
| FR-B1 分步澄清（先口径后时间） | ❌ 单轮一次性 clarify（LLM 生成文案） | 分步状态机 + 规则模板引擎（FR-B2） |
| FR-B2 模板生成澄清 | ❌ LLM 自由生成 | `chatbi/clarify.py` 模板引擎 + 快照测试 |
| FR-B3 时间缺省规则 | 部分在 prompt 规则中 | 固化为代码规则，不依赖 LLM 自觉 |
| FR-B4 枚举外取值澄清 | ❌ | 枚举归一化匹配 → 澄清 |
| FR-A2 口径五要素 | ❌ 只有 cube_query | AnswerCard 组装（指标名/口径/责任人/版本/新鲜度） |
| FR-A4 旁路 / FR-A5 降级矩阵 | behavior=chitchat / error 已有 | 状态机全路径 + 自动化用例 |
| FR-D1 三层防线 | ✅ `core.py:3-6` 已实现 | 保持 + 防线旁路用例 |
| FR-D2 应未命中 | behavior=miss 已有 | MissResponse（可查指标清单 + candidateId） |
| FR-D3 挖掘候选落库 | ❌ | `chatbi/mining.py` Repository |
| FR-D4 门禁前置 | ❌（PoC 无门禁概念） | `chatbi/gate.py` 四门校验 |
| 执行层 | ❌（PoC 只规划不执行） | cube query → wren CLI 执行 + JSONL 解析适配 |
| NFR-2 安全 | 部分（无明细入 prompt） | 注入防护（分隔符+转义）、零凭据校验 |

## 底座实测事实（契约硬前提，来自 PoC 报告）

1. `wren_core.cube_query_to_sql` 进程内编译校验可用；`WrenToolkit.from_project()` 不存在
2. `dateRange` 左闭右开 `[start, end)` → 时间展开全部半开区间（`time_expand.py` 已正确处理）
3. `timeDimensions.granularity` 必填，缺省补 `month`（`core.py:153` 已处理）
4. `wren -o json` 输出 **JSONL**（非数组）→ executor 解析层必须适配
5. 连接 profile 必须含 `datasource` 键 → 配置强校验
6. 幻觉 measure 翻译层硬拒 `Unknown measure` → 防线②原生兜底，错误向上透传

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| Naming | `poc/planner/core.py:35-50` | frozen dataclass 作为不可变 DTO（PlanResult/LlmCall 风格）；模块 snake_case |
| Errors | `poc/planner/core.py:167-204` | 校验/修复返回元组 `(result, reason)` 不抛出；LLM 异常统一归因为字符串字段（`llm.py:77-78`） |
| Data access | 仓库内无既有实现 | 按 `.claude/rules/common/patterns.md` 引入 Repository Protocol（会话、候选两处） |
| API 信封 | PRD §5.2 | `{success, data, error, meta{traceId,latencyMs}}` 统一信封 |
| LLM 调用 | `poc/planner/llm.py:45-84` | call_llm 返回 LlmCall 快照（可落盘回放），tool-use 强制结构化 |
| Tests | 仓库内无既有测试 | pytest + AAA 结构 + 描述性命名（`.claude/rules/common/testing.md`）；澄清文案用快照测试 |
| 评测纪律 | `poc/eval/run_eval.py:234-262` | `--tag <变更名>` 全量回归落 `poc/eval/results/`，红线指标门槛表 |

## 决策定案任务（PRD 开放问题，M1 期必须关闭）

- **Q1 规划模型选型**：Phase 0 用黄金集做候选模型对比评测（`run_eval.py --tag model-<name>`），按红线全对 + P95 定案后锁定 `chatbi/planner/llm.py` 的 MODEL。PoC 实测为 doubao-seed-2-1-turbo（代理），报告须如实记录。
- **Q2 会话存储**：M1 取最简满足 §5.3 的方案——Repository 接口 + 内存实现（单进程服务）+ SQLite 持久化实现，部署环境确认后可平替 Redis（M2 会话管理再扩）。**不在 M1 引入 Redis 依赖**。

## Files to Change

| File | Action | Why |
|---|---|---|
| `chatbi/__init__.py` | CREATE | 顶层包 |
| `chatbi/planner/__init__.py` `core.py` `llm.py` `schema.py` `time_expand.py` | CREATE（自 `poc/planner/` 演进） | 规划器服务化，行为与 PoC 一致（FR-A1/A3、FR-D1 三层防线原样继承） |
| `chatbi/gate.py` | CREATE | 治理门禁四门校验（已确认+试运行通过+工具启用+描述齐备），规划器入口强校验（FR-D4） |
| `chatbi/executor.py` | CREATE | cube query → wren CLI 执行，JSONL 解析，columns[].role/unit 元数据（执行层） |
| `chatbi/clarify.py` | CREATE | 分步澄清引擎：clarifyStep(tax→time→dimension) 状态 + 规则模板生成文案（FR-B1/B2）+ 枚举归一化（FR-B4） |
| `chatbi/time_rules.py` | CREATE | 时间缺省规则固化（FR-B3）：裸指标→澄清时间；带维度/筛选/对比→默认全部时间 |
| `chatbi/session.py` | CREATE | 会话状态机（§5.3：IDLE→ROUTING→FILLING→EXECUTING→ANSWERING / CLARIFYING≤2 / MINING_CANDIDATE / ERROR_ANSWER）+ SessionRepository Protocol |
| `chatbi/store/__init__.py` `memory.py` `sqlite.py` | CREATE | 会话/候选存储实现（Q2 最简方案） |
| `chatbi/mining.py` | CREATE | 挖掘候选落库（问题原文/规范化/用户/时间/检索上下文），对接治理平台 FR-12（接口形式 Q3 先按表共享草案，评审时对齐）（FR-D3） |
| `chatbi/answer.py` | CREATE | AnswerCard 五要素组装 + MissResponse（可查指标清单）+ 响应信封（FR-A2/D2） |
| `chatbi/api.py` | CREATE | FastAPI `POST /api/ask`，统一信封，traceId 生成与分段耗时（FR-A 服务化入口） |
| `chatbi/security.py` | CREATE | 用户问题注入 Prompt 的分隔符包裹+转义；启动时校验无 DB 凭据入链路（NFR-2） |
| `tests/unit/…` `tests/integration/…` | CREATE | 单测（继承/替换/枚举/模板快照/门禁/防线旁路）+ 集成（状态机全路径、信封契约） |
| `eval/run_service_eval.py` | CREATE | 服务级黄金集回归 harness：走状态机全链路（question→AnswerCard/Clarification/Miss），复用 `judge.py` 并扩展 Clarification/MissResponse 判定 |
| `.claude/prds/smart-bi.prd.md` | UPDATE | M1 行状态 pending→in-progress、Plan 列指向本文件 |

> `poc/` 目录**零修改**：它是 PoC 证据基线，`run_eval.py`/报告可复现性必须保留。`chatbi/planner` 从其拷贝演进，演进后与 `poc/planner` 的行为差异用单测显式声明。

## Tasks

### Task 0: 决策定案（Q1/Q2）
- **Action**: 用黄金集跑候选模型对比（各 `--tag model-*`），按红线全对 + P95 锁定模型；确定会话存储为 Repository+内存/SQLite。产出决策记录。
- **Validate**: `poc/.venv/bin/python poc/eval/run_eval.py --tag model-<name>` 各模型报告落盘且红线达标。

### Task 1: chatbi 包骨架 + planner 迁移（TDD）
- **Action**: 建立 `chatbi/` 包；planner 四模块自 `poc/planner/` 演进（不变式：对同一输入产出与 PoC 一致的 PlanResult）。先写"PoC 行为回归"单测（用 `poc/eval/results/results_final2_2026-11-16.json` 中的实际输出作期望值样本）。
- **Mirror**: `poc/planner/core.py` 的 frozen dataclass 与元组返回风格。
- **Validate**: `pytest tests/unit/planner` 全绿；对 10 条抽样黄金题 chatbi.plan() 与 PoC 输出逐字段一致。

### Task 2: 治理门禁 + 执行层
- **Action**: `gate.py` 四门校验（门禁状态数据源 M1 用 mdl.json + 门禁配置文件，治理平台对接 M4）；`executor.py` 调 wren CLI 执行已校验 SQL，JSONL 解析、truncated/超时/空集分类。门禁状态变更后查询立即失效（每请求实时校验）。
- **Mirror**: 错误处理镜像 `_validate_and_repair` 元组返回；JSONL 适配见实测事实 #4。
- **Validate**: 单测覆盖四门各关一门即拒 + JSONL 解析/超时/空集路径。

### Task 3: 分步澄清引擎（FR-B1–B4）
- **Action**: `clarify.py` + `time_rules.py`：clarifyStep 状态（tax→time→dimension）、规则模板渲染（复述理解+选项+一次一类缺口）、澄清轮次计数（≤2 不收敛→MINING_CANDIDATE）、枚举归一化匹配失败→澄清。LLM 只负责识别歧义，**文案 100% 模板生成**。
- **Mirror**: 模板同输入同文案（快照测试）；口径红线——裸"销售额"一律澄清（K2）。
- **Validate**: 澄清文案快照测试；黄金集口径歧义层 4/4、时间表达层 8/8 保持。

### Task 4: 状态机 + 会话/候选存储 + 应答组装
- **Action**: `session.py` 状态机（§5.3 全路径，状态外置）；`store/` 两个 Repository 实现；`mining.py` 候选落库（未命中/低置信 2 轮不收敛/no_match 三入口）；`answer.py` 组装三类响应。失败降级矩阵（FR-A5）全路径实现。
- **Validate**: 状态机全路径参数化用例；候选落库率 100% 用例；重置后首轮与全新会话一致（FR-C4 提前覆盖基础版）。

### Task 5: API 服务 + NFR-2 安全
- **Action**: `api.py` FastAPI 入口（统一信封、traceId、分段耗时字段预留）；`security.py` 注入防护（问题文本包裹转义后才入 prompt）、启动断言链路零 DB 凭据。
- **Validate**: 信封契约集成测试；注入用例（问题含指令文本时仅作为数据段处理）。

### Task 6: 服务级黄金集回归 + 状态机全路径验收
- **Action**: `eval/run_service_eval.py` 走全链路跑 58 条；`judge.py` 扩展判定 Clarification（分步选项）与 MissResponse（含可查指标清单）。任一失败修复后全量重跑。
- **Validate**: `--tag m1-service` 报告：58/58 全对、两条红线 100%、澄清触发率 ≥95%。

## Validation

```bash
# 单测 + 覆盖率（目标 ≥80%）
cd /home/mxr/text2DSL && poc/.venv/bin/python -m pytest tests/ --cov=chatbi --cov-report=term-missing

# PoC 基线回归（poc 未动，应保持 58/58）
cd /home/mxr/text2DSL/poc && .venv/bin/python eval/run_eval.py --tag m1-baseline-check

# M1 服务级黄金集回归（验收门槛）
cd /home/mxr/text2DSL/poc && .venv/bin/python ../eval/run_service_eval.py --tag m1-service

# lint/format
cd /home/mxr/text2DSL && poc/.venv/bin/ruff check chatbi tests && poc/.venv/bin/black --check chatbi tests
```

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 模板化澄清替换 LLM 澄清后，黄金集澄清层基线（4/4、选项机械合格）回归失败 | 中 | 高 | Task 3 先跑澄清分层回归再合入；模板措辞以 PoC 实际输出为快照基准 |
| Q1 换模型导致全量基线漂移 | 中 | 高 | Task 0 率先定案；模型变更后立即全量回归，不达标不锁模型 |
| wren CLI 执行层延迟叠加，P95 恶化（现状 5579ms 已超 5s） | 高 | 中 | 分段耗时上报自 M1 建立；执行层不引入新瓶颈；NFR-1 优化主体留 M5，但 M1 建立基线防止劣化 |
| 门禁状态数据源 M1 无治理平台，配置文件临时方案与 M4 对接冲突 | 低 | 低 | gate.py 走 Repository 接口，M4 只换实现 |
| Q3 挖掘候选接口未与治理平台对齐 | 中 | 低 | M1 按表共享草案实现，开放问题跟踪 |
| wren CLI 执行需真实连接 profile（datasource 键） | 低 | 中 | executor 配置强校验 + 连接失败明确降级（FR-A5 矩阵内） |

## Acceptance

- [ ] 黄金集 58/58 全对（服务级回归 `--tag m1-service`）
- [ ] 幻觉拦截率 / 应未命中正确率两条红线 100%
- [ ] 状态机全路径（§5.3）自动化用例跑通，降级矩阵（FR-A5）全覆盖
- [ ] 澄清 ≤2 轮收敛，文案快照测试通过（同输入同文案）
- [ ] Q1/Q2 决策定案并记录；Q3 留治理平台评审
- [ ] NFR-2 注入用例 + 零凭据校验通过
- [ ] pytest 覆盖率 ≥80%，ruff/black 通过
- [ ] `poc/` 目录零修改（diff 为空）

---
*Status: DRAFT — 待用户确认后进入实施（建议以 tdd-workflow 按 Task 顺序执行）。*
