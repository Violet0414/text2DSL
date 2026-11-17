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

## Web 前端(W0,vben5)

前端位于 `web/`(vue-vben-admin 5.x monorepo,apps/web-antd),与后端同仓。
pnpm 需 ≥11(`corepack enable && corepack prepare pnpm@11.16.0 --activate`,
本机 Node 22.23 满足 engines)。

### 开发态(两个终端)

```bash
# 终端 1:FastAPI(必须设 wren 路径)
CHATBI_WREN_BIN=$PWD/poc/.venv/bin/wren poc/.venv/bin/python -m uvicorn chatbi.api:app --port 8000
# 终端 2:vite dev server(5666,/api 已代理到 :8000)
cd web && pnpm dev:antd   # 浏览器 http://localhost:5666
```

登录:用户名 `chatbi`,口令取环境变量 `CHATBI_ADMIN_PASSWORD`,
未设置时回退开发默认 `chatbi-dev`(仅限本地;生产必须显式设置)。

### 生产态(单服务)

```bash
cd web && pnpm build:antd   # 产物 web/apps/web-antd/dist
CHATBI_WREN_BIN=$PWD/poc/.venv/bin/wren poc/.venv/bin/python -m uvicorn chatbi.api:app --port 8000
# FastAPI 检测到 dist 目录自动 StaticFiles 托管(hash 路由,无需 SPA fallback),打开 http://localhost:8000
```

### 前端 Gotchas(实测)

- web/ 内已移除 vben 的 `.git`(随主仓管理)与 lefthook `prepare` 脚本
  (否则 install 时 lefthook 会污染主仓 .git/hooks)。
- chatbi 业务端点走统一信封 `{success,data,error,meta}`,前端用
  `chatbiClient`(responseReturn 'body')自解包;vben 鉴权端点走 vben 契约
  `{code,data,errorMessage}`,两套格式是显式边界,勿混用。
- `.env.development` 已设 `VITE_NITRO_MOCK=false`(真实后端);
  生产 apiURL 为同源 `/api`。
- **vue-router 双实例白屏(已修,勿回退)**:登录后 BasicLayout 白屏报
  `Cannot read properties of undefined (reading 'beforeEach')`,根因是
  pnpm 按 rolldown peer 上下文拆出两份 vue-router(注入 Symbol key 不匹配,
  布局侧 useRouter() 恒 undefined)。已用 `web/pnpm-workspace.yaml`
  overrides 钉死 `rolldown: 1.2.19` + `vue-router: 5.2.0` 根治。
  判别方法:`ls web/apps/web-antd/dist/js | grep -c useApi` 应为 1;
  `readlink web/apps/web-antd/node_modules/vue-router` 与
  `web/packages/effects/layouts/node_modules/vue-router` 必须同源。
  .pnpm 下同名多目录可能是历史残留,以 `pnpm why <pkg>` 为准。
