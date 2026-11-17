"""受控问数规划器:NL → 行为分支 + cube query 结构化参数。

自 poc/planner 演进,行为契约与 PoC一致;差异:
- LLM 客户端经 LlmClient Protocol 注入(测试用 Fake,生产用 AnthropicLlmClient,appkey 后期填)
- 修复成功路径 validation 状态为 repaired
"""
