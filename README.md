# text2DSL — ChatBI 受控问数服务

自然语言 → 受控 DSL(cube query)→ SQL 的智能问数(ChatBI)服务。核心理念:
**答案永远带口径出处,未定义指标绝不给数**——LLM 只在语义层定义的指标/维度
空间内做规划,输出受治理约束的 `cube_query`,由确定性引擎编译执行,杜绝"自由
生成 SQL"带来的口径漂移与幻觉数据。

- 后端:**FastAPI** 单服务(`POST /api/ask` 统一信封),同时托管前端静态资源
- 前端:**Vue 3 + vue-vben-admin 5.x** 聊天式问数工作台(同仓 monorepo)
- 语义层:**Wren Engine**(wrenai 0.18.0)+ DuckDB

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 后端框架 | Python 3.12 · FastAPI 0.163 · uvicorn | 单进程;统一信封 `{success,data,error,meta}` |
| LLM | anthropic SDK 2.8(Anthropic 兼容网关) | 规划模型 `deepseek-v4.1-flash`(火山 codingPlan;`CHATBI_LLM_MODEL` 可换模型,零代码改动) |
| 语义层 | wrenai 0.18.0(wren CLI + wren_core-py 0.8.2) | MDL 建模;cube_query → SQL 确定性编译 |
| 执行引擎 | DuckDB 2.0 | 嵌入式分析库,零运维 |
| 会话存储 | SQLite(默认)/ 内存 | Repository 协议双实现,平替 Redis 只换装配 |
| 前端 | Vue 3 · vue-vben-admin 5.x · Ant Design Vue · ECharts | monorepo(`web/`),pnpm ≥11 · Vite |
| 测试 | pytest(154 用例,LLM 全 Fake)+ 黄金集评测(58 题,真 LLM) | 单测 + 服务级评测双轨 |

## textDSL 语义层架构

语义层以 Wren 项目(`poc/wren_poc/`)为载体,分四层收敛,最终落成一份
**MDL JSON**(`target/mdl.json`)供规划器消费:

```
poc/wren_poc/
├── data/                  # DuckDB 源数据(sales.duckdb)
├── models/orders/         # 物理模型:表引用、列、类型(直连 data source)
├── cubes/sales/           # 受控指标层(语义层核心):
│   └── metadata.yml       #   measures(SUM/COUNT 等口径表达式 + 同义词)
│                          #   dimensions(渠道/区域/类目…)、time_dimensions
├── relationships.yml      # 模型间关系(join 语义)
└── target/mdl.json        # wren 编译产物 = text2DSL 的"DSL 词表"
```

**cube 是唯一合法的问数词表**:每个 measure 携带口径描述与同义词(如
`sales_amount`="销售额(不含税)"与 `sales_amount_with_tax`="含税口径"并存,
正是用于验证口径歧义澄清的场景)。规划器只允许把用户问题翻译成对 cube 成员
的引用,不允许发明新字段。

## 请求链路(一次提问的生命周期)

```
用户提问 → 前端(零口径计算,纯展示)
  └→ POST /api/ask(FastAPI 统一信封 + 会话鉴权)
       └→ ChatPipeline
            1. LLM 规划(chatbi/planner):工具强制结构化输出 behavior + cube_query;
               JSON 修复回退;失败重试 1 次;多轮历史作为对话上下文继承时间/筛选
            2. 治理门禁(chatbi/gate + gate_config.json):未 confirmed 的指标
               不得出数(试运行/灰度状态管理,每请求实时读取)
            3. 时间缺省规则(chatbi/time_rules + planner/time_expand):
               "上个月/最近三个月"确定性展开为左闭右开 dateRange,无 LLM 参与
            4. wren CLI 执行(chatbi/executor):cube_query → SQL(wren_core 编译)
               → DuckDB;语义校验失败兜底降级为澄清,绝不裸奔出数
            5. 应答组装(chatbi/answer):六态载荷
               AnswerCard(表格 + 口径五要素 + 图表推荐)/ Clarification /
               Miss(未定义指标 → 进指标需求池)/ Reply / Report / Error
```

图表链路为「规则推荐 + 服务端拼 ECharts option + LLM 只写解读」三段式
(`chatbi/charting.py` 确定性打分、`chatbi/insight.py` 单次解读调用且严禁
编造合计/同比,失败优雅降级为空解读)。

## 目录结构

```
chatbi/            # 后端服务(api/pipeline/planner/gate/executor/charting/insight/...)
chatbi/store/      # SessionRepository/MiningRepository:memory + sqlite 双实现
web/               # 前端 monorepo(vue-vben-admin 5.x,apps/web-antd)
  └─ src/views/chatbi/   # 聊天问数页(答案卡/报表卡/澄清/未命中面板/会话侧栏)
poc/wren_poc/      # Wren 语义层项目(cubes/models/data + mdl.json)
poc/eval/          # 黄金集评测(run_eval.py + judge.py + golden_questions.jsonl)
eval/              # 服务级评测(run_service_eval.py,走真实 HTTP 链路)
tests/unit/        # pytest 单测(LLM 全 Fake 注入,154 用例)
docs/decisions/    # 关键决策记录(模型选型/存储选型)
.claude/skills/run-chatbi/  # 一键冒烟:启动→探活→6 场景→自动停服
```

## 快速开始

### 后端

```bash
# venv(uv 管理)
uv venv poc/.venv && uv pip install --python poc/.venv/bin/python \
  "wrenai[duckdb]" anthropic fastapi "uvicorn[standard]" httpx pytest

# 环境变量(LLM 凭据二选一;缺凭据服务不崩,经信封返回 LlmConfigError)
export ANTHROPIC_BASE_URL=<网关地址>
export ANTHROPIC_AUTH_TOKEN=<Bearer 凭据>   # 或 ANTHROPIC_API_KEY
# 可选:CHATBI_LLM_MODEL(默认 deepseek-v4.1-flash)
#      CHATBI_ADMIN_PASSWORD(登录口令,未设则回退开发默认 chatbi-dev)

# 启动(wren CLI 不在 PATH,必须显式指定)
CHATBI_WREN_BIN=$PWD/poc/.venv/bin/wren \
  poc/.venv/bin/python -m uvicorn chatbi.api:app --port 8000
```

### 前端(开发态)

```bash
cd web && pnpm install && pnpm dev:antd   # http://localhost:5666,/api 已代理 :8000
```

登录:用户名 `chatbi`,口令取 `CHATBI_ADMIN_PASSWORD`(开发默认 `chatbi-dev`)。

### 前端(生产态,单服务)

```bash
cd web && pnpm build:antd                 # 产物 web/apps/web-antd/dist
# FastAPI 检测到 dist 自动托管,打开 http://localhost:8000
```

### 一键冒烟(启动→探活→6 个 PRD 场景→自动停服)

```bash
PORT=8301 bash .claude/skills/run-chatbi/smoke.sh
```

## 测试与评测

```bash
poc/.venv/bin/python -m pytest tests/ -q        # 154 用例,LLM 全 Fake,秒级

# 黄金集抽样(真 LLM):PRD 58 题基线 PoC 58/58 达标
CHATBI_WREN_BIN=$PWD/poc/.venv/bin/wren poc/.venv/bin/python \
  eval/run_service_eval.py --limit 4 --tag smoke
```

## 关键设计纪律

- **受控问数**:LLM 只产出对语义层词表的引用,SQL 由 wren_core 确定性编译,
  治理门禁未放行的指标一律不出数
- **前端零口径计算**:一切数据来自后端信封载荷,前端只做类型收窄与展示
- **状态外置**:会话/指标需求池经 Repository 协议,内存/SQLite(平替 Redis)
- **可回放**:每轮应答带 `traceId` + LLM 调用快照,黄金集可复现评测
- **信封统一**:业务端点 `{success,data,error,meta}`;鉴权端点走 vben 契约,
  两套格式是显式边界

## 里程碑

- ✅ **PoC**:58 题黄金集 58/58,验证受控问数全链路可行(2026-11-16)
- ✅ **M1 + W0**:后端工程化(Repository/门禁/多轮/降级)+ Web 前端 v0(2026-11-17)
- ✅ **报表卡**:图表推荐/AI 解读/chart_select 直出 + 聊天窗口体验优化(2026-11-20)
- ⏭ **M2**:进行中
