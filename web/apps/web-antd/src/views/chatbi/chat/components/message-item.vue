<script lang="ts" setup>
/**
 * 单条消息渲染:按载荷四态 + 错误/加载态分发到对应组件。
 * 呈现层优化:用户/助手头像与气泡分区,pending 态带旋转指示与自定义文案。
 */
import type { UiMessage } from '../use-chat';

import type { ChartOptionInfo } from '#/api/chatbi/shared';

import { LoaderCircle, MessageSquareCode } from '@vben/icons';
import { Alert } from 'ant-design-vue';

import AnswerCard from './answer-card.vue';
import ClarifyOptions from './clarify-options.vue';
import MissPanel from './miss-panel.vue';
import ReportCard from './report-card.vue';

defineProps<{ isLatestAnswer?: boolean; message: UiMessage }>();

defineEmits<{
  select: [option: string];
  'chart-select': [chart: ChartOptionInfo];
}>();

function payloadText(payload: unknown): string {
  const p = payload as { message?: string; text?: string };
  return p?.text || p?.message || '';
}
function payloadType(payload: unknown): 'error' | 'success' {
  const p = payload as { type?: string };
  return p?.type === 'error' ? 'error' : 'success';
}
</script>

<template>
  <div
    class="mb-4 flex items-start gap-2"
    :class="message.role === 'user' ? 'justify-end' : 'justify-start'"
  >
    <!-- 助手头像 -->
    <div
      v-if="message.role !== 'user'"
      class="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full border bg-white shadow-sm"
    >
      <MessageSquareCode class="size-4 text-blue-600" />
    </div>

    <div class="max-w-[78%] min-w-0">
      <!-- 用户气泡:蓝色渐变,右上直角收口 -->
      <div
        v-if="message.role === 'user'"
        class="rounded-2xl rounded-tr-sm bg-gradient-to-br from-blue-500 to-blue-600 px-4 py-2 text-white shadow-sm"
      >
        {{ message.text }}
      </div>
      <template v-else>
        <div
          v-if="message.pending"
          class="flex items-center gap-2 py-2 text-sm text-gray-400"
        >
          <LoaderCircle class="size-4 animate-spin text-blue-500" />
          {{ message.pendingLabel || '正在分析问题…' }}
        </div>
        <Alert
          v-else-if="message.error"
          :message="message.error"
          type="error"
          show-icon
          class="whitespace-pre-wrap"
        />
        <template v-else-if="message.payload">
          <AnswerCard
            v-if="message.payload.type === 'answer'"
            :is-latest="isLatestAnswer"
            :payload="message.payload"
            @chart-select="$emit('chart-select', $event)"
            @select="$emit('select', $event)"
          />
          <ReportCard
            v-else-if="message.payload.type === 'report'"
            :payload="message.payload"
          />
          <ClarifyOptions
            v-else-if="message.payload.type === 'clarification'"
            :payload="message.payload"
            @select="$emit('select', $event)"
          />
          <MissPanel
            v-else-if="message.payload.type === 'miss'"
            :payload="message.payload"
          />
          <Alert
            v-else
            :message="payloadText(message.payload)"
            :type="payloadType(message.payload)"
            show-icon
          />
        </template>
      </template>
    </div>

    <!-- 用户头像 -->
    <div
      v-if="message.role === 'user'"
      class="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-blue-600 text-xs font-medium text-white shadow-sm"
    >
      我
    </div>
  </div>
</template>
