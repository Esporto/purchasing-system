// Delete confirmation and material detail modal
'use strict';

let pendingDelete = null;
function promptDelete(type, key) {
  pendingDelete = { type, key };
  document.getElementById('del-modal-title').innerText = `Delete ${key}`;
  document.getElementById('del-modal-msg').innerText = `Remove this ${type} record immediately?`;
  document.getElementById('del-confirm-btn').onclick = executeDelete;
  openModal('delete-modal');
}

async function executeDelete() {
  if (!pendingDelete) return;
  const { type, key } = pendingDelete; pendingDelete = null;
  const base = { material: '/materials/', pr: '/prs/', supplier: '/suppliers/', po: '/orders/' }[type];
  closeModal('delete-modal');
  await mutate(() => api('DELETE', base + encodeURIComponent(key)), null, "Deleted", `${key} removed.`);
}

function viewMaterialDetail(code) {
  const item = materialsData.find(m => m.code === code);
  if (!item) return;

  document.getElementById('spec-modal-title').innerText = item.name;
  document.getElementById('spec-modal-subtitle').innerText = `SKU: ${item.code} | Category: ${item.categoryLabel || item.category}`;
  
  document.getElementById('spec-modal-content').innerHTML = `
    <div class="space-y-3">
      <div class="bg-slate-50 border border-slate-200 rounded-xl p-3.5 space-y-1.5">
        <span class="font-bold text-slate-800 text-[10px] uppercase block">Technical Specifications</span>
        <p class="text-slate-700 font-medium">${item.specs}</p>
        <div class="pt-1.5 border-t border-slate-200 grid grid-cols-2 gap-2 text-[11px] text-slate-500">
          <span>Tolerance: <strong class="text-slate-700">${item.details?.tolerance || 'Standard'}</strong></span>
          <span>Packaging: <strong class="text-slate-700">${item.details?.packaging || 'Bundles'}</strong></span>
        </div>
      </div>
      <div class="grid grid-cols-3 gap-2 text-center">
        <div class="bg-slate-50 border border-slate-100 rounded-xl p-2">
          <span class="text-[9px] text-slate-400 uppercase block">Balance</span>
          <span class="mono font-bold text-slate-900">${item.currentStock} ${item.uom}</span>
        </div>
        <div class="bg-slate-50 border border-slate-100 rounded-xl p-2">
          <span class="text-[9px] text-slate-400 uppercase block">Reorder Pt</span>
          <span class="mono font-bold text-amber-700">${item.reorderPoint} ${item.uom}</span>
        </div>
        <div class="bg-slate-50 border border-slate-100 rounded-xl p-2">
          <span class="text-[9px] text-slate-400 uppercase block">Std Cost</span>
          <span class="mono font-bold text-emerald-700">$${Number(item.stdCost).toFixed(2)}</span>
        </div>
      </div>
    </div>
  `;

  openModal('spec-modal');
}
