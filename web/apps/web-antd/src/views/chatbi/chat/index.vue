<script lang="ts" setup>
/**
 * ChatBI 聊天问数页(W0):会话侧栏 + 消息流 + 输入区。
 * 覆盖 PRD 场景 S1 直查 / S2 澄清 / S4 未命中 / S5 旁路 / S6 降级(表格形态)。
 */
import type { SessionSummary } from '#/api/chatbi/shared';

import { onMounted, nextTick, ref } from 'vue';
import { useRouter } from 'vue-router';

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
  scrollToBottom();
}

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

async function onSelectSession(summary: SessionSummary): Promise<void> {
  try {
    await openSession(summary);
    scrollToBottom();
  } catch {
    antMessage.error('历史回看加载失败');
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
  <Page title="智能问数" description="受控问数：答案永远带口径出处，未定义指标绝不给数">
    <div class="flex h-[calc(100vh-160px)] gap-3">
      <Card class="w-64 shrink-0 overflow-hidden" :body-style="{ padding: '12px' }">
        <SessionSidebar
          :active-id="sessionId"
          :loading="sessionsLoading"
          :sessions="sessions"
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
          <div v-if="messages.length === 0" class="py-10 text-center text-gray-400">
            <p class="text-base">试着问：上个月各渠道营收是多少？</p>
            <p class="mt-1 text-sm">
              支持：口径澄清、多轮追问、未定义指标提示
            </p>
          </div>
          <MessageItem
            v-for="m in messages"
            :key="m.id"
            :message="m"
            @select="selectClarifyOption"
          />
        </div>

        <div class="mt-2 flex items-start gap-2 border-t pt-2">
          <Input.TextArea
            v-model:value="input"
            :auto-size="{ minRows: 1, maxRows: 4 }"
            :disabled="loading"
            placeholder="输入自然语言问题，Enter 发送，Shift+Enter 换行"
            @keydown.enter.prevent="send"
          />
          <Tooltip title="清空上下文，开始新会话（FR-C4）">
            <Button :disabled="loading" @click="onNewSession">重新问</Button>
          </Tooltip>
          <Button
            :disabled="loading"
            :loading="loading"
            type="primary"
            @click="send"
          >
            发送
          </Button>
          <Button danger ghost @click="onLogout">退出</Button>
        </div>
      </Card>
    </div>
  </Page>
</template>
