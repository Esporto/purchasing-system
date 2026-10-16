// Suppliers, pipeline and SOP views, search, header KPIs, dropdowns
'use strict';

function renderSuppliers() {
  const container = document.getElementById('suppliers-grid');
  if (!container) return;

  container.innerHTML = suppliersData.map(sup => `
    <div class="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 card-contain flex flex-col justify-between space-y-3.5 relative">
      <div>
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0">
            <span class="mono text-[10px] text-slate-400 uppercase font-semibold block">${sup.id}</span>
            <h3 class="font-bold text-slate-900 text-xs sm:text-sm mt-0.5 truncate">${sup.name}</h3>
            <span class="text-xs text-sky-700 font-medium truncate block">${sup.category}</span>
          </div>
          <div class="flex items-center gap-1 shrink-0">
            <span class="text-[10px] font-bold px-2 py-0.5 rounded-full border ${sup.tierColor}">${sup.tier}</span>
            <button onclick="promptDelete('supplier', '${sup.id}')" aria-label="Delete Vendor" class="text-slate-300 hover:text-rose-600 hover:bg-rose-50 p-1 rounded transition">
              ${ICONS.trash}
            </button>
          </div>
        </div>

        <div class="mt-3.5 grid grid-cols-3 gap-2 text-center bg-slate-50 border border-slate-100 rounded-xl p-2.5">
          <div>
            <span class="text-[9px] text-slate-400 uppercase block">Score</span>
            <span class="mono font-bold text-sm text-slate-900">${sup.score}<span class="text-[10px] font-normal text-slate-400">/100</span></span>
          </div>
          <div>
            <span class="text-[9px] text-slate-400 uppercase block">OTIF</span>
            <span class="mono font-bold text-sm text-emerald-600">${sup.otif}</span>
          </div>
          <div>
            <span class="text-[9px] text-slate-400 uppercase block">QC Rate</span>
            <span class="mono font-bold text-sm text-sky-600">${sup.qcRate || '99.0%'}</span>
          </div>
        </div>
      </div>

      <div class="pt-2.5 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
        <span class="truncate">💳 ${sup.paymentTerms}</span>
        <span class="shrink-0">⏱️ ${sup.leadTime}</span>
      </div>
    </div>
  `).join('');
}

function renderPipeline() {
  const container = document.getElementById('pipeline-grid');
  if (!container) return;

  container.innerHTML = pipelineData.map(po => `
    <div class="bg-white rounded-2xl border border-slate-200 shadow-xs p-4 card-contain flex flex-col justify-between space-y-3 relative">
      <div>
        <div class="flex items-center justify-between gap-2">
          <span class="mono text-xs font-bold text-sky-700 bg-sky-50 border border-sky-200 px-2 py-0.5 rounded shrink-0">${po.poNumber}</span>
          <div class="flex items-center gap-1 shrink-0">
            <span class="text-[10px] px-2 py-0.5 rounded-full border ${po.alertBadge}">${po.alert}</span>
            <button onclick="promptDelete('po', '${po.poNumber}')" aria-label="Delete PO" class="text-slate-300 hover:text-rose-600 hover:bg-rose-50 p-1 rounded transition">
              ${ICONS.trash}
            </button>
          </div>
        </div>
        <h4 class="font-bold text-slate-900 text-xs sm:text-sm mt-2 truncate">${po.vendor}</h4>
        <p class="text-xs text-slate-600 mt-0.5 font-medium line-clamp-1">${po.items}</p>
      </div>

      <div class="space-y-1">
        <div class="flex justify-between text-[11px] text-slate-500">
          <span>Status: <strong class="text-slate-800">${po.status}</strong></span>
          <span class="mono font-semibold">${po.progressPct}%</span>
        </div>
        <div class="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
          <div class="bg-sky-600 h-1.5 rounded-full transition-all duration-300" style="width: ${po.progressPct}%"></div>
        </div>
      </div>

      <div class="bg-slate-50 border border-slate-100 rounded-xl p-2.5 text-xs text-slate-700">
        <span class="text-[10px] uppercase font-bold text-slate-400 block mb-0.5">Expediting Action:</span>
        <p class="text-[11px] line-clamp-2">${po.dockAction}</p>
      </div>

      <div class="pt-2 border-t border-slate-100 flex items-center justify-between text-xs">
        <span class="mono font-bold text-slate-900 text-xs sm:text-sm">${po.amount}</span>
        <span class="text-slate-500 flex items-center gap-1 text-[11px]">
          📅 ${po.dueDate}
        </span>
      </div>
    ${poActionButtons(po)}
    </div>
  `).join('');
}

function renderSOP() {
  const container = document.getElementById('sop-grid');
  if (!container) return;

  container.innerHTML = sopData.map(sop => `
    <div class="bg-white rounded-2xl border border-slate-200 shadow-xs p-4 card-contain flex flex-col justify-between space-y-3">
      <div>
        <div class="flex items-center justify-between">
          <span class="mono text-[10px] font-bold text-sky-700 bg-sky-50 border border-sky-200 px-2 py-0.5 rounded">${sop.id}</span>
          <span class="text-[10px] text-slate-500 font-medium">${sop.type}</span>
        </div>
        <h4 class="font-bold text-slate-900 text-xs sm:text-sm mt-2">${sop.title}</h4>
        <p class="text-xs text-slate-600 mt-1">${sop.desc}</p>
      </div>
      <div class="bg-slate-50 border border-slate-100 rounded-xl p-2.5 text-[11px] text-slate-500">
        <span class="font-semibold text-slate-700 block mb-0.5">Required Fields:</span>
        <span>${sop.fields}</span>
      </div>
      <div class="pt-2 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-400">
        <span>Custodian: <strong class="text-slate-600">${sop.role}</strong></span>
        <span class="text-sky-600 font-medium">Standard Form</span>
      </div>
    </div>
  `).join('');
}

let searchDebounce = null;
function filterCards() {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(executeFilterCards, 60);
}

function executeFilterCards() {
  if (activeGalleryTab === 'prs') {
    renderPRs();
    return;
  }

  const searchInput = document.getElementById('gallery-search');
  const catSelect = document.getElementById('category-filter');
  const term = searchInput ? searchInput.value.toLowerCase().trim() : '';
  const category = catSelect ? catSelect.value : 'all';

  const filtered = materialsData.filter(m => {
    const matchesTerm = !term || 
                        (m.name || '').toLowerCase().includes(term) || 
                        (m.code || '').toLowerCase().includes(term) || 
                        (m.specs || '').toLowerCase().includes(term) || 
                        (m.supplier || '').toLowerCase().includes(term);
    const matchesCategory = category === 'all' || m.category === category;
    return matchesTerm && matchesCategory;
  });

  renderMaterials(filtered);
}

function updateHeaderKPIs() {
  const skuHeader = document.getElementById('sku-count-header');
  if (skuHeader) skuHeader.innerText = materialsData.length;
  const matBadge = document.getElementById('mat-count-badge');
  if (matBadge) matBadge.innerText = materialsData.length;

  const pendingPRs = prsData.filter(p => p.status !== 'Approved' && p.status !== 'Converted to PO' && !p.status.toLowerCase().includes('reject')).length;
  const prPendingHeader = document.getElementById('pr-pending-count');
  if (prPendingHeader) prPendingHeader.innerText = `${pendingPRs} Pending`;
  const prBadge = document.getElementById('pr-count-badge');
  if (prBadge) prBadge.innerText = prsData.length;

  const vendorHeader = document.getElementById('vendor-count-header');
  if (vendorHeader) vendorHeader.innerText = `${suppliersData.length} Active`;
  const supBadge = document.getElementById('sup-count-badge');
  if (supBadge) supBadge.innerText = suppliersData.length;

  const totalPO = pipelineData.filter(p => !['Received', 'Cancelled', 'Dock Received'].includes(p.status)).reduce((sum, item) => sum + (Number(item.rawAmount) || 0), 0);
  const poHeader = document.getElementById('po-value-header');
  if (poHeader) poHeader.innerText = `$${totalPO.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const poBadge = document.getElementById('po-count-badge');
  if (poBadge) poBadge.innerText = pipelineData.length;

  const grnHeader = document.getElementById('grn-count-header');
  if (grnHeader) grnHeader.innerText = `${grnsData.length} Logged`;
  const holdHeader = document.getElementById('hold-count-header');
  if (holdHeader) holdHeader.innerText = `${ncrsData.filter(n => n.status.startsWith('Open')).length} NCR / ${invoicesData.filter(i => i.status.startsWith('Held')).length} inv`;

  updatePRFilterCounts();
  populateDropdowns();
}

function populateDropdowns() {
  const matSelect = document.getElementById('mat-vendor-select');
  const poSelect = document.getElementById('po-vendor-select');
  if (matSelect) {
    matSelect.innerHTML = suppliersData.map(s => `<option value="${s.name}">${s.name} (${s.category})</option>`).join('');
  }
  if (poSelect) {
    poSelect.innerHTML = suppliersData.map(s => `<option value="${s.name}">${s.name}</option>`).join('');
  }
}
