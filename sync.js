// Loading, polling and saving data through the server
'use strict';

function refreshAll() {
  executeFilterCards(); renderPRs(); renderSuppliers(); renderPipeline(); renderUsersTable(); updateHeaderKPIs(); renderLogistics();
  try { populateDropdowns(); } catch (_) {}
}
async function loadAll(announce = false) {
  if (!authToken) return;
  try {
    const [m, s, o, p, g, n, v] = await Promise.all(['/materials', '/suppliers', '/orders', '/prs', '/grns', '/ncrs', '/invoices'].map(x => api('GET', x + '?limit=1000')));
    materialsData = m.map(mapMaterial); suppliersData = s.map(mapSupplier); pipelineData = o.map(mapOrder); prsData = p.map(mapPR);
    grnsData = g.map(mapGRN); ncrsData = n.map(mapNCR); invoicesData = v.map(mapInvoice);
    if (currentUser && currentUser.role === 'admin') usersData = (await api('GET', '/users')).map(mapUser);
    refreshAll();
    if (announce) showToast("Synced", "Latest data loaded from the server.");
  } catch (err) { if (announce) showToast("Sync failed", err.message, "error"); }
}
async function mutate(call, onDone, title, msg) {
  try {
    const r = await call();
    if (onDone) onDone(r);
    await loadAll();
    if (title) showToast(title, msg);
    return r;
  } catch (err) { showToast("Not saved", err.message, "error"); }
}
async function initCloudBackend() {
  if (authToken) {
    try { currentUser = mapUser(await api('GET', '/me')); applyUserProfileUI(); closeModal('login-modal'); await loadAll(); }
    catch (_) { sessionExpired(false); }
  } else { openModal('login-modal'); }
  setInterval(() => { if (!document.hidden && authToken) loadAll(); }, 20000);
}



async function forceSyncAllToCloud() { await loadAll(true); }


