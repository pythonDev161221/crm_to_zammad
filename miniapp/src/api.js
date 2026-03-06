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

  // Tickets (reported by worker)
  getTickets: () => request('GET', '/tickets/'),
  getTicket: (id) => request('GET', `/tickets/${id}/`),
  createTicket: (data) => request('POST', '/tickets/', data),
  resolveTicket: (id) => request('POST', `/tickets/${id}/resolve/`),

  // Tasks (assigned to IT workers within a ticket)
  createTask: (ticketId, data) => request('POST', `/tickets/${ticketId}/tasks/`, data),
  updateTask: (id, data) => request('PATCH', `/tasks/${id}/`, data),

  // Comments
  addComment: (ticketId, text, isInternal, photos) => {
    const form = new FormData();
    form.append('text', text);
    form.append('is_internal', isInternal ? 'true' : 'false');
    if (photos) photos.forEach(p => form.append('photos', p));
    return request('POST', `/tickets/${ticketId}/comments/`, form);
  },

  // IT Workers
  getITWorkers: (ticketId) => request('GET', `/it-workers/${ticketId ? `?ticket_id=${ticketId}` : ''}`),

  // Station management
  getStationWorkers: () => request('GET', '/station/workers/'),
  createStationWorker: (data) => request('POST', '/station/workers/', data),
  removeStationWorker: (id) => request('DELETE', `/station/workers/${id}/`),

  // Password change
  changePassword: (old_password, new_password) =>
    request('POST', '/auth/change-password/', { old_password, new_password }),
};
