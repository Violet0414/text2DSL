import { defineConfig } from '@vben/vite-config';

export default defineConfig(async () => {
  return {
    application: {},
    vite: {
      server: {
        proxy: {
          // 保留 /api 前缀直达 FastAPI(后端端点本身挂在 /api 下,不做 rewrite)
          '/api': {
            changeOrigin: true,
            target: 'http://localhost:8000',
            ws: true,
          },
        },
      },
    },
  };
});
