/**
 * ChatBI 载荷契约与信封解包(纯函数,与后端 chatbi/answer.py 四态对齐)。
 * 纪律(W0):前端零口径计算——一切数据来自信封 payload,这里只做类型收窄与展示映射。
 */

export interface EnvelopeMeta {
  latencyMs: number;
  traceId: string;
}

export interface Envelope<T> {
  data: null | T;
  error: null | { code: string; message: string };
  meta: EnvelopeMeta;
  success: boolean;
}

/** 口径五要素(FR-A2):缺失任一项视为缺陷 */
export interface MetricMeta {
  definition?: string;
  freshness?: string;
  name?: string;
  owner?: string;
  version?: string;
  [key: string]: unknown;
}

/** 图表推荐条目(AnswerCard 附带,前端选择按钮数据源) */
export interface ChartOptionInfo {
  label: string;
  purpose: string;
  type: string;
}

export interface AnswerCardData {
  chart_options?: ChartOptionInfo[];
  columns: string[];
  cube_query: null | Record<string, unknown>;
  message: string;
  metric: MetricMeta;
  roles: Record<string, string>;
  rows: Record<string, unknown>[];
  type: 'answer';
}

export interface ClarifyData {
  clarify_step: string;
  options: string[];
  question_text: string;
  template_id: string;
  type: 'clarification';
}

export interface MissData {
  available_metrics: string[];
  candidate_id: string;
  message: string;
  type: 'miss';
}

export interface ReplyData {
  text: string;
  type: 'reply';
}

export interface ErrorData {
  message: string;
  rows: Record<string, unknown>[];
  type: 'error';
}

/** 报表载荷(chart_select 轮):与工作流 report_json 结构对齐 */
export interface ReportData {
  chart: {
    echarts_option: null | Record<string, unknown>;
    label: string;
    type: string;
  };
  insight: { core_data?: string; trend_analysis?: string };
  message: string;
  question: string;
  summary: string;
  type: 'report';
}

export type ChatPayload =
  | AnswerCardData
  | ClarifyData
  | MissData
  | ReplyData
  | ErrorData
  | ReportData;

/** 会话列表条目(GET /api/sessions,camelCase 信封) */
export interface SessionSummary {
  messageCount: number;
  sessionId: string;
  title: string;
  updatedAt: string;
}

/** 历史消息(GET /api/sessions/{id}/history) */
export interface HistoryMessage {
  createdAt: string;
  messageId: number;
  payload: ChatPayload & { text?: string };
  role: 'assistant' | 'user';
  traceId: string;
}

const PAYLOAD_TYPES: readonly string[] = [
  'answer',
  'clarification',
  'error',
  'miss',
  'reply',
  'report',
];

export function isPayloadType(value: unknown): value is ChatPayload['type'] {
  return typeof value === 'string' && PAYLOAD_TYPES.includes(value);
}

/** 类型收窄:unknown → ChatPayload(历史回放中 payload 来自 JSON) */
export function asPayload(value: unknown): ChatPayload & { text?: string } {
  if (
    value &&
    typeof value === 'object' &&
    isPayloadType((value as Record<string, unknown>).type)
  ) {
    return value as ChatPayload & { text?: string };
  }
  return { text: String(value ?? ''), type: 'reply' };
}

export class ChatbiApiError extends Error {
  code: string;
  traceId: string;

  constructor(message: string, code: string, traceId = '') {
    super(message);
    this.code = code;
    this.traceId = traceId;
  }
}

/** 信封解包:success=false 或 error 存在 → 抛 ChatbiApiError(错误分态由 UI 层处理) */
export function unwrapEnvelope<T>(body: Envelope<T>): T {
  if (body.success && body.data !== null) {
    return body.data;
  }
  const err = body.error ?? { code: 'UNKNOWN', message: '未知错误' };
  throw new ChatbiApiError(err.message, err.code, body.meta?.traceId ?? '');
}

/** 口径五要素齐备性(FR-A2 验收:缺失任一项视为缺陷,UI 显示补齐提示) */
export const METRIC_META_FIELDS = [
  { key: 'name', label: '指标名' },
  { key: 'definition', label: '口径定义' },
  { key: 'owner', label: '责任人' },
  { key: 'version', label: '版本' },
  { key: 'freshness', label: '数据新鲜度' },
] as const;

export function missingMetricFields(metric: MetricMeta): string[] {
  return METRIC_META_FIELDS.filter((f) => !metric[f.key]).map((f) => f.label);
}

/** 列角色 → 展示标签(数据来自 columns[].roles,前端不推导) */
const ROLE_LABELS: Record<string, string> = {
  dimension: '维度',
  measure: '指标',
  time: '时间',
};

export function roleLabel(role: undefined | string): string {
  return (role && ROLE_LABELS[role]) || '';
}
