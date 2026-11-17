import { describe, expect, it } from 'vitest';

import {
  asPayload,
  ChatbiApiError,
  isPayloadType,
  missingMetricFields,
  roleLabel,
  unwrapEnvelope,
} from './shared';

describe('unwrapEnvelope', () => {
  const okBody = {
    data: { type: 'reply', text: '你好' },
    error: null,
    meta: { traceId: 't1', latencyMs: 12 },
    success: true,
  };

  it('成功信封返回 data', () => {
    expect(unwrapEnvelope(okBody)).toEqual({ type: 'reply', text: '你好' });
  });

  it('失败信封抛 ChatbiApiError 且携带 code 与 traceId', () => {
    const body = {
      ...okBody,
      data: null,
      error: { code: 'LlmConfigError', message: 'LLM 未配置' },
      success: false,
    };
    try {
      unwrapEnvelope(body);
      expect.unreachable('应当抛出');
    } catch (e) {
      expect(e).toBeInstanceOf(ChatbiApiError);
      const err = e as ChatbiApiError;
      expect(err.code).toBe('LlmConfigError');
      expect(err.traceId).toBe('t1');
    }
  });

  it('success=true 但 data=null 视为错误(绝不渲染空结果)', () => {
    const body = { ...okBody, data: null };
    expect(() => unwrapEnvelope(body)).toThrow(ChatbiApiError);
  });
});

describe('payload 类型收窄', () => {
  it('isPayloadType 只认五态', () => {
    expect(isPayloadType('answer')).toBe(true);
    expect(isPayloadType('clarification')).toBe(true);
    expect(isPayloadType('miss')).toBe(true);
    expect(isPayloadType('reply')).toBe(true);
    expect(isPayloadType('error')).toBe(true);
    expect(isPayloadType('injected')).toBe(false);
    expect(isPayloadType(42)).toBe(false);
  });

  it('asPayload 收窄合法载荷', () => {
    const payload = asPayload({
      options: ['含税'],
      type: 'clarification',
    });
    expect(payload.type).toBe('clarification');
    expect((payload as any).options).toEqual(['含税']);
  });

  it('asPayload 非法形状回退为 reply 文本(不抛出,展示侧兜底)', () => {
    expect(asPayload('任意文本')).toEqual({ text: '任意文本', type: 'reply' });
    expect(asPayload(null)).toEqual({ text: '', type: 'reply' });
    expect(asPayload({ type: 'hack', evil: true })).toEqual({
      text: String({ type: 'hack', evil: true }),
      type: 'reply',
    });
  });
});

describe('口径五要素(FR-A2)', () => {
  it('五要素齐备无缺失', () => {
    const metric = {
      definition: 'sum(revenue)',
      freshness: 'T+1',
      name: '营收',
      owner: '数据组',
      version: 'v1.2',
    };
    expect(missingMetricFields(metric)).toEqual([]);
  });

  it('缺失项返回中文标签列表', () => {
    expect(missingMetricFields({ name: '营收' })).toEqual([
      '口径定义',
      '责任人',
      '版本',
      '数据新鲜度',
    ]);
    expect(missingMetricFields({})).toHaveLength(5);
  });
});

describe('roleLabel', () => {
  it('映射已知角色', () => {
    expect(roleLabel('measure')).toBe('指标');
    expect(roleLabel('dimension')).toBe('维度');
    expect(roleLabel('time')).toBe('时间');
  });

  it('未知/缺失角色返回空串', () => {
    expect(roleLabel('weird')).toBe('');
    expect(roleLabel(undefined)).toBe('');
  });
});
