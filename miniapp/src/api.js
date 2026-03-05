const BASE_URL = '/api';

let accessToken = null;

export function setToken(token) {
  accessToken = token;
}

async function request(method, path, body = null) {
  const headers = { 'Content-Type': 'application/json' };
  if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`;

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : null,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }

  return res.status === 204 ? null : res.json();
}

export const api = {
  // Auth
  telegramAuth: (initData) =>
    request('POST', '/auth/telegram/', { initData }),

  // Me
  getMe: () => request('GET', '/me/'),

  // Tasks
  getTasks: () => request('GET', '/tasks/'),
  getTask: (id) => request('GET', `/tasks/${id}/`),
  createTask: (data) => request('POST', '/tasks/', data),
  resolveTask: (id) => request('POST', `/tasks/${id}/resolve/`),

  // Tickets
  createTicket: (taskId, data) => request('POST', `/tasks/${taskId}/tickets/`, data),
  updateTicket: (id, data) => request('PATCH', `/tickets/${id}/`, data),

  // Comments
  addComment: (taskId, text) => request('POST', `/tasks/${taskId}/comments/`, { text }),

  // IT Workers
  getITWorkers: () => request('GET', '/it-workers/'),

  // Station management
  getStationWorkers: () => request('GET', '/station/workers/'),
  createStationWorker: (data) => request('POST', '/station/workers/', data),
  removeStationWorker: (id) => request('DELETE', `/station/workers/${id}/`),

  // Password change
  changePassword: (old_password, new_password) =>
    request('POST', '/auth/change-password/', { old_password, new_password }),
};
