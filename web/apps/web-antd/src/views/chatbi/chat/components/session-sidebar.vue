<script lang="ts" setup>
/**
 * 会话列表侧栏(FR-C5):列表 + 新会话 + 点击回看历史 + 删除(Popconfirm 二次确认)。
 */
import type { SessionSummary } from '#/api/chatbi/shared';

import { List, ListItem, Button, Popconfirm } from 'ant-design-vue';

defineProps<{
  activeId: string;
  /** 提问进行中(loading):期间禁用删除,避免在途应答把已删会话写回列表 */
  askLoading?: boolean;
  loading: boolean;
  sessions: SessionSummary[];
}>();

defineEmits<{
  select: [summary: SessionSummary];
  'new-session': [];
  remove: [summary: SessionSummary];
}>();

function formatTime(iso: string): string {
  return iso ? iso.replace('T', ' ').slice(0, 16) : '';
}
</script>

<template>
  <div class="flex h-full flex-col">
    <div class="mb-2 flex items-center justify-between">
      <span class="font-medium">历史会话</span>
      <Button size="small" type="primary" @click="$emit('new-session')">
        新会话
      </Button>
    </div>
    <div class="min-h-0 flex-1 overflow-y-auto">
      <List
        :data-source="sessions"
        :loading="loading"
        size="small"
      >
        <template #renderItem="{ item }">
          <ListItem
            :class="[
              'cursor-pointer rounded-md px-2 !py-2 transition-colors',
              item.sessionId === activeId
                ? 'border-l-2 border-solid border-l-blue-500 bg-blue-50'
                : 'border-l-2 border-solid border-l-transparent hover:bg-gray-50',
            ]"
            @click="$emit('select', item)"
          >
            <div class="flex w-full items-center gap-1">
              <div class="min-w-0 flex-1">
                <div class="truncate text-sm">{{ item.title || '（无标题）' }}</div>
                <div class="text-xs text-gray-400">
                  {{ formatTime(item.updatedAt) }} · {{ item.messageCount }} 条
                </div>
              </div>
              <Popconfirm
                :cancel-button-props="{ size: 'small' }"
                :ok-button-props="{ danger: true, size: 'small' }"
                cancel-text="取消"
                ok-text="删除"
                title="删除后不可恢复，确定删除该会话？"
                @confirm="$emit('remove', item)"
              >
                <Button
                  class="shrink-0"
                  danger
                  :disabled="askLoading"
                  size="small"
                  type="text"
                  @click.stop
                >
                  删除
                </Button>
              </Popconfirm>
            </div>
          </ListItem>
        </template>
      </List>
      <div
        v-if="!loading && sessions.length === 0"
        class="py-6 text-center text-sm text-gray-400"
      >
        暂无历史会话
      </div>
    </div>
  </div>
</template>
