/**
 * ChatBI 业务请求封装:统一信封解包后的类型化 API。
 * 路径前缀 /api 由 VITE_GLOB_API_URL(apiURL)提供;dev 经 Vite proxy 转发 FastAPI。
 */

import { chatbiClient } from '#/api/request';

import type {
  ChatPayload,
  Envelope,
  HistoryMessage,
  SessionSummary,
} from './shared';
import { unwrapEnvelope } from './shared';

export interface AskPayloadData {
  payload: ChatPayload;
}

export async function ask(
  sessionId: string,
  question: string,
): Promise<{ payload: ChatPayload; traceId: string }> {
  const body = await chatbiClient.post<Envelope<{ type: string }>>(
    '/api/ask',
    { question, sessionId },
  );
  const data = unwrapEnvelope(body);
  return {
    payload: data as unknown as ChatPayload,
    traceId: body.meta?.traceId ?? '',
  };
}

export async function listSessions(): Promise<{
  sessions: SessionSummary[];
}> {
  const body = await chatbiClient.get<
    Envelope<{ sessions: SessionSummary[] }>
  >('/api/sessions');
  return unwrapEnvelope(body);
}

export async function sessionHistory(
  sessionId: string,
): Promise<{ messages: HistoryMessage[]; sessionId: string }> {
  const body = await chatbiClient.get<
    Envelope<{ messages: HistoryMessage[]; sessionId: string }>
  >(`/api/sessions/${encodeURIComponent(sessionId)}/history`);
  return unwrapEnvelope(body);
}
