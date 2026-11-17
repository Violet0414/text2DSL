<script lang="ts" setup>
/**
 * 单条消息渲染:按载荷四态 + 错误/加载态分发到对应组件。
 */
import type { UiMessage } from '../use-chat';

import { Alert } from 'ant-design-vue';

import AnswerCard from './answer-card.vue';
import ClarifyOptions from './clarify-options.vue';
import MissPanel from './miss-panel.vue';

defineProps<{ message: UiMessage }>();

defineEmits<{ select: [option: string] }>();

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
    class="mb-3 flex"
    :class="message.role === 'user' ? 'justify-end' : 'justify-start'"
  >
    <div class="max-w-[85%] min-w-0">
      <div
        v-if="message.role === 'user'"
        class="rounded-lg bg-blue-600 px-3 py-2 text-white"
      >
        {{ message.text }}
      </div>
      <template v-else>
        <div v-if="message.pending" class="py-2 text-sm text-gray-400">
          正在分析问题…
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
  </div>
</template>
