<script lang="ts" setup>
/**
 * 会话列表侧栏(FR-C5):列表 + 新会话 + 点击回看历史。
 */
import type { SessionSummary } from '#/api/chatbi/shared';

import { List, ListItem, Button } from 'ant-design-vue';

defineProps<{
  activeId: string;
  loading: boolean;
  sessions: SessionSummary[];
}>();

defineEmits<{
  select: [summary: SessionSummary];
  'new-session': [];
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
              'cursor-pointer rounded-md px-2 !py-2',
              item.sessionId === activeId ? 'bg-blue-50' : 'hover:bg-gray-50',
            ]"
            @click="$emit('select', item)"
          >
            <div class="min-w-0">
              <div class="truncate text-sm">{{ item.title || '（无标题）' }}</div>
              <div class="text-xs text-gray-400">
                {{ formatTime(item.updatedAt) }} · {{ item.messageCount }} 条
              </div>
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
