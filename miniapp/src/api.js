const BASE_URL = '/api';

let accessToken = null;
let refreshToken = null;

export function setToken(access, refresh) {
  accessToken = access;
  if (refresh !== undefined) refreshToken = refresh;
}

async function doFetch(method, path, body) {
  const headers = {};
  if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`;

  let requestBody = null;
  if (body instanceof FormData) {
    requestBody = body;
  } else if (body) {
    headers['Content-Type'] = 'application/json';
    requestBody = JSON.stringify(body);
  }

  return fetch(`${BASE_URL}${path}`, { method, headers, body: requestBody });
}

async function request(method, path, body = null) {
  let res = await doFetch(method, path, body);

  if (res.status === 401 && refreshToken) {
    // Try to refresh the access token
    const refreshRes = await fetch(`${BASE_URL}/auth/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh: refreshToken }),
    });
    if (refreshRes.ok) {
      const data = await refreshRes.json();
      accessToken = data.access;
      res = await doFetch(method, path, body);
    }
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }

  return res.status === 204 ? null : res.json();
}

function withCompany(path, companyId) {
  return companyId ? `${path}?company_id=${companyId}` : path;
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
  updateMe: (data) => request('PATCH', '/me/', data),

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
  getManageITWorkers: (companyId) => request('GET', withCompany('/manage/it-workers/', companyId)),
  addManageITWorker: (data) => request('POST', '/manage/it-workers/', data),
  removeManageITWorker: (id) => request('DELETE', `/manage/it-workers/${id}/`),

  getManageSupplyWorkers: (companyId) => request('GET', withCompany('/manage/supply-workers/', companyId)),
  addManageSupplyWorker: (data) => request('POST', '/manage/supply-workers/', data),
  removeManageSupplyWorker: (id) => request('DELETE', `/manage/supply-workers/${id}/`),

  getManageStationManagers: (companyId) => request('GET', withCompany('/manage/station-managers/', companyId)),
  addManageStationManager: (data) => request('POST', '/manage/station-managers/', data),
  removeManageStationManager: (id) => request('DELETE', `/manage/station-managers/${id}/`),

  getManageITDeputies: (companyId) => request('GET', withCompany('/manage/it-deputies/', companyId)),
  promoteToITDeputy: (data) => request('POST', '/manage/it-deputies/', data),
  demoteITDeputy: (id) => request('DELETE', `/manage/it-deputies/${id}/`),

  getManageStations: (companyId) => request('GET', withCompany('/manage/stations/', companyId)),
  getEmptyStations: (companyId) => request('GET', companyId ? `/manage/stations/?company_id=${companyId}&empty=true` : '/manage/stations/?empty=true'),
  setStationManager: (stationId, userId) => request('POST', `/manage/stations/${stationId}/set-manager/`, { user_id: userId }),
  removeStationManager: (stationId) => request('DELETE', `/manage/stations/${stationId}/remove-manager/`),
  resolveTicket: (id) => request('POST', `/tickets/${id}/resolve/`),
  rateTicket: (id, rating) => request('POST', `/tickets/${id}/rate/`, { rating }),

  // Tasks (assigned to IT workers within a ticket)
  createTask: (ticketId, data) => request('POST', `/tickets/${ticketId}/tasks/`, data),
  updateTask: (id, data) => request('PATCH', `/tasks/${id}/`, data),
  cancelTask: (id) => request('DELETE', `/tasks/${id}/cancel/`),

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
  getStationWorkers: (stationId) => request('GET', stationId ? `/station/workers/?station_id=${stationId}` : '/station/workers/'),
  createStationWorker: (data) => request('POST', '/station/workers/', data),
  removeStationWorker: (id) => request('DELETE', `/station/workers/${id}/`),

  // Deputy management (station manager only)
  getStationDeputies: (stationId) => request('GET', stationId ? `/station/deputies/?station_id=${stationId}` : '/station/deputies/'),
  addStationDeputy: (data) => request('POST', '/station/deputies/', data),
  removeStationDeputy: (id, stationId) => request('DELETE', `/station/deputies/${id}/${stationId ? `?station_id=${stationId}` : ''}`),

  // Invite link (station manager only)
  getStationInvite: (stationId) => request('GET', `/station/invite/${stationId ? `?station_id=${stationId}` : ''}`),
  generateStationInvite: (stationId) => request('POST', '/station/invite/', stationId ? { station_id: stationId } : {}),
  deleteStationInvite: (stationId) => request('DELETE', `/station/invite/${stationId ? `?station_id=${stationId}` : ''}`),

  // Role invites (IT manager)
  getRoleInvites: (companyId) => request('GET', withCompany('/manage/role-invite/', companyId)),
  createRoleInvite: (data) => request('POST', '/manage/role-invite/', data),
  deleteRoleInvite: (id) => request('DELETE', `/manage/role-invite/${id}/`),

  // Password change
  changePassword: (old_password, new_password) =>
    request('POST', '/auth/change-password/', { old_password, new_password }),

  // Education
  getEducation: (companyId) => request('GET', companyId ? `/education/?company_id=${companyId}` : '/education/'),
  createEducation: (title, description, itemType, file, url, companyId) => {
    const form = new FormData();
    form.append('title', title);
    form.append('description', description);
    form.append('item_type', itemType);
    if (file) form.append('file', file);
    if (url) form.append('url', url);
    if (companyId) form.append('company_id', companyId);
    return request('POST', '/education/', form);
  },
  deleteEducation: (id) => request('DELETE', `/education/${id}/`),
};
