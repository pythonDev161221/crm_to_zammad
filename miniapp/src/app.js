import { api, setToken } from '/static/api.js';

const tg = window.Telegram?.WebApp;
const inTelegram = !!(tg?.initData);
const app = document.getElementById('app');

function tgAlert(msg) { inTelegram ? tg.showAlert(msg) : alert(msg); }
function tgConfirm(msg) {
  return inTelegram
    ? new Promise(resolve => tg.showConfirm(msg, resolve))
    : Promise.resolve(confirm(msg));
}

let currentUser = null;

// ── Router ────────────────────────────────────────────────────────────────────

window.showScreen = function(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  const screen = document.getElementById(id);
  if (screen) screen.classList.add('active');
  if (inTelegram) tg.BackButton[id === 'screen-tickets' ? 'hide' : 'show']();
}

// ── Auth ──────────────────────────────────────────────────────────────────────

async function init() {
  if (inTelegram) { tg.ready(); tg.expand(); tg.BackButton.onClick(() => showScreen('screen-tickets')); }

  showScreen('screen-loading');

  try {
    const devToken = localStorage.getItem('dev_access_token');
    if (devToken) {
      setToken(devToken);
      const me = await api.getMe();
      currentUser = { id: me.id, role: me.role, name: me.first_name || me.username };
      if (me.role === 'it_manager') {
        currentUser.companies = await api.getMyCompanies().catch(() => []);
      }
      await loadTickets();
      return;
    }

    const initData = tg?.initData || '';
    if (!initData) {
      window.location.href = '/dev/';
      return;
    }
    const auth = await api.telegramAuth(initData);
    setToken(auth.access);
    currentUser = auth.user;
    if (currentUser.role === 'it_manager') {
      currentUser.companies = await api.getMyCompanies().catch(() => []);
    }
    await loadTickets();
  } catch (e) {
    showError('Auth failed: ' + e.message);
  }
}

// ── Ticket List ───────────────────────────────────────────────────────────────

async function loadTickets() {
  showScreen('screen-tickets');
  const list = document.getElementById('tickets-list');
  list.innerHTML = '<div class="loading">Loading...</div>';

  try {
    const tickets = await api.getTickets();
    renderTicketList(tickets);
  } catch (e) {
    list.innerHTML = `<div class="empty">Error: ${e.message}</div>`;
  }
}

function renderTicketList(tickets) {
  const list = document.getElementById('tickets-list');
  const role = currentUser.role;

  const fab = document.getElementById('fab-new-ticket');
  fab.style.display = (role === 'worker' || role === 'station_manager' || role === 'deputy') ? 'flex' : 'none';

  const btnStation = document.getElementById('btn-station');
  btnStation.style.display = (role === 'station_manager' || role === 'deputy') ? 'inline' : 'none';

  const btnManage = document.getElementById('btn-manage');
  btnManage.style.display = role === 'it_manager' ? 'inline' : 'none';

  if (!tickets.length) {
    list.innerHTML = '<div class="empty">No tickets yet.</div>';
    return;
  }

  list.innerHTML = tickets.map(t => `
    <div class="card" onclick="openTicket(${t.id})">
      <div class="card-title">${escHtml(t.title)}</div>
      <div class="card-meta">
        <span class="badge badge-${t.status}">${formatStatus(t.status)}</span>
        &nbsp;${formatDate(t.created_at)}
      </div>
      ${role !== 'worker' ? `<div class="card-meta" style="margin-top:4px">${t.tasks?.length || 0} task(s)</div>` : ''}
    </div>
  `).join('');
}

// ── Ticket Detail ─────────────────────────────────────────────────────────────

window.openTicket = async function(id) {
  showScreen('screen-ticket-detail');
  const body = document.getElementById('ticket-detail-body');
  body.innerHTML = '<div class="loading">Loading...</div>';

  try {
    const ticket = await api.getTicket(id);
    renderTicketDetail(ticket);
  } catch (e) {
    body.innerHTML = `<div class="empty">Error: ${e.message}</div>`;
  }
};

function renderTicketDetail(ticket) {
  const header = document.getElementById('ticket-detail-title');
  header.textContent = ticket.title;

  const body = document.getElementById('ticket-detail-body');
  const role = currentUser.role;
  const isITWorker = role === 'it_worker' || role === 'it_manager' || role === 'admin';
  const isSupplyWorker = role === 'supply_worker';
  const isManager = role === 'station_manager' || role === 'deputy';
  const canComment = !isManager;
  const myTask = ticket.tasks?.find(t => t.assigned_to === currentUser.id);

  body.innerHTML = `
    <div class="detail-body">
      <!-- Status -->
      <div class="detail-section">
        <span class="badge badge-${ticket.status}">${formatStatus(ticket.status)}</span>
        <span style="color:var(--hint);font-size:13px;margin-left:8px">by ${escHtml(ticket.created_by_name)}</span>
      </div>

      <!-- Description -->
      ${ticket.description || ticket.photos?.length ? `
        <div class="detail-section">
          ${ticket.description ? `<h3>Description</h3><div class="description-text">${escHtml(ticket.description)}</div>` : ''}
          ${ticket.photos?.length ? `
            <div class="comment-photos" style="margin-top:${ticket.description ? '10px' : '0'}">
              ${ticket.photos.map(p => `<img class="comment-photo" src="${p.image}" onclick="openPhoto('${p.image}')">`).join('')}
            </div>` : ''}
        </div>` : ''}

      <!-- Tasks -->
      ${isITWorker ? `
        <div class="detail-section">
          <h3>Tasks</h3>
          ${ticket.tasks?.length ? ticket.tasks.map(t => `
            <div class="ticket-card">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <div class="ticket-worker">${escHtml(t.assigned_to_name)}</div>
                <span class="badge badge-${t.status}">${formatStatus(t.status)}</span>
              </div>
              ${t.notes ? `<div class="ticket-notes">${escHtml(t.notes)}</div>` : ''}
              ${t.assigned_to === currentUser.id ? renderTaskActions(t) : ''}
            </div>
          `).join('') : '<div class="empty" style="padding:10px">No tasks yet.</div>'}
        </div>` : ''}
      ${isSupplyWorker && myTask ? `
        <div class="detail-section">
          <h3>My Task</h3>
          <div class="ticket-card">
            <div style="display:flex;justify-content:space-between;align-items:center">
              <div class="ticket-worker">${escHtml(myTask.assigned_to_name)}</div>
              <span class="badge badge-${myTask.status}">${formatStatus(myTask.status)}</span>
            </div>
            ${myTask.notes ? `<div class="ticket-notes">${escHtml(myTask.notes)}</div>` : ''}
            ${renderTaskActions(myTask)}
          </div>
        </div>` : ''}

      <!-- Comments -->
      <div class="detail-section" id="comments-section">
        <h3>Comments</h3>
        ${renderComments(ticket.comments)}
      </div>
    </div>

    <!-- Comment input (not for station managers) -->
    ${canComment ? `
    <div class="comment-input-area">
      ${isITWorker ? `
        <div class="comment-internal-toggle">
          <label><input type="checkbox" id="comment-internal"> Internal (IT staff only)</label>
        </div>` : ''}
      <div class="comment-input-row">
        <input id="comment-input" type="text" placeholder="Write a comment...">
        <label class="comment-photo-btn" title="Attach photo">
          &#128247;
          <input type="file" id="comment-photos" accept="image/*" multiple style="display:none">
        </label>
        <button onclick="submitComment(${ticket.id})">&#10148;</button>
      </div>
      <div id="comment-photo-preview" class="comment-photo-preview"></div>
    </div>` : ''}

    <!-- IT Worker actions -->
    ${isITWorker && ticket.status !== 'resolved' ? `
      <div style="padding:0 16px 16px;display:flex;flex-direction:column;gap:8px">
        ${!ticket.tasks?.find(t => t.assigned_to === currentUser.id) ? `
          <button class="btn btn-primary" onclick="assignSelf(${ticket.id})">Take this ticket</button>
        ` : ''}
        ${myTask && myTask.status !== 'done' ? `
          <button class="btn btn-secondary" onclick="showDelegateForm(${ticket.id})">Delegate to another IT worker</button>
        ` : ''}
        ${canResolve(ticket) ? `
          <button class="btn btn-danger" onclick="resolveTicket(${ticket.id})">Mark as Resolved</button>
        ` : ''}
      </div>
    ` : ''}
  `;

  document.getElementById('screen-ticket-detail').dataset.ticketId = ticket.id;
}

function renderTaskActions(task) {
  if (task.status === 'done') return '';
  const next = task.status === 'open' ? 'in_progress' : 'done';
  const label = next === 'in_progress' ? 'Start working' : 'Mark my part done';
  return `<button class="btn btn-primary" style="margin-top:8px" onclick="updateTask(${task.id}, '${next}')">
    ${label}
  </button>`;
}

function renderComments(comments) {
  if (!comments?.length) return '<div class="empty" style="padding:10px">No comments yet.</div>';
  return comments.map(c => `
    <div class="comment ${c.is_internal ? 'comment-internal' : ''}">
      <div class="comment-author">
        ${escHtml(c.author_name)}
        ${c.is_internal ? '<span class="comment-internal-badge">Internal</span>' : ''}
      </div>
      ${c.text ? `<div class="comment-text">${escHtml(c.text)}</div>` : ''}
      ${c.photos?.length ? `
        <div class="comment-photos">
          ${c.photos.map(p => `<img class="comment-photo" src="${p.image}" onclick="openPhoto('${p.image}')">`).join('')}
        </div>` : ''}
      <div class="comment-time">${formatDate(c.created_at)}</div>
    </div>
  `).join('');
}

function canResolve(ticket) {
  if (!ticket.tasks?.length) return false;
  return ticket.tasks.every(t => t.status === 'done');
}

// ── Actions ───────────────────────────────────────────────────────────────────

window.updateTask = async function(taskId, newStatus) {
  try {
    await api.updateTask(taskId, { status: newStatus });
    const ticketId = document.getElementById('screen-ticket-detail').dataset.ticketId;
    await openTicket(ticketId);
  } catch (e) {
    tgAlert(e.message);
  }
};

window.assignSelf = async function(ticketId) {
  try {
    await api.createTask(ticketId, {
      assigned_to: currentUser.id,
      status: 'open',
    });
    await openTicket(ticketId);
  } catch (e) {
    tgAlert(e.message);
  }
};

window.resolveTicket = async function(ticketId) {
  const confirmed = await tgConfirm('Mark this ticket as resolved and send to Zammad?');
  if (!confirmed) return;
  try {
    await api.resolveTicket(ticketId);
    tgAlert('Ticket resolved and archived to Zammad.');
    await loadTickets();
    showScreen('screen-tickets');
  } catch (e) {
    tgAlert(e.message);
  }
};

window.submitComment = async function(ticketId) {
  const input = document.getElementById('comment-input');
  const text = input.value.trim();
  const photoInput = document.getElementById('comment-photos');
  const photos = photoInput ? [...photoInput.files] : [];
  const isInternal = document.getElementById('comment-internal')?.checked || false;

  if (!text && !photos.length) return;

  try {
    await api.addComment(ticketId, text, isInternal, photos);
    input.value = '';
    if (photoInput) photoInput.value = '';
    document.getElementById('comment-photo-preview').innerHTML = '';
    if (document.getElementById('comment-internal')) {
      document.getElementById('comment-internal').checked = false;
    }
    await openTicket(ticketId);
  } catch (e) {
    tgAlert(e.message);
  }
};

let selectedDelegateWorkerId = null;

window.showDelegateForm = async function(ticketId) {
  showScreen('screen-delegate');
  document.getElementById('delegate-ticket-id').value = ticketId;
  document.getElementById('delegate-notes').value = '';
  selectedDelegateWorkerId = null;

  const list = document.getElementById('delegate-worker-list');
  list.innerHTML = '<div class="empty">Loading...</div>';

  try {
    const workers = await api.getITWorkers(ticketId);
    if (!workers.length) {
      list.innerHTML = '<div class="empty">No other IT workers available.</div>';
      return;
    }
    list.innerHTML = workers.map(w => `
      <div class="card" id="delegate-worker-${w.id}" onclick="selectWorker(${w.id}, '${escHtml(w.name)}')">
        <div class="card-title">🔧 ${escHtml(w.name)}</div>
      </div>
    `).join('');
  } catch (e) {
    list.innerHTML = `<div class="empty">Error: ${e.message}</div>`;
  }
};

window.selectWorker = function(id, name) {
  selectedDelegateWorkerId = id;
  document.querySelectorAll('#delegate-worker-list .card').forEach(c => {
    c.style.border = '2px solid transparent';
  });
  const card = document.getElementById(`delegate-worker-${id}`);
  if (card) card.style.border = '2px solid var(--button)';
};

window.submitDelegate = async function() {
  const ticketId = document.getElementById('delegate-ticket-id').value;
  const notes = document.getElementById('delegate-notes').value.trim();

  if (!selectedDelegateWorkerId) {
    tgAlert('Please select an IT worker.');
    return;
  }

  try {
    await api.createTask(ticketId, {
      assigned_to: selectedDelegateWorkerId,
      status: 'open',
      notes,
    });
    await openTicket(ticketId);
    showScreen('screen-ticket-detail');
  } catch (e) {
    tgAlert(e.message);
  }
};

// ── Create Ticket ─────────────────────────────────────────────────────────────

window.showCreateTicket = async function() {
  showScreen('screen-create-ticket');
  document.getElementById('new-ticket-title').value = '';
  document.getElementById('new-ticket-desc').value = '';
  document.getElementById('new-ticket-photos').value = '';
  document.getElementById('new-ticket-photo-preview').innerHTML = '';

  const stationField = document.getElementById('station-select-field');
  stationField.style.display = 'none';

  if (currentUser.role === 'station_manager') {
    try {
      const stations = await api.getMyStations();
      if (stations.length > 1) {
        const select = document.getElementById('new-ticket-station');
        select.innerHTML = stations.map(s => `<option value="${s.id}">${escHtml(s.name)}</option>`).join('');
        stationField.style.display = '';
      }
    } catch (e) {
      tgAlert('Could not load stations: ' + e.message);
    }
  }
};

window.previewTicketPhotos = function(input) {
  const preview = document.getElementById('new-ticket-photo-preview');
  preview.innerHTML = '';
  [...input.files].forEach(file => {
    const img = document.createElement('img');
    img.className = 'comment-photo';
    img.src = URL.createObjectURL(file);
    preview.appendChild(img);
  });
};

window.submitCreateTicket = async function() {
  const title = document.getElementById('new-ticket-title').value.trim();
  const description = document.getElementById('new-ticket-desc').value.trim();
  const photoInput = document.getElementById('new-ticket-photos');
  const photos = photoInput ? [...photoInput.files] : [];

  if (!title) {
    tgAlert('Please enter a title.');
    return;
  }

  let stationId = null;
  if (currentUser.role === 'station_manager') {
    const stationField = document.getElementById('station-select-field');
    if (stationField.style.display !== 'none') {
      stationId = document.getElementById('new-ticket-station').value;
    }
  }

  try {
    await api.createTicket(title, description, photos, stationId);
    await loadTickets();
    showScreen('screen-tickets');
  } catch (e) {
    tgAlert(e.message);
  }
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function escHtml(str) {
  if (!str) return '';
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function formatStatus(s) {
  return { open: 'Open', in_progress: 'In Progress', done: 'Done', resolved: 'Resolved' }[s] || s;
}

function formatDate(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function showError(msg) {
  app.innerHTML = `<div class="loading" style="flex-direction:column;gap:8px">
    <div>⚠️</div><div>${escHtml(msg)}</div>
  </div>`;
}

// ── Station Workers ───────────────────────────────────────────────────────────

window.showStationWorkers = async function() {
  showScreen('screen-station-workers');
  const btnDeputies = document.getElementById('btn-deputies');
  if (btnDeputies) btnDeputies.style.display = currentUser.role === 'station_manager' ? 'inline' : 'none';
  const list = document.getElementById('station-workers-list');
  list.innerHTML = '<div class="loading">Loading...</div>';

  try {
    const workers = await api.getStationWorkers();
    if (!workers.length) {
      list.innerHTML = '<div class="empty">No workers yet. Add the first one.</div>';
      return;
    }
    list.innerHTML = workers.map(w => `
      <div class="card" style="display:flex;align-items:center;justify-content:space-between">
        <div>
          <div class="card-title">${escHtml(w.name)}</div>
          <div class="card-meta">@${escHtml(w.username)} · ${w.is_active ? 'Active' : '<span style="color:#dc3545">Deactivated</span>'}</div>
        </div>
        ${w.is_active ? `<button class="btn btn-danger" style="width:auto;padding:6px 12px;font-size:13px" onclick="removeWorker(${w.id}, '${escHtml(w.name)}')">Remove</button>` : ''}
      </div>
    `).join('');
  } catch (e) {
    list.innerHTML = `<div class="empty">Error: ${e.message}</div>`;
  }
};

window.removeWorker = async function(id, name) {
  const confirmed = await tgConfirm(`Deactivate ${name}?`);
  if (!confirmed) return;
  try {
    await api.removeStationWorker(id);
    await showStationWorkers();
  } catch (e) {
    tgAlert(e.message);
  }
};

window.submitAddWorker = async function() {
  const first_name = document.getElementById('new-worker-first').value.trim();
  const last_name = document.getElementById('new-worker-last').value.trim();
  const username = document.getElementById('new-worker-username').value.trim();
  const password = document.getElementById('new-worker-password').value.trim();

  if (!username || !password) {
    tgAlert('Username and password are required.');
    return;
  }

  try {
    await api.createStationWorker({ username, password, first_name, last_name });
    tgAlert(`Account created for ${first_name || username}.`);
    showScreen('screen-station-workers');
    await showStationWorkers();
  } catch (e) {
    tgAlert(e.message);
  }
};

// ── Change Password ───────────────────────────────────────────────────────────

window.submitChangePassword = async function() {
  const old_password = document.getElementById('old-password').value;
  const new_password = document.getElementById('new-password').value;
  const confirm = document.getElementById('confirm-password').value;

  if (new_password !== confirm) {
    tgAlert('New passwords do not match.');
    return;
  }

  try {
    await api.changePassword(old_password, new_password);
    tgAlert('Password changed successfully.');
    document.getElementById('old-password').value = '';
    document.getElementById('new-password').value = '';
    document.getElementById('confirm-password').value = '';
    showScreen('screen-tickets');
  } catch (e) {
    tgAlert(e.message);
  }
};

// ── Photo preview ─────────────────────────────────────────────────────────────

document.addEventListener('change', function(e) {
  if (e.target.id !== 'comment-photos') return;
  const preview = document.getElementById('comment-photo-preview');
  if (!preview) return;
  preview.innerHTML = '';
  [...e.target.files].forEach(file => {
    const img = document.createElement('img');
    img.className = 'comment-photo';
    img.src = URL.createObjectURL(file);
    preview.appendChild(img);
  });
});

window.openPhoto = function(src) {
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.9);z-index:999;display:flex;align-items:center;justify-content:center;';
  overlay.innerHTML = `<img src="${src}" style="max-width:100%;max-height:100%;object-fit:contain;">`;
  overlay.onclick = () => overlay.remove();
  document.body.appendChild(overlay);
};

// ── IT Manager: Staff Management ──────────────────────────────────────────────

let currentManageType = null;

const MANAGE_CONFIG = {
  it_worker:       { title: 'IT Workers',       addTitle: 'Add IT Worker',       apiGet: () => api.getManageITWorkers(),       apiAdd: (d) => api.addManageITWorker(d),       apiRemove: (id) => api.removeManageITWorker(id) },
  supply_worker:   { title: 'Supply Workers',    addTitle: 'Add Supply Worker',   apiGet: () => api.getManageSupplyWorkers(),   apiAdd: (d) => api.addManageSupplyWorker(d),   apiRemove: (id) => api.removeManageSupplyWorker(id) },
  station_manager: { title: 'Station Managers',  addTitle: 'Add Station Manager', apiGet: () => api.getManageStationManagers(), apiAdd: (d) => api.addManageStationManager(d), apiRemove: (id) => api.removeManageStationManager(id) },
};

window.showManageSection = async function(type) {
  currentManageType = type;
  const cfg = MANAGE_CONFIG[type];
  document.getElementById('manage-staff-title').textContent = cfg.title;
  showScreen('screen-manage-staff');

  const list = document.getElementById('manage-staff-list');
  list.innerHTML = '<div class="loading">Loading...</div>';
  try {
    const staff = await cfg.apiGet();
    if (!staff.length) {
      list.innerHTML = '<div class="empty">No staff yet.</div>';
      return;
    }
    list.innerHTML = staff.map(u => `
      <div class="card" style="display:flex;align-items:center;justify-content:space-between">
        <div>
          <div class="card-title">${escHtml(u.name)}</div>
          <div class="card-meta">@${escHtml(u.username)} · ${u.is_active ? 'Active' : '<span style="color:#dc3545">Deactivated</span>'}</div>
        </div>
        ${u.is_active ? `<button class="btn btn-danger" style="width:auto;padding:6px 12px;font-size:13px" onclick="removeManageStaff(${u.id}, '${escHtml(u.name)}')">Remove</button>` : ''}
      </div>
    `).join('');
  } catch (e) {
    list.innerHTML = `<div class="empty">Error: ${e.message}</div>`;
  }
};

window.removeManageStaff = async function(id, name) {
  const confirmed = await tgConfirm(`Deactivate ${name}?`);
  if (!confirmed) return;
  try {
    await MANAGE_CONFIG[currentManageType].apiRemove(id);
    await showManageSection(currentManageType);
  } catch (e) {
    tgAlert(e.message);
  }
};

window.showAddStaff = async function() {
  const cfg = MANAGE_CONFIG[currentManageType];
  document.getElementById('add-staff-title').textContent = cfg.addTitle;
  document.getElementById('add-staff-first').value = '';
  document.getElementById('add-staff-last').value = '';
  document.getElementById('add-staff-username').value = '';
  document.getElementById('add-staff-password').value = '';

  const stationField = document.getElementById('add-staff-station-field');
  const companyField = document.getElementById('add-staff-company-field');
  stationField.style.display = 'none';
  companyField.style.display = 'none';

  if (currentManageType === 'station_manager') {
    try {
      const stations = await api.getManageStations();
      const select = document.getElementById('add-staff-station');
      select.innerHTML = stations.map(s => `<option value="${s.id}">${escHtml(s.name)}</option>`).join('');
      stationField.style.display = '';
    } catch (e) {
      tgAlert('Could not load stations: ' + e.message);
      return;
    }
  } else if (currentUser.companies && currentUser.companies.length > 1) {
    const select = document.getElementById('add-staff-company');
    select.innerHTML = currentUser.companies.map(c => `<option value="${c.id}">${escHtml(c.name)}</option>`).join('');
    companyField.style.display = '';
  }

  showScreen('screen-add-staff');
};

window.submitAddStaff = async function() {
  const username = document.getElementById('add-staff-username').value.trim();
  const password = document.getElementById('add-staff-password').value.trim();
  const first_name = document.getElementById('add-staff-first').value.trim();
  const last_name = document.getElementById('add-staff-last').value.trim();

  if (!username || !password) {
    tgAlert('Username and password are required.');
    return;
  }

  const data = { username, password, first_name, last_name };

  if (currentManageType === 'station_manager') {
    data.station_id = document.getElementById('add-staff-station').value;
  } else {
    const companyField = document.getElementById('add-staff-company-field');
    if (companyField.style.display !== 'none') {
      data.company_id = document.getElementById('add-staff-company').value;
    }
  }

  try {
    await MANAGE_CONFIG[currentManageType].apiAdd(data);
    tgAlert(`Account created for ${first_name || username}.`);
    showScreen('screen-manage-staff');
    await showManageSection(currentManageType);
  } catch (e) {
    tgAlert(e.message);
  }
};

// ── Station Deputies ──────────────────────────────────────────────────────────

window.showStationDeputies = async function() {
  showScreen('screen-station-deputies');
  const list = document.getElementById('station-deputies-list');
  list.innerHTML = '<div class="loading">Loading...</div>';

  try {
    const deputies = await api.getStationDeputies();
    if (!deputies.length) {
      list.innerHTML = '<div class="empty">No deputies yet.</div>';
      return;
    }
    list.innerHTML = deputies.map(d => `
      <div class="card" style="display:flex;align-items:center;justify-content:space-between">
        <div>
          <div class="card-title">${escHtml(d.name)}</div>
          <div class="card-meta">@${escHtml(d.username)} · ${d.is_active ? 'Active' : '<span style="color:#dc3545">Deactivated</span>'}</div>
        </div>
        ${d.is_active ? `<button class="btn btn-danger" style="width:auto;padding:6px 12px;font-size:13px" onclick="removeDeputy(${d.id}, '${escHtml(d.name)}')">Remove</button>` : ''}
      </div>
    `).join('');
  } catch (e) {
    list.innerHTML = `<div class="empty">Error: ${e.message}</div>`;
  }
};

window.removeDeputy = async function(id, name) {
  const confirmed = await tgConfirm(`Remove deputy ${name}? They will become a regular worker.`);
  if (!confirmed) return;
  try {
    await api.removeStationDeputy(id);
    await showStationDeputies();
  } catch (e) {
    tgAlert(e.message);
  }
};

window.showAddDeputy = async function() {
  document.getElementById('deputy-type').value = 'promote';
  document.getElementById('deputy-promote-section').style.display = '';
  document.getElementById('deputy-new-section').style.display = 'none';
  document.getElementById('deputy-notes') && (document.getElementById('deputy-notes').value = '');

  // populate worker select
  try {
    const workers = await api.getStationWorkers();
    const active = workers.filter(w => w.is_active);
    const select = document.getElementById('deputy-worker-select');
    if (!active.length) {
      tgAlert('No active workers to promote.');
      return;
    }
    select.innerHTML = active.map(w => `<option value="${w.id}">${escHtml(w.name)} (@${escHtml(w.username)})</option>`).join('');
  } catch (e) {
    tgAlert('Could not load workers: ' + e.message);
    return;
  }

  showScreen('screen-add-deputy');
};

window.toggleDeputyType = function(value) {
  document.getElementById('deputy-promote-section').style.display = value === 'promote' ? '' : 'none';
  document.getElementById('deputy-new-section').style.display = value === 'new' ? '' : 'none';
};

window.submitPromoteDeputy = async function() {
  const workerId = document.getElementById('deputy-worker-select').value;
  if (!workerId) { tgAlert('Please select a worker.'); return; }
  try {
    await api.addStationDeputy({ worker_id: parseInt(workerId) });
    tgAlert('Worker promoted to deputy.');
    showScreen('screen-station-deputies');
    await showStationDeputies();
  } catch (e) {
    tgAlert(e.message);
  }
};

window.submitCreateDeputy = async function() {
  const username = document.getElementById('deputy-username').value.trim();
  const password = document.getElementById('deputy-password').value.trim();
  const first_name = document.getElementById('deputy-first').value.trim();
  const last_name = document.getElementById('deputy-last').value.trim();

  if (!username || !password) { tgAlert('Username and password are required.'); return; }

  try {
    await api.addStationDeputy({ username, password, first_name, last_name });
    tgAlert(`Deputy account created for ${first_name || username}.`);
    showScreen('screen-station-deputies');
    await showStationDeputies();
  } catch (e) {
    tgAlert(e.message);
  }
};

// ── Start ─────────────────────────────────────────────────────────────────────

init();
