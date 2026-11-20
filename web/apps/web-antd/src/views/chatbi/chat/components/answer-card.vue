<script lang="ts" setup>
/**
 * 答案卡(W0):结果表格 + 口径五要素(FR-A2) + 查询参数可追溯。
 * 数据全部来自 payload,前端不计算口径。
 * 呈现层:图表按钮带类型色点;role Tag 按维度/指标/时间配色;口径区收紧间距。
 */
import type { AnswerCardData, ChartOptionInfo } from '#/api/chatbi/shared';

import { computed } from 'vue';

import {
  Alert,
  Button,
  Collapse,
  CollapsePanel,
  Descriptions,
  DescriptionsItem,
  Tag,
  Tooltip,
} from 'ant-design-vue';

import {
  METRIC_META_FIELDS,
  missingMetricFields,
  roleLabel,
} from '#/api/chatbi/shared';

const props = defineProps<{ isLatest?: boolean; payload: AnswerCardData }>();

const emit = defineEmits<{ 'chart-select': [chart: ChartOptionInfo] }>();

function selectChart(chart: ChartOptionInfo): void {
  // 图表直出(R2):上抛类型对象,由 use-chat.requestChart 组装 wire JSON,不渲染原始 JSON
  emit('chart-select', chart);
}

/** 列角色 → Tag 配色(维度/指标/时间三色区分) */
const ROLE_TAG_COLOR: Record<string, string> = {
  dimension: 'geekblue',
  measure: 'green',
  time: 'volcano',
};

/** 图表类型 → 按钮色点(与 report-card 徽标一致) */
const CHART_DOT: Record<string, string> = {
  bar: 'bg-blue-500',
  line: 'bg-emerald-500',
  pie: 'bg-amber-500',
};

const tableColumns = computed(() =>
  props.payload.columns.map((col) => ({
    dataIndex: col,
    role: roleLabel(props.payload.roles?.[col]),
    roleKey: props.payload.roles?.[col],
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
      class="rounded-lg border"
    >
      <template #headerCell="{ column }">
        <span>
          {{ column.title }}
          <Tag
            v-if="column.role"
            class="ml-1"
            :color="ROLE_TAG_COLOR[column.roleKey] || 'default'"
            style="font-size: 10px"
          >
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

    <div
      v-if="isLatest && payload.chart_options && payload.chart_options.length > 0"
      class="mt-3 flex flex-wrap items-center gap-2"
    >
      <span class="text-xs text-gray-500">生成图表:</span>
      <Tooltip
        v-for="opt in payload.chart_options"
        :key="opt.type"
        :title="opt.purpose"
      >
        <Button size="small" class="flex items-center gap-1.5" @click="selectChart(opt)">
          <span
            class="size-2 rounded-full"
            :class="CHART_DOT[opt.type] || 'bg-gray-400'"
          />
          {{ opt.label }}
        </Button>
      </Tooltip>
    </div>

    <Descriptions
      :column="1"
      bordered
      size="small"
      class="mt-3 [&_.ant-descriptions-item-label]:w-24 [&_.ant-descriptions-title]:mb-1 [&_.ant-descriptions-title]:text-sm"
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
