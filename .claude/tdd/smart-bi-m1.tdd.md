# TDD 证据报告 — M1 对话问数核心(Task 1-5 框架)

**Source plan**: `.claude/plans/smart-bi.plan.md`(用户已确认;Task 0 模型对比与 Task 6 服务级黄金集回归因 appkey 未配置延后,用户指示「先搞框子,模型这块我后期填入appkey」)

## 用户旅程(源自计划)
1. 业务分析师用自然语言提问 → 得到带口径五要素的 AnswerCard
2. 口径歧义/缺时间 → 分步模板澄清(≤2 轮),不收敛进挖掘候选
3. 未定义指标 → MissResponse + 候选落库,绝不瞎答(红线)
4. 非问数意图 → 旁路普通对话
5. 执行失败/超时/空集 → 明确解释,绝不返回未经验证的数据

## Task 报告(Task → 测试 → RED → GREEN)

| Task | 执行摘要 | RED 证据 | GREEN 证据 | 提交 |
|---|---|---|---|---|
| 1 planner 迁移 | chatbi/planner 四模块自 poc 演进,LLM 客户端可注入 | ModuleNotFoundError: chatbi(29 测试收集失败) | 29 passed | 87776ad→e5e4d9f |
| 2 门禁+执行层 | 四门实时校验;wren CLI JSONL 解析;timeout/cli_error/parse_error 分类 | 收集错误(chatbi.gate/executor 不存在) | 47 passed | 4e3663b→43e360f |
| 3 澄清+时间规则 | FR-B1/B2/B4 模板引擎;FR-B3 代码化 | 收集错误 | 63 passed | (含 Task3 RED)→482232a |
| 4 状态机+存储 | §5.3 流水线编排;澄清≤2轮;候选落库;SQLite/内存双仓库 | 收集错误 | 79 passed | 44cb1dc→0256af9 |
| 5 API+安全 | 统一信封;分隔符包裹防注入;零 DB 凭据启动校验 | 收集错误 | 94 passed | dc4097b→5504ae4 |

## 测试保证表(核心 10 项)

| # | 保证 | 测试 | 类型 | 结果 |
|---|---|---|---|---|
| 1 | last_month 展开为半开区间 [10-01,11-01) | test_time_expand.py::test_last_month_is_half_open | unit | PASS |
| 2 | schema 枚举只含 MDL 白名单成员 | test_schema.py::test_measure_enum_come_from_mdl_whitelist | unit | PASS |
| 3 | 幻觉 measure 编译拦截→修复一次→仍失败降级澄清,绝不出数 | test_core.py::test_hallucinated_measure_intercepted_then_degrades_to_clarify | unit | PASS |
| 4 | K3 时间槽位从上一轮确定性继承 | test_core.py::test_time_slot_inherited_from_previous_turn | unit | PASS |
| 5 | 四门任一关闭即拒,未登记指标安全默认拒绝 | test_gate.py(参数化) | unit | PASS |
| 6 | JSONL 逐行解析(非数组);超时/CLI 错误/解析错误分类 | test_executor.py | unit | PASS |
| 7 | 裸指标无修饰→模板澄清时间;带维度/筛选→all_time | test_time_rules.py | unit | PASS |
| 8 | 澄清同输入同文案(快照);分步 tax→time→dimension | test_clarify.py | unit | PASS |
| 9 | 澄清 2 轮不收敛→挖掘候选落库+MissResponse | test_pipeline.py::test_clarify_not_converging_after_two_rounds_mines_candidate | integration | PASS |
| 10 | 统一信封契约;异常信封兜底;分隔符注入剥除;零 DB 凭据校验 | test_api.py + test_security.py | integration/unit | PASS |

## 覆盖率与已知缺口

- 最终:`pytest tests/ --cov=chatbi` → **94 passed, TOTAL 90%**(ruff/black 全过)
- 缺口:
  - `chatbi/planner/llm.py` 50% — AnthropicLlmClient 真实调用路径需 appkey,由 Task 0/6 覆盖
  - Task 0(模型对比评测)与 Task 6(服务级黄金集回归 58/58)待 appkey 配置后执行
  - chart/ChartSpec 属 M3;trace_id 回放属 M2

## 合并证据

分阶段提交链完整保留在本分支 feat/m1-chatbi-core(RED/GREEN 成对提交);
`poc/` 目录 git diff 为空(冻结承诺达成)。

## Task 6 服务级黄金集回归(2026-11-17 补录,appkey 已配置)

**命令**:`CHATBI_WREN_BIN=poc/.venv/bin/wren poc/.venv/bin/python eval/run_service_eval.py --tag m1-service-r4`
**最终结果(r4)**:**58/58 全对**,失败归因空,wall=158s

| 指标 | r4 实测 | 门槛 | 达标 |
|---|---|---|---|
| 全对条数 | 58/58 | 58/58 | ✅ |
| 工具选择/参数准确率 | 100%/100% | ≥90% | ✅ |
| 应未命中正确率(红线) | 100% | 100% | ✅ |
| 旁路正确率 | 100% | 100% | ✅ |
| 澄清触发率 | 100% | ≥95% | ✅ |
| 多轮继承正确率 | 100% | ≥85% | ✅ |
| P95 延迟 | 3753ms | ≤5000ms(含真实执行) | ✅ |
| 幻觉拦截(防线①②③) | 单测覆盖(test_core 三防线用例) | 100% 红线 | ✅(机制级) |

**修复轨迹(r1 55/58 → r4 58/58)**:
1. r1:Q27 时间槽位漂移 + C4 值筛选维度重复分组 → 引入 temperature=0 意图与 eq 筛选维度归一化
2. r2:0/58 — 实测 anthropic SDK 2.8.0 `Messages.create` 已移除 `temperature` 参数 → 全部调用秒败
3. 修复:按 SDK 签名自适应传参(9a7f865);新增 FR-B3 服务层兜底(in 筛选保留维度 7c2be09)
4. r4:58/58。**确定性结论**:本环境 SDK 不传 temperature,LLM 漂移由服务层确定性规则兜底
   (eq/in 归一化 + 裸指标时间兜底),不再依赖采样参数。

**Task 0 决策记录**:docs/decisions/2026-11-17-m1-q1-q2.md(Q1 沿用当前模型;Q2 内存+SQLite)。

## M1 验收清单终态

- [x] 黄金集 58/58 全对(服务级 r4)
- [x] 两条红线 100%(应未命中实测;幻觉拦截机制级单测)
- [x] 状态机全路径自动化用例(109 单测/集成)+ 服务级全链路
- [x] 澄清 ≤2 轮收敛,文案快照测试通过
- [x] Q1/Q2 决策定案并记录;Q3 留治理平台评审
- [x] NFR-2 注入用例 + 零凭据校验通过
- [x] pytest 覆盖率 ≥80%(90%),ruff/black 通过
- [x] poc/ 目录零修改(git diff 为空)
