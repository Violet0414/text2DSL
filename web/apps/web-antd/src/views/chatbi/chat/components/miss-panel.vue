<script lang="ts" setup>
/**
 * 未命中卡(FR-D2 红线的界面呈现):明确回复 + 可查指标清单 + 挖掘候选提示。
 */
import type { MissData } from '#/api/chatbi/shared';

import { Alert, Card, Tag } from 'ant-design-vue';

defineProps<{ payload: MissData }>();
</script>

<template>
  <Card size="small">
    <template #title>
      <span>未找到已定义指标</span>
    </template>
    <Alert :message="payload.message" show-icon type="warning" class="mb-2" />
    <p v-if="payload.available_metrics.length > 0" class="mb-1">
      当前可查指标：
    </p>
    <div v-if="payload.available_metrics.length > 0" class="flex flex-wrap gap-1">
      <Tag v-for="m in payload.available_metrics" :key="m" color="blue">
        {{ m }}
      </Tag>
      <Tag v-if="payload.candidate_id" color="purple">
        需求已记录为挖掘候选（{{ payload.candidate_id }})
      </Tag>
      <Tag v-else color="purple">需求已记录为挖掘候选</Tag>
    </div>
    <p v-else class="text-sm text-gray-500">
      暂无已启用的指标,请联系语义治理管理员。
    </p>
  </Card>
</template>
