<script lang="ts" setup>
/**
 * 答案卡(W0):结果表格 + 口径五要素(FR-A2) + 查询参数可追溯。
 * 数据全部来自 payload,前端不计算口径。
 */
import type { AnswerCardData } from '#/api/chatbi/shared';

import { computed } from 'vue';

import {
  Alert,
  Collapse,
  CollapsePanel,
  Descriptions,
  DescriptionsItem,
  Tag,
} from 'ant-design-vue';

import {
  METRIC_META_FIELDS,
  missingMetricFields,
  roleLabel,
} from '#/api/chatbi/shared';

const props = defineProps<{ payload: AnswerCardData }>();

const tableColumns = computed(() =>
  props.payload.columns.map((col) => ({
    dataIndex: col,
    role: roleLabel(props.payload.roles?.[col]),
    title: col,
  })),
);

const tableData = computed(() =>
  props.payload.rows.map((row, idx) => ({ ...row, __key: idx })),
);

const missing = computed(() => missingMetricFields(props.payload.metric || {}));
</script>

<template>
  <div class="answer-card">
    <Alert
      v-if="payload.message"
      :message="payload.message"
      show-icon
      type="info"
      class="mb-2"
    />
    <a-table
      v-if="payload.rows.length > 0"
      :columns="tableColumns"
      :data-source="tableData"
      :pagination="{ pageSize: 10 }"
      :row-key="(r: Record<string, unknown>) => r.__key"
      size="small"
    >
      <template #headerCell="{ column }">
        <span>
          {{ column.title }}
          <Tag v-if="column.role" class="ml-1" style="font-size: 10px">
            {{ column.role }}
          </Tag>
        </span>
      </template>
    </a-table>
    <Alert
      v-else
      message="查询成功但没有数据"
      description="可尝试放宽时间范围或筛选条件"
      show-icon
      type="warning"
    />

    <Descriptions
      :column="1"
      bordered
      size="small"
      class="mt-3"
      title="口径出处（五要素）"
    >
      <DescriptionsItem
        v-for="f in METRIC_META_FIELDS"
        :key="f.key"
        :label="f.label"
      >
        {{ payload.metric?.[f.key] || '-' }}
      </DescriptionsItem>
    </Descriptions>
    <Alert
      v-if="missing.length > 0"
      :message="`口径元数据缺失: ${missing.join('、')}（缺陷,请反馈治理管理员）`"
      show-icon
      type="warning"
      class="mt-2"
    />

    <Collapse v-if="payload.cube_query" ghost class="mt-2">
      <CollapsePanel header="查看查询参数（cube query）" key="cq">
        <pre class="whitespace-pre-wrap break-all text-xs">{{
          JSON.stringify(payload.cube_query, null, 2)
        }}</pre>
      </CollapsePanel>
    </Collapse>
  </div>
</template>
