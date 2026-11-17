/**
 * ChatBI 聊天页状态编排:发送/重置/会话切换,全部经 api/chatbi 类型化封装。
 * 纪律:前端零口径计算;错误不吞——ChatbiApiError 连同 traceId 展示给用户。
 */

import { ref } from 'vue';

import { ask, listSessions, sessionHistory } from '#/api/chatbi';
import type {
  ChatPayload,
  SessionSummary,
} from '#/api/chatbi/shared';
import { asPayload, ChatbiApiError } from '#/api/chatbi/shared';

export interface UiMessage {
  createdAt?: string;
  error?: string;
  id: string;
  payload?: ChatPayload;
  pending?: boolean;
  role: 'assistant' | 'user';
  text?: string;
  traceId?: string;
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

  async function askOnce(question: string): Promise<void> {
    pushMessage({ role: 'user', text: question });
    const pending = pushMessage({ pending: true, role: 'assistant' });
    loading.value = true;
    try {
      const { payload, traceId } = await ask(sessionId.value, question);
      replaceMessage(pending.id, { ...pending, payload, traceId });
    } catch (error) {
      const text =
        error instanceof ChatbiApiError
          ? `[${error.code}] ${error.message}${error.traceId ? ` (traceId: ${error.traceId})` : ''}`
          : `网络或服务异常: ${String(error)}`;
      replaceMessage(pending.id, { ...pending, error: text });
    } finally {
      loading.value = false;
    }
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
    messages.value = data.messages.map((m) => ({
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
    selectClarifyOption,
    sessions,
    sessionId,
    sessionsLoading,
  };
}
