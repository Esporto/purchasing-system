// In-memory application state and role helpers
'use strict';

// IN-MEMORY ACTIVE STATE & FILTERS
let materialsData = [];
let prsData = [];
let suppliersData = [];
let pipelineData = [];
let usersData = [];
let currentUser = null;

let activeGalleryTab = 'materials';
let activePRFilter = 'all';
let activePRSort = 'newest';

// Active Line Items State for New PR Form
let prLinesBuilder = [];

function loadLocalState() {
  // purge data (including plaintext passwords) cached by earlier versions of this page
  ['alu_materials', 'alu_prs', 'alu_suppliers', 'alu_pipeline', 'alu_users', 'alu_active_user'].forEach(k => localStorage.removeItem(k));
}


loadLocalState();

function isUserAdmin(user) {
  if (!user) return false;
  const r = String(user.role || '').toLowerCase();
  const u = String(user.username || '').toLowerCase();
  const l = String(user.roleLabel || '').toLowerCase();
  return r.includes('admin') || u === 'admin' || l.includes('admin') || r.includes('gm');
}

function isUserFinanceOrAdmin(user) {
  if (!user) return false;
  if (isUserAdmin(user)) return true;
  const r = String(user.role || '').toLowerCase();
  const l = String(user.roleLabel || '').toLowerCase();
  return r.includes('finance') || l.includes('finance');
}
