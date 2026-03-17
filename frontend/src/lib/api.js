import axios from 'axios';

// Use relative URL so Nginx proxies /api/ to backend automatically.
// Works regardless of IP/domain — no need for REACT_APP_BACKEND_URL.
const API_BASE = '/api';

const api = axios.create({ baseURL: API_BASE });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('noc_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('noc_token');
      localStorage.removeItem('noc_user');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default api;
