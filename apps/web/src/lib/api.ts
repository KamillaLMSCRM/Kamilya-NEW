import axios from 'axios';
import { getAccessToken, clearStoredAuth } from '@/lib/auth';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      clearStoredAuth();
      if (typeof window !== 'undefined') {
        window.location.href = '/login';
      }
    }
    // Demo sandbox limits — surface a global event so DemoLimitProvider
    // can pop the friendly modal regardless of which component fired
    // the request.
    if (
      err.response?.status === 403 &&
      err.response?.data?.detail?.code === 'demo_limit_exceeded'
    ) {
      if (typeof window !== 'undefined') {
        window.dispatchEvent(
          new CustomEvent('demo_limit', { detail: err.response.data.detail })
        );
      }
    }
    return Promise.reject(err);
  },
);

export default api;
