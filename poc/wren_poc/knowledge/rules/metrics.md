# 指标口径规则(metrics)

## 口径规则

1. **销售额口径裁定**:系统同时定义了 `sales_amount`(不含税)与 `sales_amount_with_tax`(含税)两个 measure。当用户说"销售额/营收"且上下文未指明口径时,**必须发起澄清**,提供选项:[含税口径, 不含税口径],不得擅自选择。
2. 上下文指明"含税"时 → `sales_amount_with_tax`;指明"不含税"时 → `sales_amount`。
3. **客单价**固定不含税口径(`avg_order_value`),无歧义,不澄清。
4. **退款率**(`refund_rate`)= 已退款金额 / 总金额(不含税),无歧义,不澄清。
5. **订单量**(`order_count`)= COUNT(DISTINCT order_id),无歧义,不澄清。

## 时间默认与澄清规则

1. 用户给出任何时间表达(本月/上月/近7天/2025年10月…)→ 直接解析,不澄清时间。
2. **裸指标且无时间**:问句只有指标名、无维度分组/筛选/TopN/对比等修饰(如"订单量")→ **发起澄清**追问时间范围,选项:[本月, 上个月, 近7天, 今年, 全部时间]。
3. **有修饰则不澄清时间**:问句含维度分组、筛选、TopN、对比/趋势词,或为总览泛问句(如"营收情况""卖了多少""平均每单多少钱""退款情况怎么样")→ 时间缺失不澄清,默认按**全部时间**查询。
4. "全部时间"不算时间缺失:用户明说"全部/历史累计/至今"时直接查询。
5. 多轮对话中,当前问题未提时间时**继承上一轮的时间参数**(K3 多轮继承)。

## 未命中与旁路规则

1. 用户询问语义层未注册的指标(如库存周转率、利润率)→ **不得编造**,进入未命中说明分支:告知该指标未定义,并列出可查指标清单。
2. 用户询问语义层未注册的维度(如门店、客户)→ 同上,未命中说明。
3. 非问数意图(寒暄、建指标请求、天气等)→ 旁路到闲聊/引导回复,**不生成查询**。

## 查询构造规则

1. 所有问数必须基于 sales cube:`measures ⊆ {sales_amount, sales_amount_with_tax, order_count, avg_order_value, refund_rate}`;
2. `dimensions ⊆ {channel, region, category, order_status}`;
3. 时间统一走 `timeDimensions: [{dimension: order_date, granularity, dateRange}]`;
4. 维度筛选走 `filters`(operator 用 eq/in 等),不在 dimensions 里硬塞筛选值;
5. Top-N:dimensions + orderBy(measure desc) + limit N。

## 直查判定示例(few-shot,必须遵守)

- "卖了多少" → 直查 `order_count`,slot=all_time(泛问句总览,**不要**澄清时间)
- "营收情况" → 直查 `sales_amount`,slot=all_time
- "营收和订单量对比" → 直查两指标汇总(无维度分组),slot=all_time(**不要**因缺分组维度而澄清)
- "订单量" → 澄清时间(裸指标无修饰)
- "销售额" / "销售额怎么样" → 澄清口径(含税/不含税)
- "营收同比" / "营收环比" → 直查,slot=yoy / mom(系统自动展开当期+对比期两次查询,**不要**澄清对比周期)
- "本月各渠道营收" → 直查,slot=current_month,分组 channel
