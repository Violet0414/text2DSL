---
name: run-chatbi
description: 运行/启动/冒烟/截图 ChatBI 智能问数服务(FastAPI /api/ask)。当用户说"把项目跑起来"、"启动服务"、"演示问数"、"smoke test"时使用。驱动方式为后台 uvicorn + curl,无需浏览器。
---

# run-chatbi

ChatBI 受控问数服务:FastAPI 暴露 `POST /api/ask`(统一信封),内部链路
LLM 规划 → 治理门禁 → 时间缺省规则 → wren CLI 执行(duckdb) → 应答组装。
单进程服务,无浏览器界面;**驱动 = curl**。统一入口是本 skill 的
`smoke.sh`(自动启动→探活→跑 6 个 PRD 场景→输出摘要→自动停服)。

## Prerequisites

- 仓库根目录执行;Python venv 位于 `poc/.venv`(uv 管理,**未提交入 git**)。
- 本容器实测依赖版本:anthropic 2.8.0 / wrenai 0.18.0(wren CLI + wren_core-py 0.8.2)/
  fastapi 0.163.1 / uvicorn 0.54.0 / duckdb 2.0.0。
- 从零重建 venv 的安装行**未在本容器复验**(venv 已存在),仅备查:
  `uv venv poc/.venv && uv pip install --python poc/.venv/bin/python "wrenai[duckdb]" anthropic fastapi "uvicorn[standard]" httpx pytest`
- **LLM 凭据**(问数必需,冒烟的 LLM 场景依赖它):环境变量
  `ANTHROPIC_AUTH_TOKEN`(火山 codingPlan Bearer)**或** `ANTHROPIC_API_KEY`,
  以及 `ANTHROPIC_BASE_URL`。缺凭据时服务不崩——`/api/ask` 经信封返回
  `success:false, error.code=LlmConfigError`。
- wren 数据源:`~/.wren/profiles.yml` 指向 duckdb(本机已配 `pocduck`)。

## Run (agent path)

```bash
PORT=8301 bash .claude/skills/run-chatbi/smoke.sh
```

脚本做六件事:启动 uvicorn(仅绑 127.0.0.1)→ `/healthz` 探活(30s 超时)→
依次驱动 S1 直查 / S2 口径澄清 / S4 未命中红线 / S5 旁路 / S3 两轮多轮追问
→ 打印每场景摘要 → EXIT 时 kill 服务。全程真实 LLM 调用,约 40–90s。
服务日志:`/tmp/chatbi_smoke_$PORT.log`。

手动交互(服务已在跑时):

```bash
curl -s -X POST http://127.0.0.1:8300/api/ask -H 'Content-Type: application/json' \
  -d '{"sessionId": "t1", "question": "上个月各渠道营收"}'
```

同一 `sessionId` 连续发问即多轮(`华南区呢` 继承时间并替换 region 筛选;
`重新问` 清空上下文)。改数据模型/门禁后重启服务生效(门禁文件
`chatbi/gate_config.json` 每请求实时读,无需重启)。

## Direct invocation(不经服务测内部逻辑)

```bash
poc/.venv/bin/python -m pytest tests/ -q                    # 111 用例,LLM 全 Fake
CHATBI_WREN_BIN=$PWD/poc/.venv/bin/wren poc/.venv/bin/python \
  eval/run_service_eval.py --limit 4 --tag smoke            # 黄金集抽样(真 LLM)
```

## Run (human path)

`poc/.venv/bin/python -m uvicorn chatbi.api:app --port 8300` 后浏览器打开
仅能看到 Swagger `/docs`;对话界面属后续里程碑,尚不存在。

## Gotchas(实测踩坑)

- **wren 不在 PATH**:CLI 装在 `poc/.venv/bin/wren`;本 skill 的 smoke.sh 已设
  `CHATBI_WREN_BIN`,手动起服时必须带该变量,否则执行层报
  `FileNotFoundError: 'wren'`。
- **wren CLI 必须在 wren 项目目录运行**(否则 `no wren project found`);
  executor 已默认以 `poc/wren_poc` 为 cwd,自建 executor 时记得传 `cwd`。
- **anthropic SDK 2.8.0 的 `Messages.create` 没有 `temperature` 参数**
  (签名自适应已内置);手动加该参数会秒级全败,表现为所有请求
  `TypeError: ... unexpected keyword argument 'temperature'`。
- **凭据双通道**:火山 codingPlan 用 `ANTHROPIC_AUTH_TOKEN`(Bearer),
  标准 Anthropic 用 `ANTHROPIC_API_KEY`(x-api-key);`LlmConfig.from_env`
  两者都读,`ANTHROPIC_API_KEY` 优先。
- **信封字段命名不一致**(已知待修):输入 `sessionId` 为 camelCase,
  输出数据体为 snake_case(`clarify_step`/`template_id`/`candidate_id`)。
- 运行时在 cwd 生成 `chatbi_sessions.db`(SQLite 会话库,已 gitignore);
  删掉即重置全部会话。

## Troubleshooting

| 症状 | 处置 |
|---|---|
| `FileNotFoundError: 'wren'` | 设 `CHATBI_WREN_BIN=$PWD/poc/.venv/bin/wren` |
| 信封 `error.code=LlmConfigError` | 配置 `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_BASE_URL` |
| 全部请求秒败 + `unexpected keyword argument` | SDK 兼容问题,检查 llm.py 是否被手改注入 temperature |
| `no wren project found` | executor cwd 被改;应指向含 `wren_project.yml` 的目录 |
| 服务 30s 未就绪 | 看 `/tmp/chatbi_smoke_$PORT.log` 常见为端口占用,换 `PORT=` |
