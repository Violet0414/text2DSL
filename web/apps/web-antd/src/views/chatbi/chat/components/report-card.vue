<script lang="ts" setup>
/**
 * 报表卡(chart_select 轮):ECharts 图表(服务端 option 直渲染)
 * + 自然语言 summary + AI 解读(core_data)/趋势分析(trend_analysis)。
 * 数据全部来自 payload,前端零口径计算。
 * 布局:图表主视觉置顶,解读区按分块卡片呈现;图表类型徽标用色点区分
 * (不引入运行时联网的 iconify 图标,仅用打包内 lucide 图标)。
 */
import type { EchartsUIType } from '@vben/plugins/echarts';

import type { ReportData } from '#/api/chatbi/shared';

import { onMounted, ref } from 'vue';

import { EchartsUI, useEcharts } from '@vben/plugins/echarts';

import { Alert } from 'ant-design-vue';

const props = defineProps<{ payload: ReportData }>();

const chartRef = ref<EchartsUIType>();
const { renderEcharts } = useEcharts(chartRef);

/** 图表类型 → 徽标色点(与后端 CHART_TYPES 对齐,未知类型回退灰色) */
const CHART_DOT: Record<string, string> = {
  bar: 'bg-blue-500',
  line: 'bg-emerald-500',
  pie: 'bg-amber-500',
};

/** core_data 为 1~3 条文本,按换行/分号拆成要点列表 */
const coreDataItems = ref<string[]>([]);

onMounted(() => {
  const option = props.payload.chart?.echarts_option;
  if (option) {
    void renderEcharts(option as Parameters<typeof renderEcharts>[0]);
  }
  coreDataItems.value = (props.payload.insight?.core_data || '')
    .split(/[\n;；]/)
    .map((s) => s.trim())
    .filter(Boolean);
});
</script>

<template>
  <div class="report-card">
    <Alert
      v-if="payload.message"
      :message="payload.message"
      show-icon
      type="warning"
      class="mb-2"
    />

    <!-- 主视觉:图表 -->
    <div class="overflow-hidden rounded-xl border bg-white shadow-sm">
      <div class="flex items-center gap-2 border-b bg-gray-50/80 px-4 py-2.5">
        <span
          class="size-2.5 rounded-full"
          :class="CHART_DOT[payload.chart?.type] || 'bg-gray-400'"
        />
        <span class="text-sm font-medium">{{ payload.chart?.label || '图表' }}</span>
        <span class="mx-1 text-gray-300">|</span>
        <span class="truncate text-sm text-gray-500">{{ payload.question }}</span>
      </div>
      <div class="px-2 py-3">
        <EchartsUI ref="chartRef" height="360px" />
      </div>
    </div>

    <!-- 解读区 -->
    <div
      v-if="payload.summary || coreDataItems.length > 0 || payload.insight?.trend_analysis"
      class="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-3"
    >
      <div
        v-if="payload.summary"
        class="rounded-xl border bg-white p-4 shadow-sm lg:col-span-3"
      >
        <div class="mb-1.5 text-xs font-semibold tracking-wide text-gray-400 uppercase">
          数据概述
        </div>
        <p class="whitespace-pre-wrap text-sm leading-6 text-gray-700">
          {{ payload.summary }}
        </p>
      </div>

      <div
        v-if="coreDataItems.length > 0"
        class="rounded-xl border bg-white p-4 shadow-sm"
      >
        <div class="mb-2 text-xs font-semibold tracking-wide text-gray-400 uppercase">
          核心数据
        </div>
        <ul class="space-y-1.5">
          <li
            v-for="(item, idx) in coreDataItems"
            :key="idx"
            class="flex gap-2 text-sm leading-6 text-gray-700"
          >
            <span class="mt-2 size-1.5 shrink-0 rounded-full bg-blue-500" />
            <span>{{ item }}</span>
          </li>
        </ul>
      </div>

      <div
        v-if="payload.insight?.trend_analysis"
        class="rounded-xl border bg-white p-4 shadow-sm"
        :class="coreDataItems.length > 0 ? 'lg:col-span-2' : 'lg:col-span-3'"
      >
        <div class="mb-1.5 text-xs font-semibold tracking-wide text-gray-400 uppercase">
          趋势分析
        </div>
        <p class="whitespace-pre-wrap text-sm leading-6 text-gray-700">
          {{ payload.insight.trend_analysis }}
        </p>
      </div>
    </div>
  </div>
</template>
