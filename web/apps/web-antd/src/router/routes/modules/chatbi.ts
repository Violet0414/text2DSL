import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:message-circle',
      order: -1,
      title: '智能问数',
    },
    name: 'Chatbi',
    path: '/chatbi',
    children: [
      {
        name: 'ChatbiChat',
        path: 'chat',
        component: () => import('#/views/chatbi/chat/index.vue'),
        meta: {
          icon: 'lucide:message-circle',
          title: '智能问数',
        },
      },
    ],
  },
];

export default routes;
