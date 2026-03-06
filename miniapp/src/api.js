const BASE_URL = '/api';

let accessToken = null;

export function setToken(token) {
  accessToken = token;
}

async function request(method, path, body = null) {
  const headers = {};
  if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`;

  let requestBody = null;
  if (body instanceof FormData) {
    requestBody = body;
    // Don't set Content-Type — browser sets it with boundary for FormData
  } else if (body) {
    headers['Content-Type'] = 'application/json';
    requestBody = JSON.stringify(body);
  }

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: requestBody,
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
  addComment: (taskId, text, isInternal, photos) => {
    const form = new FormData();
    form.append('text', text);
    form.append('is_internal', isInternal ? 'true' : 'false');
    if (photos) photos.forEach(p => form.append('photos', p));
    return request('POST', `/tasks/${taskId}/comments/`, form);
  },

  // IT Workers
  getITWorkers: (taskId) => request('GET', `/it-workers/${taskId ? `?task_id=${taskId}` : ''}`),

  // Station management
  getStationWorkers: () => request('GET', '/station/workers/'),
  createStationWorker: (data) => request('POST', '/station/workers/', data),
  removeStationWorker: (id) => request('DELETE', `/station/workers/${id}/`),

  // Password change
  changePassword: (old_password, new_password) =>
    request('POST', '/auth/change-password/', { old_password, new_password }),
};
