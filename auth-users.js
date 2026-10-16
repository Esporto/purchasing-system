// Login, logout, role-based UI and user management
'use strict';

function handleLoginSubmit(e) {
  e.preventDefault();
  const uname = document.getElementById('login-uname').value.trim().toLowerCase();
  const pass = document.getElementById('login-pass').value.trim();
  executeLogin(uname, pass);
}


async function executeLogin(username, password) {
  const errBox = document.getElementById('login-error-alert');
  if (errBox) errBox.classList.add('hidden');
  try {
    const res = await api('POST', '/login', { username, password });
    authToken = res.token; sessionStorage.setItem(TOKEN_KEY, authToken);
    currentUser = mapUser(res.user);
    closeModal('login-modal'); applyUserProfileUI(); await loadAll();
    showToast("Access Granted", `Welcome back, ${currentUser.fullName}!`);
  } catch (e) { if (errBox) { errBox.innerText = e.message; errBox.classList.remove('hidden'); } }
}

function handleLogout() {
  closeSidebar('user-profile-sidebar');
  sessionExpired(false);
  showToast("Signed Out", "You have securely signed out.");
}

function applyUserProfileUI() {
  if (!currentUser) {
    openModal('login-modal');
    return;
  }

  const displayName = (currentUser.fullName || currentUser.name || currentUser.username || 'User').trim();
  const initials = (displayName.split(/\s+/).filter(Boolean).map(n => n[0]).join('') || displayName.substring(0, 2) || 'US').substring(0, 2).toUpperCase();

  const hAvatar = document.getElementById('user-header-avatar');
  const hName = document.getElementById('user-header-name');
  const hRole = document.getElementById('user-header-role');
  if (hAvatar) hAvatar.innerText = initials;
  if (hName) hName.innerText = displayName;
  if (hRole) hRole.innerText = currentUser.roleLabel || currentUser.role || 'Staff';

  const sAvatar = document.getElementById('sidebar-user-avatar');
  const sName = document.getElementById('sidebar-user-name');
  const sUname = document.getElementById('sidebar-user-uname');
  const sBadge = document.getElementById('sidebar-user-role-badge');
  if (sAvatar) sAvatar.innerText = initials;
  if (sName) sName.innerText = displayName;
  if (sUname) sUname.innerText = `@${currentUser.username || 'user'}`;
  if (sBadge) sBadge.innerText = currentUser.roleLabel || currentUser.role || 'Staff';

  const userIsAdmin = isUserAdmin(currentUser);

  const headerAdminBtn = document.getElementById('header-admin-access-btn');
  if (headerAdminBtn) {
    if (userIsAdmin) {
      headerAdminBtn.classList.remove('hidden');
      headerAdminBtn.classList.add('flex');
    } else {
      headerAdminBtn.classList.add('hidden');
      headerAdminBtn.classList.remove('flex');
    }
  }

  const accessCard = document.getElementById('sidebar-access-card');
  if (accessCard) {
    accessCard.style.display = userIsAdmin ? 'block' : 'none';
  }

  const utilAccessBtn = document.getElementById('sidebar-util-access-btn');
  if (utilAccessBtn) {
    utilAccessBtn.style.display = userIsAdmin ? 'flex' : 'none';
  }

  renderUsersTable();
  renderPRs();
}

function renderUsersTable() {
  const tbody = document.getElementById('user-accounts-tbody');
  if (!tbody) return;

  tbody.innerHTML = usersData.map(u => {
    const isAllowed = u.status === 'allowed';
    const isSelf = currentUser && currentUser.username === u.username;
    const nameDisplay = u.fullName || u.name || u.username || 'Unnamed User';

    return `
      <tr class="hover:bg-slate-50 transition">
        <td class="p-3 mono font-bold text-sky-700">@${u.username}</td>
        <td class="p-3 font-semibold text-slate-800">${nameDisplay}</td>
        <td class="p-3 text-slate-600 capitalize">${u.roleLabel || u.role}</td>
        <td class="p-3">
          <span class="px-2 py-0.5 rounded-full text-[10px] font-bold ${isAllowed ? 'bg-emerald-100 text-emerald-800 border border-emerald-300' : 'bg-rose-100 text-rose-800 border border-rose-300'}">
            ${isAllowed ? '● Allowed' : '● Revoked'}
          </span>
        </td>
        <td class="p-3 text-right space-x-1.5">
          ${isSelf ? `
            <span class="text-[10px] text-slate-400 italic">Current Session</span>
          ` : `
            <button onclick="toggleUserStatus('${u.username}')" class="px-2.5 py-1 rounded text-[10px] font-semibold transition ${isAllowed ? 'bg-rose-100 text-rose-700 hover:bg-rose-200' : 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200'}">
              ${isAllowed ? 'Revoke Access' : 'Allow Access'}
            </button>
            <button onclick="changeUserPassword('${u.username}')" class="px-2.5 py-1 rounded text-[10px] font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200">
              Password
            </button>
          `}
        </td>
      </tr>
    `;
  }).join('');
}

async function toggleUserStatus(username) {
  const user = usersData.find(u => u.username === username);
  if (!user) return;
  const status = user.status === 'allowed' ? 'revoked' : 'allowed';
  await mutate(() => api('POST', '/users', { username, status }), null, "Access Updated", `@${username} status set to ${status.toUpperCase()}.`);
}

async function handleCreateUser(e) {
  e.preventDefault();
  const form = e.target;
  const username = document.getElementById('new-user-uname').value.trim().toLowerCase();
  if (usersData.some(u => u.username === username)) { showToast("Username Exists", `Account @${username} already exists.`, "error"); return; }
  const body = { username, full_name: document.getElementById('new-user-fullname').value.trim(), role: document.getElementById('new-user-role').value,
                 password: document.getElementById('new-user-pass').value };
  await mutate(() => api('POST', '/users', body), () => form.reset(), "User Registered", `Account @${username} added and granted access.`);
}

async function changeUserPassword(username) {
  const newPass = prompt(`Enter new password for @${username} (at least 8 characters):`);
  if (newPass) await mutate(() => api('POST', '/users', { username, password: newPass }), null, "Password Saved", `Password for @${username} updated.`);
}
