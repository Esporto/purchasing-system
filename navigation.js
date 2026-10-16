// Tab switching and the new-entry modal
'use strict';

function switchGallery(tab) {
  activeGalleryTab = tab;

  const catFilterWrapper = document.getElementById('category-filter-wrapper');
  if (catFilterWrapper) {
    catFilterWrapper.style.display = tab === 'materials' ? 'block' : 'none';
  }

  ['materials', 'prs', 'suppliers', 'pipeline', 'sop'].forEach(t => {
    const sec = document.getElementById('gallery-' + t);
    if (sec) sec.classList.toggle('hidden', t !== tab);

    const btn = document.getElementById('tab-' + t);
    if (btn) {
      btn.className = t === tab 
        ? 'tab-btn active-tab px-3.5 py-1.5 rounded-lg flex items-center gap-2 bg-white text-slate-900 shadow-sm shrink-0 transition whitespace-nowrap'
        : 'tab-btn px-3.5 py-1.5 rounded-lg flex items-center gap-2 text-slate-600 hover:text-slate-900 shrink-0 transition whitespace-nowrap';
    }
  });

  if (tab === 'materials') renderMaterials(materialsData);
  if (tab === 'prs') renderPRs();
  if (tab === 'suppliers') renderSuppliers();
  if (tab === 'pipeline') renderPipeline();
  if (tab === 'sop') renderSOP();
}

function switchEntryTab(type) {
  ['material', 'pr', 'supplier', 'po'].forEach(t => {
    const form = document.getElementById('form-add-' + t);
    if (form) form.classList.toggle('hidden', t !== type);

    const btn = document.getElementById('entry-tab-' + t);
    if (btn) {
      btn.className = t === type 
        ? 'px-4 py-2.5 border-b-2 border-sky-600 text-sky-700 font-semibold flex items-center gap-1.5 shrink-0 transition whitespace-nowrap'
        : 'px-4 py-2.5 border-b-2 border-transparent text-slate-600 hover:text-slate-900 flex items-center gap-1.5 shrink-0 transition whitespace-nowrap';
    }
  });
}

function openNewEntryModal(tab = 'material') {
  populateDropdowns();
  switchEntryTab(tab);
  if (tab === 'pr') {
    const nextPrNum = "PR-2026-" + String(prsData.length + 1).padStart(3, '0');
    const numInput = document.getElementById('pr-num');
    if (numInput) numInput.value = nextPrNum;
    
    // Initialize with default line item
    prLinesBuilder = [];
    addPRLineRow();
  }
  openModal('new-entry-modal');
}
