// Server API client and session handling
'use strict';

// ===== Server API layer (replaces Firebase / localStorage data) =====
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const unesc = s => String(s ?? '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
const TOKEN_KEY = 'alu_session_token';
let authToken = sessionStorage.getItem(TOKEN_KEY);

async function api(method, path, body) {
  const r = await fetch('/api' + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(authToken ? { Authorization: 'Bearer ' + authToken } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  let data = null;
  try { data = await r.json(); } catch (_) {}
  if (r.status === 401 && authToken && path !== '/login') sessionExpired();
  if (!r.ok) throw new Error((data && data.error) || `Request failed (${r.status})`);
  return data;
}
function sessionExpired(announce = true) {
  authToken = null; currentUser = null; sessionStorage.removeItem(TOKEN_KEY);
  materialsData = []; suppliersData = []; pipelineData = []; prsData = []; usersData = []; grnsData = []; ncrsData = []; invoicesData = [];
  refreshAll(); openModal('login-modal');
  if (announce) showToast("Signed Out", "Your session ended. Please sign in again.", "error");
}
