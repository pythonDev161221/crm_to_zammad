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

  linkAccount: (initData, username, password) =>
    request('POST', '/auth/link/', { initData, username, password }),

  registerWithInvite: (initData, token, first_name, last_name) =>
    request('POST', '/auth/register/', { initData, token, first_name, last_name }),

  // Me
  getMe: () => request('GET', '/me/'),

  // Tickets (reported by worker)
  getTickets: () => request('GET', '/tickets/'),
  getTicket: (id) => request('GET', `/tickets/${id}/`),
  createTicket: (title, description, photos, stationId = null) => {
    const form = new FormData();
    form.append('title', title);
    form.append('description', description);
    if (stationId) form.append('station_id', stationId);
    if (photos) photos.forEach(p => form.append('photos', p));
    return request('POST', '/tickets/', form);
  },

  // Station manager: list their own stations
  getMyStations: () => request('GET', '/my-stations/'),

  // IT Manager: list their own companies
  getMyCompanies: () => request('GET', '/my-companies/'),

  // IT Manager: manage staff
  getManageITWorkers: () => request('GET', '/manage/it-workers/'),
  addManageITWorker: (data) => request('POST', '/manage/it-workers/', data),
  removeManageITWorker: (id) => request('DELETE', `/manage/it-workers/${id}/`),

  getManageSupplyWorkers: () => request('GET', '/manage/supply-workers/'),
  addManageSupplyWorker: (data) => request('POST', '/manage/supply-workers/', data),
  removeManageSupplyWorker: (id) => request('DELETE', `/manage/supply-workers/${id}/`),

  getManageStationManagers: () => request('GET', '/manage/station-managers/'),
  addManageStationManager: (data) => request('POST', '/manage/station-managers/', data),
  removeManageStationManager: (id) => request('DELETE', `/manage/station-managers/${id}/`),

  getManageStations: () => request('GET', '/manage/stations/'),
  resolveTicket: (id) => request('POST', `/tickets/${id}/resolve/`),
  rateTicket: (id, rating) => request('POST', `/tickets/${id}/rate/`, { rating }),

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

  // Deputy management (station manager only)
  getStationDeputies: () => request('GET', '/station/deputies/'),
  addStationDeputy: (data) => request('POST', '/station/deputies/', data),
  removeStationDeputy: (id) => request('DELETE', `/station/deputies/${id}/`),

  // Invite link (station manager only)
  getStationInvite: (stationId) => request('GET', `/station/invite/${stationId ? `?station_id=${stationId}` : ''}`),
  generateStationInvite: (stationId) => request('POST', '/station/invite/', stationId ? { station_id: stationId } : {}),
  deleteStationInvite: (stationId) => request('DELETE', `/station/invite/${stationId ? `?station_id=${stationId}` : ''}`),

  // Password change
  changePassword: (old_password, new_password) =>
    request('POST', '/auth/change-password/', { old_password, new_password }),
};
