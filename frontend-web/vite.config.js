import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        proxy: {
            '/api': {
                target: 'http://127.0.0.1:8080',
                changeOrigin: true,
                timeout: 0,
                proxyTimeout: 0,
                configure: function (proxy) {
                    proxy.on('proxyReq', function (proxyReq, req) {
                        var _a;
                        if ((_a = req.url) === null || _a === void 0 ? void 0 : _a.includes('/messages/stream')) {
                            proxyReq.setHeader('Accept', 'text/event-stream');
                            proxyReq.setHeader('Cache-Control', 'no-cache');
                        }
                    });
                    proxy.on('proxyRes', function (proxyRes, req) {
                        var _a;
                        if ((_a = req.url) === null || _a === void 0 ? void 0 : _a.includes('/messages/stream')) {
                            proxyRes.headers['x-accel-buffering'] = 'no';
                            proxyRes.headers['cache-control'] = 'no-cache';
                        }
                    });
                },
            },
            '/internal': {
                target: 'http://127.0.0.1:8000',
                changeOrigin: true,
                configure: function (proxy) {
                    proxy.on('proxyReq', function (proxyReq) {
                        proxyReq.setHeader('Authorization', 'Bearer secret-token');
                    });
                },
            },
        },
    },
});
