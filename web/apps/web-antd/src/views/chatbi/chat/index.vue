<script lang="ts" setup>
/**
 * ChatBI 聊天问数页(W0):会话侧栏 + 消息流 + 输入区。
 * 覆盖 PRD 场景 S1 直查 / S2 澄清 / S4 未命中 / S5 旁路 / S6 降级(表格形态)。
 */
import type { ChartOptionInfo, SessionSummary } from '#/api/chatbi/shared';

import { computed, onMounted, nextTick, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import { LogOut, RotateCw } from '@vben/icons';
import { Page } from '@vben/common-ui';

import {
  Button,
  Card,
  Input,
  message as antMessage,
  Tooltip,
} from 'ant-design-vue';

import SessionSidebar from './components/session-sidebar.vue';
import MessageItem from './components/message-item.vue';
import { ChatbiApiError } from '#/api/chatbi/shared';
import { useChat } from './use-chat';

const router = useRouter();
const chat = useChat();
const input = ref('');
const listRef = ref<HTMLElement>();

const {
  askOnce,
  loadSessions,
  loading,
  messages,
  newSession,
  openSession,
  removeSession,
  requestChart,
  selectClarifyOption,
  sessions,
  sessionId,
  sessionsLoading,
} = chat;

async function send(): Promise<void> {
  const text = input.value.trim();
  if (!text || loading.value) return;
  input.value = '';
  await askOnce(text);
  await loadSessions();
}

/** 消息条数变化(新提问/新应答)即自动滚底,替代各处手动调用 */
watch(
  () => messages.value.length,
  () => scrollToBottom(),
);

function scrollToBottom(): void {
  void nextTick(() => {
    if (listRef.value) {
      listRef.value.scrollTop = listRef.value.scrollHeight;
    }
  });
}

function onNewSession(): void {
  newSession();
}

/**
 * 最新一张成功答案卡的 id:图表按钮只渲染在它上面,
 * 避免多轮成功后旧卡按钮画出最新查询的数据(复查 MEDIUM 修复)。
 */
const lastAnswerId = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const m = messages.value[i];
    if (
      m &&
      m.role === 'assistant' &&
      !m.pending &&
      !m.error &&
      m.payload?.type === 'answer'
    ) {
      return m.id;
    }
  }
  return '';
});

/** 图表直出(R2):不渲染 chart_select JSON,直接进入生成态 */
function onChartSelect(chart: ChartOptionInfo): void {
  void requestChart(chart).then(() => loadSessions());
}

/** 空状态示例问题:点击即问 */
const SAMPLE_QUESTIONS = [
  '上个月各渠道营收',
  '华南区上个月销售额',
  '最近三个月各渠道趋势',
] as const;

async function askSample(question: string): Promise<void> {
  if (loading.value) return;
  await askOnce(question);
  await loadSessions();
}

async function onSelectSession(summary: SessionSummary): Promise<void> {
  try {
    await openSession(summary);
    scrollToBottom();
  } catch {
    antMessage.error('历史回看加载失败');
  }
}

async function onDeleteSession(summary: SessionSummary): Promise<void> {
  try {
    await removeSession(summary);
    antMessage.success('会话已删除');
  } catch (error) {
    // 错误不吞:ChatbiApiError 连同 code/traceId 展示,便于与服务端日志关联
    const detail =
      error instanceof ChatbiApiError
        ? `[${error.code}] 删除失败${error.traceId ? ` (traceId: ${error.traceId})` : ''}`
        : '删除失败，请重试';
    antMessage.error(detail);
  }
}

function onLogout(): void {
  void router.push('/auth/login');
}

onMounted(() => {
  void loadSessions();
  scrollToBottom();
});
</script>

<template>
  <Page
    title="智能问数"
    description="受控问数：答案永远带口径出处，未定义指标绝不给数"
    header-class="mx-4 mt-4 rounded-lg border"
  >
    <div class="flex h-[calc(100vh-160px)] gap-3">
      <Card class="w-64 shrink-0 overflow-hidden" :body-style="{ padding: '12px' }">
        <SessionSidebar
          :active-id="sessionId"
          :ask-loading="loading"
          :loading="sessionsLoading"
          :sessions="sessions"
          @remove="onDeleteSession"
          @select="onSelectSession"
          @new-session="onNewSession"
        />
      </Card>

      <Card
        class="min-w-0 flex-1 flex flex-col overflow-hidden"
        :body-style="{ padding: '12px', display: 'flex', flexDirection: 'column', height: '100%' }"
      >
        <div
          ref="listRef"
          class="min-h-0 flex-1 overflow-y-auto pr-1"
        >
          <div
            v-if="messages.length === 0"
            class="flex h-full flex-col items-center justify-center py-10"
          >
            <div
              class="mb-4 flex size-14 items-center justify-center rounded-2xl bg-blue-50 text-2xl"
            >
              📊
            </div>
            <p class="text-lg font-medium text-gray-700">问我数据问题</p>
            <p class="mt-1 text-sm text-gray-400">
              受控问数：答案永远带口径出处，未定义指标绝不给数
            </p>
            <div class="mt-5 flex flex-wrap justify-center gap-2">
              <Button
                v-for="q in SAMPLE_QUESTIONS"
                :key="q"
                :disabled="loading"
                size="small"
                class="rounded-full"
                @click="askSample(q)"
              >
                {{ q }}
              </Button>
            </div>
          </div>
          <MessageItem
            v-for="m in messages"
            :key="m.id"
            :is-latest-answer="m.id === lastAnswerId"
            :message="m"
            @chart-select="onChartSelect"
            @select="selectClarifyOption"
          />
        </div>

        <div class="mt-2 flex items-start gap-2 border-t pt-3">
          <Input.TextArea
            v-model:value="input"
            :auto-size="{ minRows: 1, maxRows: 4 }"
            :disabled="loading"
            class="rounded-lg"
            placeholder="输入自然语言问题，Enter 发送，Shift+Enter 换行"
            @keydown.enter.prevent="send"
          />
          <Tooltip title="清空上下文，开始新会话（FR-C4）">
            <Button :disabled="loading" @click="onNewSession">
              <RotateCw class="size-3.5" />
            </Button>
          </Tooltip>
          <Button
            :disabled="loading"
            :loading="loading"
            type="primary"
            class="rounded-lg"
            @click="send"
          >
            发送
          </Button>
          <Tooltip title="退出登录">
            <Button danger ghost @click="onLogout">
              <LogOut class="size-3.5" />
            </Button>
          </Tooltip>
        </div>
      </Card>
    </div>
  </Page>
</template>
