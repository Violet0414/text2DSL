/**
 * ChatBI 聊天页状态编排:发送/重置/会话切换,全部经 api/chatbi 类型化封装。
 * 纪律:前端零口径计算;错误不吞——ChatbiApiError 连同 traceId 展示给用户。
 */

import { ref } from 'vue';

import { ask, deleteSession, listSessions, sessionHistory } from '#/api/chatbi';
import type {
  ChartOptionInfo,
  ChatPayload,
  SessionSummary,
} from '#/api/chatbi/shared';
import { asPayload, ChatbiApiError } from '#/api/chatbi/shared';

export interface UiMessage {
  createdAt?: string;
  error?: string;
  id: string;
  payload?: ChatPayload;
  /** 加载态提示文案(如"正在生成柱状图…"),缺省为通用文案 */
  pendingLabel?: string;
  pending?: boolean;
  role: 'assistant' | 'user';
  text?: string;
  traceId?: string;
}

/** 判断用户消息是否为图表选择 JSON(前端按钮约定,呈现层不展示原始 JSON) */
function isChartSelectText(text: undefined | string): boolean {
  if (!text) return false;
  try {
    const obj = JSON.parse(text) as Record<string, unknown>;
    return obj.action === 'chart_select';
  } catch {
    return false;
  }
}

const seq = { value: 0 };

function nextId(): string {
  seq.value += 1;
  return `m${seq.value}`;
}

export function newSessionId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `s-${Date.now()}-${seq.value}`;
}

export function useChat() {
  const sessionId = ref(newSessionId());
  const messages = ref<UiMessage[]>([]);
  const loading = ref(false);
  const sessions = ref<SessionSummary[]>([]);
  const sessionsLoading = ref(false);

  function pushMessage(msg: Omit<UiMessage, 'id'>): UiMessage {
    const full: UiMessage = { ...msg, id: nextId() };
    messages.value = [...messages.value, full];
    return full;
  }

  function replaceMessage(id: string, updated: UiMessage): void {
    const idx = messages.value.findIndex((m) => m.id === id);
    if (idx >= 0) {
      const next = [...messages.value];
      next[idx] = updated;
      messages.value = next;
    }
  }

  /** 公共请求通道:push pending → 请求 → 原位替换为载荷或错误 */
  async function runAsk(
    pending: UiMessage,
    question: string,
  ): Promise<void> {
    loading.value = true;
    try {
      const { payload, traceId } = await ask(sessionId.value, question);
      replaceMessage(pending.id, { ...pending, pending: false, payload, traceId });
    } catch (error) {
      const text =
        error instanceof ChatbiApiError
          ? `[${error.code}] ${error.message}${error.traceId ? ` (traceId: ${error.traceId})` : ''}`
          : `网络或服务异常: ${String(error)}`;
      replaceMessage(pending.id, { ...pending, pending: false, error: text });
    } finally {
      loading.value = false;
    }
  }

  async function askOnce(question: string): Promise<void> {
    pushMessage({ role: 'user', text: question });
    const pending = pushMessage({ pending: true, role: 'assistant' });
    await runAsk(pending, question);
  }

  /**
   * 图表直出(R2):点图表按钮后不在聊天流渲染 chart_select JSON 用户消息,
   * 直接进入生成态;wire 契约不变——JSON 仍经同一条 /api/ask 发给后端。
   */
  async function requestChart(chart: ChartOptionInfo): Promise<void> {
    const pending = pushMessage({
      pending: true,
      pendingLabel: `正在生成${chart.label}…`,
      role: 'assistant',
    });
    await runAsk(
      pending,
      JSON.stringify({ action: 'chart_select', chart_type: chart.type }),
    );
  }

  async function loadSessions(): Promise<void> {
    sessionsLoading.value = true;
    try {
      const data = await listSessions();
      sessions.value = data.sessions;
    } catch {
      sessions.value = [];
    } finally {
      sessionsLoading.value = false;
    }
  }

  async function openSession(summary: SessionSummary): Promise<void> {
    const data = await sessionHistory(summary.sessionId);
    sessionId.value = summary.sessionId;
    // 图表选择 JSON 不回放(R2):报表卡已带问题上下文,原始 JSON 属呈现噪音
    messages.value = data.messages
      .filter(
        (m) =>
          !(
            m.role === 'user' &&
            isChartSelectText(m.role === 'user' ? m.payload.text : undefined)
          ),
      )
      .map((m) => ({
      createdAt: m.createdAt,
      id: `h${m.messageId}`,
      payload: m.role === 'assistant' ? asPayload(m.payload) : undefined,
      role: m.role,
      text: m.role === 'user' ? m.payload.text : undefined,
      traceId: m.traceId,
    }));
  }

  function selectClarifyOption(option: string): void {
    void askOnce(option);
  }

  async function removeSession(summary: SessionSummary): Promise<void> {
    await deleteSession(summary.sessionId);
    if (sessionId.value === summary.sessionId) {
      // 删除的是当前激活会话 → 清空消息区并切换全新会话
      sessionId.value = newSessionId();
      messages.value = [];
    }
    await loadSessions();
  }

  return {
    askOnce,
    loadSessions,
    messages,
    loading,
    newSession: (): void => {
      sessionId.value = newSessionId();
      messages.value = [];
    },
    openSession,
    removeSession,
    requestChart,
    selectClarifyOption,
    sessions,
    sessionId,
    sessionsLoading,
  };
}
