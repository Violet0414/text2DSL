<script lang="ts" setup>
/**
 * 澄清卡(FR-B):模板文案 + 选项按钮,点击选项即作为下一轮提问发送。
 */
import type { ClarifyData } from '#/api/chatbi/shared';

import { Button, Card, Tag } from 'ant-design-vue';

defineProps<{ payload: ClarifyData }>();

defineEmits<{ select: [option: string] }>();

const STEP_LABELS: Record<string, string> = {
  dimension: '维度值',
  tax: '口径',
  time: '时间',
};
</script>

<template>
  <Card size="small" class="clarify-card">
    <template #title>
      <span>
        需要澄清（
        <Tag color="blue">{{ STEP_LABELS[payload.clarify_step] || '待确认' }}</Tag>
        ）
      </span>
    </template>
    <p class="mb-3 whitespace-pre-wrap">{{ payload.question_text }}</p>
    <div class="flex flex-wrap gap-2">
      <Button
        v-for="opt in payload.options"
        :key="opt"
        type="primary"
        ghost
        @click="$emit('select', opt)"
      >
        {{ opt }}
      </Button>
    </div>
  </Card>
</template>
