import { api, setToken } from '/static/api.js';

const tg = window.Telegram?.WebApp;
const app = document.getElementById('app');

let currentUser = null;

// ── Router ────────────────────────────────────────────────────────────────────

function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  const screen = document.getElementById(id);
  if (screen) screen.classList.add('active');
  tg?.BackButton[id === 'screen-tasks' ? 'hide' : 'show']();
}

// ── Auth ──────────────────────────────────────────────────────────────────────

async function init() {
  tg?.ready();
  tg?.expand();
  tg?.BackButton.onClick(() => showScreen('screen-tasks'));

  showScreen('screen-loading');

  try {
    // Dev mode: use token from dev login page
    const devToken = localStorage.getItem('dev_access_token');
    if (devToken) {
      setToken(devToken);
      const me = await api.getMe();
      currentUser = { id: me.id, role: me.role, name: me.first_name || me.username };
      await loadTasks();
      return;
    }

    // Production: Telegram initData
    const initData = tg?.initData || '';
    if (!initData) {
      // No Telegram and no dev token → redirect to dev login
      window.location.href = '/dev/';
      return;
    }
    const auth = await api.telegramAuth(initData);
    setToken(auth.access);
    currentUser = auth.user;
    await loadTasks();
  } catch (e) {
    showError('Auth failed: ' + e.message);
  }
}

// ── Tasks List ────────────────────────────────────────────────────────────────

async function loadTasks() {
  showScreen('screen-tasks');
  const list = document.getElementById('tasks-list');
  list.innerHTML = '<div class="loading">Loading...</div>';

  try {
    const tasks = await api.getTasks();
    renderTaskList(tasks);
  } catch (e) {
    list.innerHTML = `<div class="empty">Error: ${e.message}</div>`;
  }
}

function renderTaskList(tasks) {
  const list = document.getElementById('tasks-list');
  const role = currentUser.role;

  const fab = document.getElementById('fab-new-task');
  fab.style.display = role === 'worker' ? 'flex' : 'none';

  if (!tasks.length) {
    list.innerHTML = '<div class="empty">No tasks yet.</div>';
    return;
  }

  list.innerHTML = tasks.map(t => `
    <div class="card" onclick="openTask(${t.id})">
      <div class="card-title">${escHtml(t.title)}</div>
      <div class="card-meta">
        <span class="badge badge-${t.status}">${formatStatus(t.status)}</span>
        &nbsp;${formatDate(t.created_at)}
      </div>
      ${role !== 'worker' ? `<div class="card-meta" style="margin-top:4px">${t.tickets?.length || 0} ticket(s)</div>` : ''}
    </div>
  `).join('');
}

// ── Task Detail ───────────────────────────────────────────────────────────────

window.openTask = async function(id) {
  showScreen('screen-task-detail');
  const body = document.getElementById('task-detail-body');
  body.innerHTML = '<div class="loading">Loading...</div>';

  try {
    const task = await api.getTask(id);
    renderTaskDetail(task);
  } catch (e) {
    body.innerHTML = `<div class="empty">Error: ${e.message}</div>`;
  }
};

function renderTaskDetail(task) {
  const header = document.getElementById('task-detail-title');
  header.textContent = task.title;

  const body = document.getElementById('task-detail-body');
  const role = currentUser.role;
  const isITWorker = role === 'it_worker' || role === 'admin';
  const myTicket = task.tickets?.find(t => t.assigned_to === currentUser.id);

  body.innerHTML = `
    <div class="detail-body">
      <!-- Status -->
      <div class="detail-section">
        <span class="badge badge-${task.status}">${formatStatus(task.status)}</span>
        <span style="color:var(--hint);font-size:13px;margin-left:8px">by ${escHtml(task.created_by_name)}</span>
      </div>

      <!-- Description -->
      ${task.description ? `
        <div class="detail-section">
          <h3>Description</h3>
          <div class="description-text">${escHtml(task.description)}</div>
        </div>` : ''}

      <!-- Tickets (IT workers / admin see all) -->
      ${isITWorker ? `
        <div class="detail-section">
          <h3>Tickets</h3>
          ${task.tickets?.length ? task.tickets.map(t => `
            <div class="ticket-card">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <div class="ticket-worker">${escHtml(t.assigned_to_name)}</div>
                <span class="badge badge-${t.status}">${formatStatus(t.status)}</span>
              </div>
              ${t.notes ? `<div class="ticket-notes">${escHtml(t.notes)}</div>` : ''}
              ${t.assigned_to === currentUser.id ? renderTicketActions(t) : ''}
            </div>
          `).join('') : '<div class="empty" style="padding:10px">No tickets yet.</div>'}
        </div>` : ''}

      <!-- Comments -->
      <div class="detail-section" id="comments-section">
        <h3>Comments</h3>
        ${renderComments(task.comments)}
      </div>
    </div>

    <!-- Comment input -->
    <div class="comment-input-row">
      <input id="comment-input" type="text" placeholder="Write a comment...">
      <button onclick="submitComment(${task.id})">&#10148;</button>
    </div>

    <!-- IT Worker actions -->
    ${isITWorker && task.status !== 'resolved' ? `
      <div style="padding:0 16px 16px;display:flex;flex-direction:column;gap:8px">
        ${!task.tickets?.find(t => t.assigned_to === currentUser.id) ? `
          <button class="btn btn-primary" onclick="assignSelf(${task.id})">Take this task</button>
        ` : ''}
        ${myTicket && myTicket.status !== 'done' ? `
          <button class="btn btn-secondary" onclick="showDelegateForm(${task.id})">Delegate to another IT worker</button>
        ` : ''}
        ${canResolve(task) ? `
          <button class="btn btn-danger" onclick="resolveTask(${task.id})">Mark as Resolved</button>
        ` : ''}
      </div>
    ` : ''}
  `;

  // store task id on screen for refresh
  document.getElementById('screen-task-detail').dataset.taskId = task.id;
}

function renderTicketActions(ticket) {
  if (ticket.status === 'done') return '';
  const next = ticket.status === 'open' ? 'in_progress' : 'done';
  const label = next === 'in_progress' ? 'Start working' : 'Mark my part done';
  return `<button class="btn btn-primary" style="margin-top:8px" onclick="updateTicket(${ticket.id}, '${next}')">
    ${label}
  </button>`;
}

function renderComments(comments) {
  if (!comments?.length) return '<div class="empty" style="padding:10px">No comments yet.</div>';
  return comments.map(c => `
    <div class="comment">
      <div class="comment-author">${escHtml(c.author_name)}</div>
      <div class="comment-text">${escHtml(c.text)}</div>
      <div class="comment-time">${formatDate(c.created_at)}</div>
    </div>
  `).join('');
}

function canResolve(task) {
  if (!task.tickets?.length) return false;
  return task.tickets.every(t => t.status === 'done');
}

// ── Actions ───────────────────────────────────────────────────────────────────

window.updateTicket = async function(ticketId, newStatus) {
  try {
    await api.updateTicket(ticketId, { status: newStatus });
    const taskId = document.getElementById('screen-task-detail').dataset.taskId;
    await openTask(taskId);
  } catch (e) {
    tg?.showAlert(e.message);
  }
};

window.assignSelf = async function(taskId) {
  try {
    await api.createTicket(taskId, {
      assigned_to: currentUser.id,
      status: 'open',
    });
    await openTask(taskId);
  } catch (e) {
    tg?.showAlert(e.message);
  }
};

window.resolveTask = async function(taskId) {
  tg?.showConfirm('Mark this task as resolved and send to Zammad?', async (confirmed) => {
    if (!confirmed) return;
    try {
      await api.resolveTask(taskId);
      tg?.showAlert('Task resolved and archived to Zammad.');
      await loadTasks();
      showScreen('screen-tasks');
    } catch (e) {
      tg?.showAlert(e.message);
    }
  });
};

window.submitComment = async function(taskId) {
  const input = document.getElementById('comment-input');
  const text = input.value.trim();
  if (!text) return;
  try {
    await api.addComment(taskId, text);
    input.value = '';
    await openTask(taskId);
  } catch (e) {
    tg?.showAlert(e.message);
  }
};

let selectedDelegateWorkerId = null;

window.showDelegateForm = async function(taskId) {
  showScreen('screen-delegate');
  document.getElementById('delegate-task-id').value = taskId;
  document.getElementById('delegate-notes').value = '';
  selectedDelegateWorkerId = null;

  const list = document.getElementById('delegate-worker-list');
  list.innerHTML = '<div class="empty">Loading...</div>';

  try {
    const workers = await api.getITWorkers();
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
  const taskId = document.getElementById('delegate-task-id').value;
  const notes = document.getElementById('delegate-notes').value.trim();

  if (!selectedDelegateWorkerId) {
    tg?.showAlert('Please select an IT worker.');
    return;
  }

  try {
    await api.createTicket(taskId, {
      assigned_to: selectedDelegateWorkerId,
      status: 'open',
      notes,
    });
    await openTask(taskId);
    showScreen('screen-task-detail');
  } catch (e) {
    tg?.showAlert(e.message);
  }
};

// ── Create Task ───────────────────────────────────────────────────────────────

window.showCreateTask = function() {
  showScreen('screen-create-task');
  document.getElementById('new-task-title').value = '';
  document.getElementById('new-task-desc').value = '';
};

window.submitCreateTask = async function() {
  const title = document.getElementById('new-task-title').value.trim();
  const description = document.getElementById('new-task-desc').value.trim();

  if (!title) {
    tg?.showAlert('Please enter a title.');
    return;
  }

  try {
    await api.createTask({ title, description });
    await loadTasks();
    showScreen('screen-tasks');
  } catch (e) {
    tg?.showAlert(e.message);
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

// ── Start ─────────────────────────────────────────────────────────────────────

init();
