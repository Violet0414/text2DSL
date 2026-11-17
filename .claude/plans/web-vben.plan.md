# Plan: text2DSL 前端（vben5 ChatBI 产品层 v0）

**Source PRD**: .claude/prds/smart-bi.prd.md
**Selected Milestone**: Web 前端 v0（横跨 M2 会话 UI / 预留 M3 图表 / M4 治理后台壳）
**Complexity**: MEDIUM

## Summary

以 vue-vben-admin 5.x（apps/web-antd）为骨架，在现有 FastAPI 后端之上同仓开发前端 `web/`。
本期交付：聊天问数核心 UI（S1–S6 呈现，四态载荷渲染、表格形态）+ 会话列表与历史回看（FR-C5）
+ 最小登录适配；图表留 M3 接 ChartSpec。

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| API 信封 | `chatbi/api.py:61-90` | `{success, data, error{code,message}, meta{traceId,latencyMs}}` |
| 载荷四态 | `chatbi/answer.py:12-44` | AnswerCard/ClarifyPayload/MissPayload/ReplyPayload camelCase 字段即 TS 契约 |
| Errors | `chatbi/api.py:72-79` | 信封兜底不裸奔，前端按 error.code 分态 |
| Tests | `tests/`（pytest） | 后端 pytest 先行（TDD）；前端 vitest 测 API 适配层 |
| 前端骨架 | 无既有模式 | 引入 vben5（MIT，保留 LICENSE），非本仓发明 |

## Files to Change

| File | Action | Why |
|---|---|---|
| `web/`（vben5 monorepo，裁剪） | CREATE | 前端骨架 |
| `chatbi/store/sqlite.py` | UPDATE | 新增消息表（全量历史，区别于最近 5 轮上下文摘要） |
| `chatbi/pipeline.py` | UPDATE | ask 落库同步写消息记录 |
| `chatbi/api.py` | UPDATE | GET /api/sessions、GET /api/sessions/{id}/history、vben 登录契约端点（口令走环境变量） |
| `tests/test_api_sessions.py` | CREATE | 新端点测试（TDD RED→GREEN） |
| `web/apps/web-antd/src/api/chatbi/` | CREATE | 四态载荷 TS 类型 + 信封解包请求封装 |
| `web/apps/web-antd/src/views/chatbi/` | CREATE | 聊天消息流、AnswerCard 口径五要素卡、澄清选项、未命中清单、降级四态、重新问 |
| `.gitignore` | UPDATE | 忽略 web/node_modules 与 dist |

## Tasks

### Task 1: vben5 引入与裁剪
- **Action**: clone（GitHub 失败改 gitee 镜像）；保留 apps/web-antd + packages；删 web-ele/web-naive/playground/backend-mock；pnpm install（registry=npmmirror）
- **Validate**: `pnpm dev:antd` 可启动

### Task 2: 后端最小增量（TDD）
- **Action**: 消息表 + 会话列表/历史端点 + vben 登录适配（/auth/login、/user/info、/auth/codes）
- **Validate**: `pytest`（新增 tests/test_api_sessions.py RED→GREEN）

### Task 3: 聊天问数核心页面
- **Action**: API 适配层 + 消息流 + AnswerCard（表格 + 口径五要素）+ 澄清选项 + 未命中清单 + 降级四态 + 重新问
- **Validate**: `pnpm vitest run` + 冒烟走查 S1/S2/S4/S5

### Task 4: 会话列表与历史回看
- **Action**: 左侧会话列表 + history 回放 + traceId 展示
- **Validate**: 冒烟走查会话切换与回看

### Task 5: 构建与交付
- **Action**: Vite proxy /api→localhost:8000；FastAPI StaticFiles 托管 dist + SPA fallback；run-chatbi skill 补冒烟步骤
- **Validate**: `pnpm build` + uvicorn 单服务页面可用

## Validation

```bash
pytest
cd web && pnpm install && pnpm build && pnpm vitest run
# 冒烟：S1 直查、S2 澄清、S4 未命中、S5 旁路、会话回看
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| R1 GitHub 网络受限 | 高 | gitee 镜像 + npmmirror registry |
| R2 vben 登录契约需按实际代码对齐 | 中 | clone 后读实际请求字段再实现端点 |
| R3 全量历史需新消息表（现仅存 5 轮摘要） | 中 | Phase 1 建表，pipeline 落库点集中 |
| R4 monorepo 体积 | 低 | 裁剪 + .gitignore |
| R5 前端自造数字风险 | 低 | 数据全部来自信封 payload，前端零计算 |

## Acceptance

- [x] All tasks complete（2026-11-17:Task1–5 全部完成,分支 feat/web-vben-ui）
- [x] Validation passes（pytest 127 全绿;vitest 10/10;pnpm build 11/11;六场景冒烟全过;静态托管+登录+会话列表+历史回放 curl 验证通过）
- [x] Patterns mirrored（新端点走统一信封;前端零口径计算;vben 契约端点为显式边界）
- [ ] 浏览器人工走查（待用户:pnpm build:antd 后单服务打开 http://localhost:8000,账号 chatbi/CHATBI_ADMIN_PASSWORD 或默认 chatbi-dev）
