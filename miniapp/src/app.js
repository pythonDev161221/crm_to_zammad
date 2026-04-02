import { api, setToken } from '/static/api.js?v=18';

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
let screenHistory = [];
let ticketPollInterval = null;
let listPollInterval = null;
let currentStationId = null;

// ── Router ────────────────────────────────────────────────────────────────────

window.showScreen = function(id) {
  const current = document.querySelector('.screen.active');
  const currentId = current?.id;
  if (currentId === 'screen-ticket-detail' && id !== 'screen-ticket-detail') {
    clearInterval(ticketPollInterval);
    ticketPollInterval = null;
  }
  if (currentId === 'screen-tickets' && id !== 'screen-tickets') {
    clearInterval(listPollInterval);
    listPollInterval = null;
  }
  if (currentId && currentId !== id) screenHistory.push(currentId);
  if (id === 'screen-tickets') screenHistory = [];
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  const screen = document.getElementById(id);
  if (screen) screen.classList.add('active');
  if (inTelegram) {
    if (screenHistory.length > 0) tg.BackButton.show();
    else tg.BackButton.hide();
  }
}

window.goBack = function() {
  if (screenHistory.length === 0) return;
  const current = document.querySelector('.screen.active');
  if (current?.id === 'screen-ticket-detail') {
    clearInterval(ticketPollInterval);
    ticketPollInterval = null;
  }
  if (current?.id === 'screen-tickets') {
    clearInterval(listPollInterval);
    listPollInterval = null;
  }
  const prev = screenHistory.pop();
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  const screen = document.getElementById(prev);
  if (screen) screen.classList.add('active');
  if (inTelegram) {
    if (screenHistory.length > 0) tg.BackButton.show();
    else tg.BackButton.hide();
  }
}

// ── Accordion ─────────────────────────────────────────────────────────────────

function openAccordion(id) {
  const body = document.getElementById(id);
  const arrow = document.getElementById(id + '-arrow');
  if (body) { body.style.display = ''; }
  if (arrow) { arrow.innerHTML = '&#8964;'; }
}

window.toggleAccordion = function(id) {
  const body = document.getElementById(id);
  const arrow = document.getElementById(id + '-arrow');
  if (!body) return;
  const open = body.style.display !== 'none';
  body.style.display = open ? 'none' : '';
  if (arrow) arrow.innerHTML = open ? '&#8250;' : '&#8964;';
};

// ── Auth ──────────────────────────────────────────────────────────────────────

async function init() {
  if (inTelegram) {
    tg.ready();
    tg.expand();
    tg.BackButton.hide();
    tg.BackButton.onClick(goBack);
  }

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

    // Check for invite link (startapp=inv_TOKEN)
    // Try all possible locations Telegram may place start_param
    const startParam = tg?.initDataUnsafe?.start_param
      || new URLSearchParams(initData).get('start_param')
      || new URLSearchParams(window.location.hash.slice(1)).get('tgWebAppStartParam')
      || '';
    if (startParam.startsWith('inv_')) {
      const inviteToken = startParam.slice(4);
      // Check if already registered
      const auth = await api.telegramAuth(initData);
      if (!auth.needs_linking) {
        // Already has an account — log them in normally
        setToken(auth.access, auth.refresh);
        currentUser = auth.user;
        await loadTickets();
        return;
      }
      // New user — show registration screen with invite panel open
      document.getElementById('register-token').value = inviteToken;
      const tgUser = tg?.initDataUnsafe?.user || {};
      document.getElementById('register-first').value = tgUser.first_name || '';
      document.getElementById('register-last').value = tgUser.last_name || '';
      showScreen('screen-link-account');
      openAccordion('accordion-invite');
      return;
    }

    const auth = await api.telegramAuth(initData);
    if (auth.needs_linking) {
      if (auth.inactive) {
        const notice = document.getElementById('link-account-inactive-notice');
        if (notice) notice.style.display = '';
      }
      showScreen('screen-link-account');
      return;
    }
    setToken(auth.access, auth.refresh);
    currentUser = auth.user;
    if (currentUser.role === 'it_manager' || currentUser.role === 'it_deputy') {
      currentUser.companies = await api.getMyCompanies().catch(() => []);
    }
    await loadTickets();
    promptPhoneIfMissing();
  } catch (e) {
    showError(t('error_auth') + e.message);
  }
}

window.showRegisterFromLink = function() {
  document.getElementById('register-token').value = '';
  document.getElementById('register-first').value = '';
  document.getElementById('register-last').value = '';
  openAccordion('accordion-invite');
};

window.submitRegister = async function() {
  const tokenInput = document.getElementById('register-token').value.trim();
  // Support full invite URL or just the token
  const token = tokenInput.includes('inv_')
    ? tokenInput.split('inv_').pop().split(/[^a-zA-Z0-9_-]/)[0]
    : tokenInput;
  const first_name = document.getElementById('register-first').value.trim();
  const last_name = document.getElementById('register-last').value.trim();

  if (!token) { tgAlert(t('msg_enter_token')); return; }
  if (!first_name) { tgAlert(t('msg_enter_first_name')); return; }

  const initData = tg?.initData || '';
  try {
    const auth = await api.registerWithInvite(initData, token, first_name, last_name);
    setToken(auth.access, auth.refresh);
    currentUser = auth.user;
    await loadTickets();
    promptPhoneIfMissing();
  } catch (e) {
    tgAlert(e.message);
  }
};

window.submitLinkAccount = async function() {
  const username = document.getElementById('link-username').value.trim();
  const password = document.getElementById('link-password').value;
  if (!username || !password) { tgAlert(t('msg_enter_username_password')); return; }

  const initData = tg?.initData || '';
  try {
    const auth = await api.linkAccount(initData, username, password);
    setToken(auth.access, auth.refresh);
    currentUser = auth.user;
    if (currentUser.role === 'it_manager' || currentUser.role === 'it_deputy') {
      currentUser.companies = await api.getMyCompanies().catch(() => []);
    }
    promptPhoneIfMissing();
    await loadTickets();
  } catch (e) {
    tgAlert(e.message);
  }
};

// ── Ticket List ───────────────────────────────────────────────────────────────

async function loadTickets() {
  showScreen('screen-tickets');
  const list = document.getElementById('tickets-list');
  list.innerHTML = `<div class="loading">${t('loading')}</div>`;

  try {
    const tickets = await api.getTickets();
    renderTicketList(tickets);
  } catch (e) {
    list.innerHTML = `<div class="empty">${t('error_general')}${e.message}</div>`;
  }

  clearInterval(listPollInterval);
  listPollInterval = setInterval(async () => {
    try {
      const tickets = await api.getTickets();
      const active = document.querySelector('.screen.active');
      if (active?.id === 'screen-tickets') renderTicketList(tickets);
    } catch (_) {}
  }, 5000);
}

function renderTicketList(tickets) {
  const list = document.getElementById('tickets-list');
  const role = currentUser.role;

  const fab = document.getElementById('fab-new-ticket');
  fab.style.display = (role === 'worker' || role === 'station_manager' || role === 'deputy') ? 'flex' : 'none';

  const btnStation = document.getElementById('btn-station');
  btnStation.style.display = (role === 'station_manager' || role === 'deputy') ? 'inline' : 'none';

  const btnManage = document.getElementById('btn-manage');
  btnManage.style.display = (role === 'it_manager' || role === 'it_deputy') ? 'inline' : 'none';
  const itOnlyCards = ['manage-card-it-worker', 'manage-card-supply-worker'];
  itOnlyCards.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = role === 'it_manager' ? '' : 'none';
  });

  const unrated = role === 'worker' ? tickets.filter(t => t.status === 'resolved' && t.rating === null) : [];
  const active = role === 'worker' ? tickets.filter(t => t.status !== 'resolved') : tickets;

  if (!active.length && !unrated.length) {
    list.innerHTML = `<div class="empty">${t('msg_no_tickets')}</div>`;
    return;
  }

  let html = '';

  if (unrated.length) {
    html += `<div style="padding:8px 16px 4px;font-size:13px;font-weight:600;color:var(--hint)">${t('section_pending_rating')}</div>`;
    html += unrated.map(tk => `
      <div class="card" onclick="openRateTicket(${tk.id}, '${escHtml(tk.title).replace(/'/g, "\\'")}')">
        <div class="card-title">${escHtml(tk.title)}</div>
        <div class="card-meta" style="color:var(--button)">&#9733; ${t('btn_rate_resolution')}</div>
      </div>
    `).join('');
  }

  if (active.length) {
    if (unrated.length) html += `<div style="padding:8px 16px 4px;font-size:13px;font-weight:600;color:var(--hint)">${t('section_active')}</div>`;

    const isIT = role === 'it_worker' || role === 'it_manager' || role === 'it_deputy';
    const myTickets = isIT ? active.filter(tk => tk.has_my_task) : [];
    const otherTickets = isIT ? active.filter(tk => !tk.has_my_task) : active;

    if (isIT && myTickets.length) {
      html += `<div style="padding:8px 16px 4px;font-size:13px;font-weight:600;color:var(--hint)">${t('section_my_tasks')}</div>`;
    }

    const renderCard = tk => `
      <div class="card" onclick="openTicket(${tk.id})">
        <div class="card-title">${escHtml(tk.title)}</div>
        ${role !== 'worker' && (tk.station_name || tk.company_name) ? `
          <div class="card-meta" style="margin-top:2px">${[tk.station_name, tk.company_name].filter(Boolean).map(escHtml).join(' · ')}</div>
        ` : ''}
        <div class="card-meta">
          <span class="badge badge-${tk.status}">${formatStatus(tk.status)}</span>
          &nbsp;${formatDate(tk.created_at)}
        </div>
        ${role !== 'worker' ? `<div class="card-meta" style="margin-top:4px">${tk.tasks?.length || 0} ${t('msg_tasks_count')}</div>` : ''}
      </div>
    `;

    html += myTickets.map(renderCard).join('');

    if (isIT && otherTickets.length) {
      html += `<div style="padding:8px 16px 4px;font-size:13px;font-weight:600;color:var(--hint)">${t('section_other_tickets')}</div>`;
    }

    html += otherTickets.map(renderCard).join('');
  }

  list.innerHTML = html;
}

// ── Ticket Detail ─────────────────────────────────────────────────────────────

window.openTicket = async function(id) {
  showScreen('screen-ticket-detail');
  const body = document.getElementById('ticket-detail-body');
  body.innerHTML = `<div class="loading">${t('loading')}</div>`;

  try {
    const ticket = await api.getTicket(id);
    renderTicketDetail(ticket);
  } catch (e) {
    body.innerHTML = `<div class="empty">${t('error_general')}${e.message}</div>`;
    return;
  }

  clearInterval(ticketPollInterval);
  ticketPollInterval = setInterval(async () => {
    try {
      const updated = await api.getTicket(id);
      const section = document.getElementById('comments-section');
      if (section) section.innerHTML = renderComments(updated.comments);
    } catch (_) {}
  }, 5000);
};

function renderTicketDetail(ticket) {
  const header = document.getElementById('ticket-detail-title');
  header.textContent = ticket.title;

  const body = document.getElementById('ticket-detail-body');
  const role = currentUser.role;
  const isITWorker = role === 'it_worker' || role === 'it_deputy' || role === 'it_manager' || role === 'admin';
  const isSupplyWorker = role === 'supply_worker';
  const isManager = role === 'station_manager' || role === 'deputy';
  const canComment = !isManager;
  const myTask = ticket.tasks?.find(t => t.assigned_to === currentUser.id && t.status !== 'cancelled');

  body.innerHTML = `
    <div class="detail-body">
      <!-- Status -->
      <div class="detail-section">
        <span class="badge badge-${ticket.status}">${formatStatus(ticket.status)}</span>
        <span style="color:var(--hint);font-size:13px;margin-left:8px">by ${escHtml(ticket.created_by_name)}</span>
        ${(isITWorker || isSupplyWorker) && ticket.created_by_phone ? `
          <a href="https://t.me/${encodeURIComponent(ticket.created_by_phone)}" style="display:inline-block;margin-left:8px;font-size:13px;color:var(--button)">&#128222; ${escHtml(ticket.created_by_phone)}</a>
        ` : ''}
        ${(ticket.station_name || ticket.company_name) ? `
          <div style="margin-top:6px;font-size:13px;color:var(--hint)">${[ticket.station_name, ticket.company_name].filter(Boolean).map(escHtml).join(' · ')}</div>
        ` : ''}
      </div>

      <!-- Description -->
      ${ticket.description || ticket.photos?.length ? `
        <div class="detail-section">
          ${ticket.description ? `<h3>${t('section_description')}</h3><div class="description-text">${escHtml(ticket.description)}</div>` : ''}
          ${ticket.photos?.length ? `
            <div class="comment-photos" style="margin-top:${ticket.description ? '10px' : '0'}">
              ${ticket.photos.map(p => `<img class="comment-photo" src="${p.image}" onclick="openPhoto('${p.image}')">`).join('')}
            </div>` : ''}
        </div>` : ''}

      <!-- Tasks -->
      ${isITWorker ? `
        <div class="detail-section">
          <h3>${t('section_tasks')}</h3>
          ${ticket.tasks?.length ? ticket.tasks.map(tk => `
            <div class="ticket-card" style="${tk.status === 'cancelled' ? 'opacity:0.5' : ''}">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <div class="ticket-worker">${escHtml(tk.assigned_to_name)}</div>
                <span class="badge badge-${tk.status}">${formatStatus(tk.status)}</span>
              </div>
              ${tk.notes ? `<div class="ticket-notes">${escHtml(tk.notes)}</div>` : ''}
              ${tk.assigned_to === currentUser.id ? renderTaskActions(tk) : ''}
              ${tk.created_by === currentUser.id && tk.assigned_to !== currentUser.id && tk.status !== 'done' && tk.status !== 'cancelled' ? `
                <button class="btn btn-secondary" style="margin-top:8px;color:var(--destructive,#e53935)" onclick="cancelTask(${tk.id})">${t('btn_cancel_task')}</button>
              ` : ''}
            </div>
          `).join('') : `<div class="empty" style="padding:10px">${t('msg_no_tasks')}</div>`}
        </div>` : ''}
      ${isSupplyWorker && myTask ? `
        <div class="detail-section">
          <h3>${t('section_my_task')}</h3>
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
        <h3>${t('section_comments')}</h3>
        ${renderComments(ticket.comments)}
      </div>
    </div>

    <!-- Comment input (not for station managers) -->
    ${canComment ? `
    <div class="comment-input-area">
      ${isITWorker ? `
        <div class="comment-internal-toggle">
          <label><input type="checkbox" id="comment-internal"> ${t('section_internal')}</label>
        </div>` : ''}
      <div class="comment-input-row">
        <input id="comment-input" type="text" placeholder="${t('placeholder_comment')}">
        <label class="comment-photo-btn" title="Attach photo">
          &#128247;
          <input type="file" id="comment-photos" accept="image/*" multiple style="display:none">
        </label>
        <button id="btn-submit-comment" onclick="submitComment(${ticket.id})">&#10148;</button>
      </div>
      <div id="comment-photo-preview" class="comment-photo-preview"></div>
    </div>` : ''}

    <!-- Worker rating (for resolved unrated tickets) -->
    ${role === 'worker' && ticket.status === 'resolved' && ticket.rating === null ? `
      <div style="padding:0 16px 16px">
        <button class="btn btn-primary" onclick="openRateTicket(${ticket.id}, '${escHtml(ticket.title).replace(/'/g, "\\'")}'">${t('btn_rate_resolution')}</button>
      </div>
    ` : ''}

    <!-- IT Worker actions -->
    ${isITWorker && ticket.status !== 'resolved' ? `
      <div style="padding:0 16px 16px;display:flex;flex-direction:column;gap:8px">
        ${!ticket.tasks?.find(tk => tk.status !== 'cancelled') ? `
          <button class="btn btn-primary" onclick="assignSelf(${ticket.id})">${t('btn_take_ticket')}</button>
        ` : ''}
        ${myTask && myTask.status !== 'done' ? `
          <button class="btn btn-secondary" onclick="showDelegateForm(${ticket.id})">${t('btn_delegate_ticket')}</button>
        ` : ''}
        ${canResolve(ticket) ? `
          <button class="btn btn-danger" onclick="resolveTicket(${ticket.id})">${t('btn_mark_resolved')}</button>
        ` : ''}
      </div>
    ` : ''}
  `;

  document.getElementById('screen-ticket-detail').dataset.ticketId = ticket.id;
}

function renderTaskActions(task) {
  if (task.status === 'done') return '';
  const next = task.status === 'open' ? 'in_progress' : 'done';
  const label = next === 'in_progress' ? t('btn_start_working') : t('btn_mark_done');
  return `<button class="btn btn-primary" style="margin-top:8px" onclick="updateTask(${task.id}, '${next}')">
    ${label}
  </button>`;
}

function renderComments(comments) {
  if (!comments?.length) return `<div class="empty" style="padding:10px">${t('msg_no_comments')}</div>`;
  return comments.map(c => `
    <div class="comment ${c.is_internal ? 'comment-internal' : ''}">
      <div class="comment-author">
        ${escHtml(c.author_name)}
        ${c.is_internal ? `<span class="comment-internal-badge">${t('section_internal_badge')}</span>` : ''}
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
  const active = ticket.tasks?.filter(t => t.status !== 'cancelled') ?? [];
  if (!active.length) return false;
  return active.every(t => t.status === 'done');
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

window.cancelTask = async function(taskId) {
  try {
    await api.cancelTask(taskId);
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
  const confirmed = await tgConfirm(t('confirm_mark_resolved'));
  if (!confirmed) return;
  const btn = document.querySelector(`button[onclick="resolveTicket(${ticketId})"]`);
  const originalText = btn?.textContent;
  if (btn) { btn.disabled = true; btn.textContent = '...'; }
  try {
    await api.resolveTicket(ticketId);
    tgAlert(t('confirm_ticket_resolved'));
    await loadTickets();
    showScreen('screen-tickets');
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = originalText; }
    tgAlert(e.message);
  }
};

let selectedStarRating = null;

window.openRateTicket = function(ticketId, title) {
  selectedStarRating = null;
  document.getElementById('rate-ticket-id').value = ticketId;
  document.getElementById('rate-ticket-title').textContent = title;
  document.querySelectorAll('.star').forEach(s => s.style.opacity = '0.3');
  showScreen('screen-rate-ticket');
};

window.selectStar = function(value) {
  selectedStarRating = value;
  document.querySelectorAll('.star').forEach(s => {
    s.style.opacity = parseInt(s.dataset.value) <= value ? '1' : '0.3';
  });
};

window.submitRating = async function() {
  if (!selectedStarRating) { tgAlert(t('msg_please_rate')); return; }
  const ticketId = document.getElementById('rate-ticket-id').value;
  try {
    await api.rateTicket(parseInt(ticketId), selectedStarRating);
    await loadTickets();
  } catch (e) {
    tgAlert(e.message);
  }
};

window.submitNotResolved = async function() {
  const ticketId = document.getElementById('rate-ticket-id').value;
  const confirmed = await tgConfirm(t('confirm_mark_not_resolved'));
  if (!confirmed) return;
  try {
    await api.rateTicket(parseInt(ticketId), 0);
    await loadTickets();
  } catch (e) {
    tgAlert(e.message);
  }
};

window.submitComment = async function(ticketId) {
  const btn = document.getElementById('btn-submit-comment');
  if (btn && btn.disabled) return;

  const input = document.getElementById('comment-input');
  const text = input.value.trim();
  const photoInput = document.getElementById('comment-photos');
  const photos = photoInput ? [...photoInput.files] : [];
  const isInternal = document.getElementById('comment-internal')?.checked || false;

  if (!text && !photos.length) return;

  if (btn) btn.disabled = true;
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
    if (btn) btn.disabled = false;
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
  list.innerHTML = `<div class="empty">${t('loading')}</div>`;

  try {
    const workers = await api.getITWorkers(ticketId);
    if (!workers.length) {
      list.innerHTML = `<div class="empty">${t('msg_no_other_it_workers')}</div>`;
      return;
    }
    list.innerHTML = workers.map(w => `
      <div class="card" id="delegate-worker-${w.id}" onclick="selectWorker(${w.id}, '${escHtml(w.name)}')">
        <div class="card-title">🔧 ${escHtml(w.name)}</div>
      </div>
    `).join('');
  } catch (e) {
    list.innerHTML = `<div class="empty">${t('error_general')}${e.message}</div>`;
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
    tgAlert(t('msg_select_worker'));
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
      tgAlert(t('error_general') + e.message);
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
  const btn = document.getElementById('btn-submit-ticket');
  if (btn.disabled) return;

  const title = document.getElementById('new-ticket-title').value.trim();
  const description = document.getElementById('new-ticket-desc').value.trim();
  const photoInput = document.getElementById('new-ticket-photos');
  const photos = photoInput ? [...photoInput.files] : [];

  if (!title) {
    tgAlert(t('msg_enter_title'));
    return;
  }

  let stationId = null;
  if (currentUser.role === 'station_manager') {
    const stationField = document.getElementById('station-select-field');
    if (stationField.style.display !== 'none') {
      stationId = document.getElementById('new-ticket-station').value;
    }
  }

  btn.disabled = true;
  try {
    await api.createTicket(title, description, photos, stationId);
    await loadTickets();
    showScreen('screen-tickets');
  } catch (e) {
    btn.disabled = false;
    tgAlert(e.message);
  }
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function escHtml(str) {
  if (!str) return '';
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function formatStatus(s) {
  return { open: t('status_open'), in_progress: t('status_in_progress'), done: t('status_done'), resolved: t('status_resolved') }[s] || s;
}

function formatDate(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function formatRole(role) {
  return {
    worker: t('role_worker'), station_manager: t('role_station_manager'), deputy: t('role_deputy'),
    it_worker: t('role_it_worker'), it_manager: t('role_it_manager'), it_deputy: t('role_it_deputy'),
    supply_worker: t('role_supply_worker'), admin: t('role_admin'),
  }[role] || role;
}

window.sharePhone = function() {
  if (!inTelegram || !tg.requestContact) {
    tgAlert(t('msg_phone_only_telegram'));
    return;
  }
  tg.requestContact(async (sent, event) => {
    if (!sent) return;
    const phone = event?.responseUnsafe?.contact?.phone_number
      || event?.contact?.phone_number;
    if (!phone) return;
    try {
      await api.updateMe({ phone });
      currentUser.phone = phone;
      await showProfile();
    } catch (e) {
      tgAlert(t('msg_could_not_save_phone') + e.message);
    }
  });
};

async function promptPhoneIfMissing() {
  if (!inTelegram || !tg.requestContact) return;
  try {
    const me = await api.getMe();
    if (me.phone) return;
    tg.requestContact(async (sent, event) => {
      if (!sent) return;
      const phone = event?.responseUnsafe?.contact?.phone_number
        || event?.contact?.phone_number;
      if (!phone) return;
      try {
        await api.updateMe({ phone });
        if (currentUser) currentUser.phone = phone;
      } catch (_) {}
    });
  } catch (_) {}
}

window.showProfile = async function() {
  showScreen('screen-profile');
  try {
    const me = await api.getMe();
    document.getElementById('profile-name').textContent =
      [me.first_name, me.last_name].filter(Boolean).join(' ') || me.username;
    document.getElementById('profile-role').textContent = formatRole(me.role);
    const stationEl = document.getElementById('profile-station');
    const parts = [];
    if (me.station_name) parts.push(me.station_name);
    if (me.company_names?.length) parts.push(me.company_names.join(', '));
    stationEl.textContent = parts.join(' · ');
    stationEl.style.display = parts.length ? '' : 'none';
    const phoneRow = document.getElementById('profile-phone-row');
    const shareRow = document.getElementById('profile-share-phone-row');
    if (me.phone) {
      phoneRow.style.display = '';
      document.getElementById('profile-phone-value').innerHTML =
        `<a href="https://t.me/${encodeURIComponent(me.phone)}" style="color:var(--button)">${escHtml(me.phone)}</a>`;
      if (shareRow) shareRow.style.display = 'none';
    } else {
      phoneRow.style.display = 'none';
      if (shareRow) shareRow.style.display = inTelegram && tg.requestContact ? '' : 'none';
    }
  } catch (e) {
    tgAlert(t('msg_could_not_load_profile') + e.message);
  }
};

function showError(msg) {
  app.innerHTML = `<div class="loading" style="flex-direction:column;gap:8px">
    <div>⚠️</div><div>${escHtml(msg)}</div>
  </div>`;
}

// ── Station Select ────────────────────────────────────────────────────────────

window.showStationOrSelect = async function() {
  try {
    const stations = await api.getMyStations();
    if (stations.length === 1) {
      currentStationId = stations[0].id;
      showStationHub(stations[0].name);
    } else {
      showScreen('screen-station-select');
      const list = document.getElementById('station-select-list');
      list.innerHTML = stations.map(s => `
        <div class="card" style="cursor:pointer" onclick="selectStation(${s.id}, '${escHtml(s.name)}')">
          <div class="card-title">${escHtml(s.name)}</div>
        </div>
      `).join('');
    }
  } catch (e) {
    tgAlert(t('error_general') + e.message);
  }
};

window.selectStation = function(id, name) {
  currentStationId = id;
  showStationHub(name);
};

function showStationHub(name) {
  document.getElementById('station-name').textContent = name;
  const isManager = currentUser.role === 'station_manager';
  document.getElementById('hub-deputies-card').style.display = isManager ? '' : 'none';
  showScreen('screen-station-hub');
}

// ── Station Workers ───────────────────────────────────────────────────────────

window.showStationWorkers = async function() {
  showScreen('screen-station-workers');
  const isManager = currentUser.role === 'station_manager';
  const btnInvite = document.getElementById('btn-invite');
  if (btnInvite) btnInvite.style.display = isManager ? 'inline' : 'none';

  const list = document.getElementById('station-workers-list');
  list.innerHTML = `<div class="loading">${t('loading')}</div>`;

  try {
    const workers = await api.getStationWorkers(currentStationId);
    if (!workers.length) {
      list.innerHTML = `<div class="empty">${t('msg_no_workers')}</div>`;
      return;
    }
    list.innerHTML = workers.map(w => `
      <div class="card" style="display:flex;align-items:center;justify-content:space-between">
        <div>
          <div class="card-title">${escHtml(w.name)}</div>
          <div class="card-meta">@${escHtml(w.username)} · ${w.is_active ? t('status_active') : `<span style="color:#dc3545">${t('status_deactivated')}</span>`}</div>
        </div>
        ${w.is_active && isManager ? `
          <div style="display:flex;flex-direction:column;gap:4px">
            <button class="btn btn-secondary" style="width:auto;padding:4px 10px;font-size:12px" onclick="promoteToDeputy(${w.id}, '${escHtml(w.name)}')">${t('btn_deputy')}</button>
            <button class="btn btn-danger" style="width:auto;padding:4px 10px;font-size:12px" onclick="removeWorker(${w.id}, '${escHtml(w.name)}')">${t('btn_remove')}</button>
          </div>
        ` : w.is_active ? `<button class="btn btn-danger" style="width:auto;padding:6px 12px;font-size:13px" onclick="removeWorker(${w.id}, '${escHtml(w.name)}')">${t('btn_remove')}</button>` : ''}
      </div>
    `).join('');
  } catch (e) {
    list.innerHTML = `<div class="empty">${t('error_general')}${e.message}</div>`;
  }
};

window.promoteToDeputy = async function(id, name) {
  const confirmed = await tgConfirm(t('confirm_promote_deputy', { name }));
  if (!confirmed) return;
  try {
    await api.addStationDeputy({ worker_id: id, station_id: currentStationId });
    tgAlert(name + t('msg_is_now_deputy'));
    await showStationWorkers();
  } catch (e) {
    tgAlert(e.message);
  }
};

// ── Invite Link ───────────────────────────────────────────────────────────────

let currentInviteStationId = null;
let currentInviteLink = null;

window.showInviteLink = async function() {
  showScreen('screen-station-invite');
  currentInviteStationId = null;
  currentInviteLink = null;

  const stationField = document.getElementById('invite-station-field');
  stationField.style.display = 'none';

  try {
    const stations = await api.getMyStations();
    if (stations.length > 1) {
      const select = document.getElementById('invite-station-select');
      select.innerHTML = stations.map(s => `<option value="${s.id}">${escHtml(s.name)}</option>`).join('');
      stationField.style.display = '';
      select.onchange = () => loadInviteLink(parseInt(select.value));
      currentInviteStationId = stations[0].id;
    } else if (stations.length === 1) {
      currentInviteStationId = stations[0].id;
    }
    if (currentInviteStationId) await loadInviteLink(currentInviteStationId);
  } catch (e) {
    tgAlert(t('error_general') + e.message);
  }
};

async function loadInviteLink(stationId) {
  currentInviteStationId = stationId;
  const linkBox = document.getElementById('invite-link-box');
  const noLink = document.getElementById('invite-no-link');
  try {
    const data = await api.getStationInvite(stationId);
    if (data.link) {
      currentInviteLink = data.link;
      document.getElementById('invite-link-text').textContent = data.link;
      linkBox.style.display = '';
      noLink.style.display = 'none';
    } else {
      currentInviteLink = null;
      linkBox.style.display = 'none';
      noLink.style.display = '';
    }
  } catch (e) {
    tgAlert(t('error_general') + e.message);
  }
}

window.copyInviteLink = function() {
  if (!currentInviteLink) return;
  navigator.clipboard.writeText(currentInviteLink)
    .then(() => tgAlert(t('msg_link_copied')))
    .catch(() => tgAlert(currentInviteLink));
};

window.generateInviteLink = async function() {
  try {
    const data = await api.generateStationInvite(currentInviteStationId);
    currentInviteLink = data.link;
    document.getElementById('invite-link-text').textContent = data.link;
    document.getElementById('invite-link-box').style.display = '';
    document.getElementById('invite-no-link').style.display = 'none';
    tgAlert(t('msg_new_link_generated'));
  } catch (e) {
    tgAlert(e.message);
  }
};

window.deactivateInviteLink = async function() {
  const confirmed = await tgConfirm(t('confirm_deactivate_link'));
  if (!confirmed) return;
  try {
    await api.deleteStationInvite(currentInviteStationId);
    currentInviteLink = null;
    document.getElementById('invite-link-box').style.display = 'none';
    document.getElementById('invite-no-link').style.display = '';
  } catch (e) {
    tgAlert(e.message);
  }
};

window.removeWorker = async function(id, name) {
  const confirmed = await tgConfirm(t('confirm_deactivate_worker', { name }));
  if (!confirmed) return;
  try {
    await api.removeStationWorker(id);
    await showStationWorkers();
  } catch (e) {
    tgAlert(e.message);
  }
};


// ── Change Name ───────────────────────────────────────────────────────────────

window.showChangeName = async function() {
  showScreen('screen-change-name');
  try {
    const me = await api.getMe();
    document.getElementById('change-name-first').value = me.first_name || '';
    document.getElementById('change-name-last').value = me.last_name || '';
  } catch (e) {}
  document.getElementById('change-name-error').style.display = 'none';
};

window.submitChangeName = async function() {
  const first_name = document.getElementById('change-name-first').value.trim();
  const last_name = document.getElementById('change-name-last').value.trim();
  const errEl = document.getElementById('change-name-error');
  if (!first_name) {
    errEl.textContent = t('msg_enter_first_name');
    errEl.style.display = '';
    return;
  }
  errEl.style.display = 'none';
  try {
    await api.updateMe({ first_name, last_name });
    goBack();
  } catch (e) {
    errEl.textContent = e.message;
    errEl.style.display = '';
  }
};

// ── Change Password ───────────────────────────────────────────────────────────

window.submitChangePassword = async function() {
  const old_password = document.getElementById('old-password').value;
  const new_password = document.getElementById('new-password').value;
  const confirm = document.getElementById('confirm-password').value;

  if (new_password !== confirm) {
    tgAlert(t('msg_password_mismatch'));
    return;
  }

  try {
    await api.changePassword(old_password, new_password);
    tgAlert(t('msg_password_changed'));
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
let currentCompanyId = null;

const MANAGE_CONFIG = {
  it_worker:       { titleKey: 'manage_it_workers',       addTitleKey: 'screen_add_staff', apiGet: () => api.getManageITWorkers(currentCompanyId),       apiAdd: (d) => api.addManageITWorker(d),       apiRemove: (id) => api.removeManageITWorker(id) },
  it_deputy:       { titleKey: 'manage_it_deputies',      addTitleKey: null,               apiGet: () => api.getManageITDeputies(currentCompanyId),      apiAdd: null,                                  apiRemove: (id) => api.demoteITDeputy(id) },
  supply_worker:   { titleKey: 'manage_supply_workers',   addTitleKey: 'screen_add_staff', apiGet: () => api.getManageSupplyWorkers(currentCompanyId),   apiAdd: (d) => api.addManageSupplyWorker(d),   apiRemove: (id) => api.removeManageSupplyWorker(id) },
  station_manager: { titleKey: 'manage_station_managers', addTitleKey: 'screen_add_staff', apiGet: () => api.getManageStationManagers(currentCompanyId), apiAdd: (d) => api.addManageStationManager(d), apiRemove: (id) => api.removeManageStationManager(id) },
};

window.showCompanyOrManage = async function() {
  const companies = currentUser.companies || [];
  if (companies.length === 1) {
    currentCompanyId = companies[0].id;
    showManageHub(companies[0].name);
  } else if (companies.length > 1) {
    showScreen('screen-company-select');
    const list = document.getElementById('company-select-list');
    list.innerHTML = companies.map(c => `
      <div class="card" style="cursor:pointer" onclick="selectCompany(${c.id}, '${escHtml(c.name)}')">
        <div class="card-title">${escHtml(c.name)}</div>
      </div>
    `).join('');
  } else {
    showScreen('screen-manage');
  }
};

window.selectCompany = function(id, name) {
  currentCompanyId = id;
  showManageHub(name);
};

function showManageHub(companyName) {
  document.getElementById('manage-company-name').textContent = companyName;
  showScreen('screen-manage');
}

window.showManageSection = async function(type) {
  currentManageType = type;
  const cfg = MANAGE_CONFIG[type];
  document.getElementById('manage-staff-title').textContent = t(cfg.titleKey);
  // Show Invite button for roles that support role invites
  const inviteBtn = document.getElementById('btn-role-invite');
  if (inviteBtn) inviteBtn.style.display = ['it_worker', 'supply_worker', 'station_manager'].includes(type) ? '' : 'none';
  // Hide Add (+) button for sections that don't support adding directly (e.g. IT Deputies — promoted from IT Workers)
  const fab = document.querySelector('#screen-manage-staff .fab');
  if (fab) fab.style.display = cfg.addTitleKey ? '' : 'none';
  showScreen('screen-manage-staff');

  const list = document.getElementById('manage-staff-list');
  list.innerHTML = `<div class="loading">${t('loading')}</div>`;
  try {
    const staff = await cfg.apiGet();
    if (!staff.length) {
      list.innerHTML = `<div class="empty">${t('msg_no_staff')}</div>`;
      return;
    }
    list.innerHTML = staff.map(u => {
      const stationsHtml = (currentManageType === 'station_manager' && u.stations && u.stations.length)
        ? u.stations.map(s => `
            <div style="display:flex;align-items:center;justify-content:space-between;margin-top:4px">
              <span style="font-size:13px;color:var(--hint)">${escHtml(s.name)}</span>
              ${u.is_active ? `<button class="btn btn-danger" style="width:auto;padding:2px 8px;font-size:12px" onclick="removeFromStation(${s.id}, '${escHtml(s.name)}', '${escHtml(u.name)}')">${t('btn_remove')}</button>` : ''}
            </div>`).join('')
        : '';
      return `
        <div class="card">
          <div style="display:flex;align-items:center;justify-content:space-between">
            <div>
              <div class="card-title">${escHtml(u.name)}</div>
              <div class="card-meta">@${escHtml(u.username)} · ${u.is_active ? t('status_active') : `<span style="color:#dc3545">${t('status_deactivated')}</span>`}</div>
            </div>
            ${u.is_active ? `
              <div style="display:flex;gap:6px">
                ${currentManageType === 'station_manager' ? `<button class="btn btn-secondary" style="width:auto;padding:6px 12px;font-size:13px" onclick="showAssignStation(${u.id}, '${escHtml(u.name)}')">+ ${t('btn_assign_station')}</button>` : ''}
                ${currentManageType === 'it_worker' ? `<button class="btn btn-secondary" style="width:auto;padding:6px 12px;font-size:13px" onclick="promoteToITDeputy(${u.id}, '${escHtml(u.name)}')">${t('btn_deputy')}</button>` : ''}
                <button class="btn btn-danger" style="width:auto;padding:6px 12px;font-size:13px" onclick="removeManageStaff(${u.id}, '${escHtml(u.name)}')">${currentManageType === 'it_deputy' ? t('btn_demote') : t('btn_remove')}</button>
              </div>` : ''}
          </div>
          ${stationsHtml}
        </div>`;
    }).join('');
  } catch (e) {
    list.innerHTML = `<div class="empty">${t('error_general')}${e.message}</div>`;
  }
};

window.removeFromStation = async function(stationId, stationName, managerName) {
  const confirmed = await tgConfirm(t('confirm_remove_from_station', { managerName, stationName }));
  if (!confirmed) return;
  try {
    await api.removeStationManager(stationId);
    await showManageSection(currentManageType);
  } catch (e) {
    tgAlert(e.message);
  }
};

window.removeManageStaff = async function(id, name) {
  const isDeputy = currentManageType === 'it_deputy';
  const confirmed = await tgConfirm(isDeputy ? t('confirm_demote_it_worker', { name }) : t('confirm_deactivate_manager', { name }));
  if (!confirmed) return;
  try {
    await MANAGE_CONFIG[currentManageType].apiRemove(id);
    await showManageSection(currentManageType);
  } catch (e) {
    tgAlert(e.message);
  }
};

window.promoteToITDeputy = async function(id, name) {
  const confirmed = await tgConfirm(t('confirm_promote_it_deputy', { name }));
  if (!confirmed) return;
  try {
    await api.promoteToITDeputy({ worker_id: id });
    tgAlert(name + t('msg_is_now_it_deputy'));
    await showManageSection(currentManageType);
  } catch (e) {
    tgAlert(e.message);
  }
};

window.showAddStaff = async function() {
  const cfg = MANAGE_CONFIG[currentManageType];
  document.getElementById('add-staff-title').textContent = cfg.addTitleKey ? t(cfg.addTitleKey) : '';
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
      const stations = await api.getEmptyStations(currentCompanyId);
      if (!stations.length) {
        tgAlert(t('msg_no_empty_stations'));
        return;
      }
      const select = document.getElementById('add-staff-station');
      select.innerHTML = stations.map(s => `<option value="${s.id}">${escHtml(s.name)}</option>`).join('');
      stationField.style.display = '';
    } catch (e) {
      tgAlert(t('error_general') + e.message);
      return;
    }
  }

  showScreen('screen-add-staff');
};

window.submitAddStaff = async function() {
  const username = document.getElementById('add-staff-username').value.trim();
  const password = document.getElementById('add-staff-password').value.trim();
  const first_name = document.getElementById('add-staff-first').value.trim();
  const last_name = document.getElementById('add-staff-last').value.trim();

  if (!username || !password) {
    tgAlert(t('msg_username_password_required'));
    return;
  }

  const data = { username, password, first_name, last_name };

  if (currentManageType === 'station_manager') {
    data.station_id = document.getElementById('add-staff-station').value;
  } else if (currentCompanyId) {
    data.company_id = currentCompanyId;
  }

  try {
    await MANAGE_CONFIG[currentManageType].apiAdd(data);
    tgAlert(t('msg_account_created') + (first_name || username));
    goBack();
    await showManageSection(currentManageType);
  } catch (e) {
    tgAlert(e.message);
  }
};

// ── Assign Station to Existing Manager ────────────────────────────────────────

let assignStationManagerId = null;

window.showAssignStation = async function(managerId, managerName) {
  assignStationManagerId = managerId;
  document.getElementById('assign-station-manager-name').textContent = `Manager: ${managerName}`;
  const select = document.getElementById('assign-station-select');
  select.innerHTML = `<option value="">${t('loading')}</option>`;
  showScreen('screen-assign-station');
  try {
    const stations = await api.getEmptyStations(currentCompanyId);
    if (!stations.length) {
      tgAlert(t('msg_no_empty_stations'));
      goBack();
      return;
    }
    select.innerHTML = stations.map(s => `<option value="${s.id}">${escHtml(s.name)}</option>`).join('');
  } catch (e) {
    select.innerHTML = `<option value="">${t('error_general')}...</option>`;
  }
};

window.submitAssignStation = async function() {
  const stationId = document.getElementById('assign-station-select').value;
  if (!stationId) { tgAlert(t('msg_select_station')); return; }
  try {
    await api.setStationManager(stationId, assignStationManagerId);
    tgAlert(t('msg_station_assigned'));
    goBack();
  } catch (e) {
    tgAlert(e.message);
  }
};

// ── Role Invite ───────────────────────────────────────────────────────────────

let currentRoleInviteLink = '';

window.showRoleInvite = async function() {
  const roleLabels = { it_worker: t('role_it_worker'), supply_worker: t('role_supply_worker'), station_manager: t('role_station_manager') };
  document.getElementById('role-invite-title').textContent = `${t('btn_invite')} ${roleLabels[currentManageType] || ''}`;
  document.getElementById('role-invite-result').style.display = 'none';
  currentRoleInviteLink = '';

  const stationField = document.getElementById('role-invite-station-field');
  const stationSelect = document.getElementById('role-invite-station');
  if (currentManageType === 'station_manager') {
    stationField.style.display = '';
    stationSelect.innerHTML = '<option value="">Loading...</option>';
    try {
      const stations = await api.getEmptyStations(currentCompanyId);
      if (!stations.length) {
        stationSelect.innerHTML = `<option value="">${t('msg_no_empty_stations')}</option>`;
      } else {
        stationSelect.innerHTML = stations.map(s => `<option value="${s.id}">${escHtml(s.name)}</option>`).join('');
      }
    } catch (e) {
      stationSelect.innerHTML = `<option value="">${t('error_general')}...</option>`;
    }
  } else {
    stationField.style.display = 'none';
  }

  // Load existing unused invites
  await loadRoleInviteList();
  showScreen('screen-role-invite');
};

async function loadRoleInviteList() {
  const listEl = document.getElementById('role-invite-list');
  try {
    const invites = await api.getRoleInvites(currentCompanyId);
    const filtered = invites.filter(i => i.role === currentManageType);
    if (!filtered.length) { listEl.innerHTML = ''; return; }
    listEl.innerHTML = `<div style="font-size:12px;color:var(--hint);margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px">${t('section_unused_links')}</div>` +
      filtered.map(i => `
        <div class="card" style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
          <div style="font-size:13px;color:var(--hint);word-break:break-all;flex:1;margin-right:8px">${i.station_name ? escHtml(i.station_name) + ' · ' : ''}...${escHtml(i.token.slice(-8))}</div>
          <button class="btn btn-danger" style="width:auto;padding:4px 10px;font-size:12px;flex-shrink:0" onclick="deleteRoleInvite(${i.id})">${t('btn_remove')}</button>
        </div>
      `).join('');
  } catch (e) {
    listEl.innerHTML = '';
  }
}

window.generateRoleInvite = async function() {
  const data = { role: currentManageType };
  if (currentCompanyId) data.company_id = currentCompanyId;
  if (currentManageType === 'station_manager') {
    const stationId = document.getElementById('role-invite-station').value;
    if (!stationId) { tgAlert(t('msg_select_station')); return; }
    data.station_id = stationId;
  }
  try {
    const res = await api.createRoleInvite(data);
    currentRoleInviteLink = res.link || `inv_${res.token}`;
    document.getElementById('role-invite-link').textContent = currentRoleInviteLink;
    document.getElementById('role-invite-result').style.display = '';
    await loadRoleInviteList();
  } catch (e) {
    tgAlert(e.message);
  }
};

window.copyRoleInviteLink = function() {
  if (!currentRoleInviteLink) return;
  if (navigator.clipboard) {
    navigator.clipboard.writeText(currentRoleInviteLink).then(() => tgAlert(t('msg_link_copied_short')));
  } else {
    tgAlert(currentRoleInviteLink);
  }
};

window.deleteRoleInvite = async function(id) {
  const confirmed = await tgConfirm(t('confirm_delete_invite'));
  if (!confirmed) return;
  try {
    await api.deleteRoleInvite(id);
    await loadRoleInviteList();
  } catch (e) {
    tgAlert(e.message);
  }
};

// ── Station Deputies ──────────────────────────────────────────────────────────

window.showStationDeputies = async function() {
  showScreen('screen-station-deputies');
  const list = document.getElementById('station-deputies-list');
  list.innerHTML = `<div class="loading">${t('loading')}</div>`;

  try {
    const deputies = await api.getStationDeputies(currentStationId);
    if (!deputies.length) {
      list.innerHTML = `<div class="empty">${t('msg_no_deputies')}</div>`;
      return;
    }
    list.innerHTML = deputies.map(d => `
      <div class="card" style="display:flex;align-items:center;justify-content:space-between">
        <div>
          <div class="card-title">${escHtml(d.name)}</div>
          <div class="card-meta">@${escHtml(d.username)}</div>
        </div>
        <button class="btn btn-secondary" style="width:auto;padding:6px 12px;font-size:13px" onclick="demoteToWorker(${d.id}, '${escHtml(d.name)}')">${t('role_worker')}</button>
      </div>
    `).join('');
  } catch (e) {
    list.innerHTML = `<div class="empty">${t('error_general')}${e.message}</div>`;
  }
};

window.demoteToWorker = async function(id, name) {
  const confirmed = await tgConfirm(t('confirm_demote_deputy', { name }));
  if (!confirmed) return;
  try {
    await api.removeStationDeputy(id, currentStationId);
    await showStationDeputies();
  } catch (e) {
    tgAlert(e.message);
  }
};

window.showAddDeputy = async function() {
  try {
    const workers = await api.getStationWorkers(currentStationId);
    const active = workers.filter(w => w.is_active);
    const select = document.getElementById('deputy-worker-select');
    if (!active.length) {
      tgAlert(t('msg_no_workers_to_promote'));
      return;
    }
    select.innerHTML = active.map(w => `<option value="${w.id}">${escHtml(w.name)} (@${escHtml(w.username)})</option>`).join('');
  } catch (e) {
    tgAlert(t('error_general') + e.message);
    return;
  }
  showScreen('screen-add-deputy');
};

window.submitPromoteDeputy = async function() {
  const workerId = document.getElementById('deputy-worker-select').value;
  if (!workerId) { tgAlert(t('msg_select_worker')); return; }
  try {
    await api.addStationDeputy({ worker_id: parseInt(workerId), station_id: currentStationId });
    tgAlert(t('msg_promoted_to_deputy'));
    goBack();
    await showStationDeputies();
  } catch (e) {
    tgAlert(e.message);
  }
};

// ── Start ─────────────────────────────────────────────────────────────────────

init();
