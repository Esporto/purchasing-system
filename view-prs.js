// PR gallery: filters, sorting, cards
'use strict';

// PR FILTER & SORT HANDLERS
function setPRFilter(filterKey) {
  activePRFilter = filterKey;
  
  const filterKeys = ['all', 'pending-step1', 'pending-step2', 'approved', 'rejected'];
  filterKeys.forEach(k => {
    const btn = document.getElementById(`pr-filter-${k}`);
    if (!btn) return;
    if (k === filterKey) {
      btn.className = "pr-filter-btn px-3 py-1.5 rounded-xl font-semibold bg-purple-600 text-white shadow-xs shrink-0 transition flex items-center gap-1.5";
    } else {
      btn.className = "pr-filter-btn px-3 py-1.5 rounded-xl font-medium bg-slate-100 text-slate-700 hover:bg-slate-200 shrink-0 transition flex items-center gap-1.5";
    }
  });

  renderPRs();
}

function setPRSort(sortKey) {
  activePRSort = sortKey;
  renderPRs();
}

function updatePRFilterCounts() {
  const allCount = prsData.length;
  const step1Count = prsData.filter(p => !p.step1?.approved && !p.step1?.rejected && !p.status.toLowerCase().includes('reject')).length;
  const step2Count = prsData.filter(p => p.step1?.approved && !p.step2?.approved && !p.step2?.rejected && !p.status.toLowerCase().includes('reject')).length;
  const approvedCount = prsData.filter(p => p.step1?.approved && p.step2?.approved).length;
  const rejectedCount = prsData.filter(p => p.status.toLowerCase().includes('reject') || p.step1?.rejected || p.step2?.rejected).length;

  const cAll = document.getElementById('pr-filter-count-all');
  const cStep1 = document.getElementById('pr-filter-count-step1');
  const cStep2 = document.getElementById('pr-filter-count-step2');
  const cAppr = document.getElementById('pr-filter-count-approved');
  const cRej = document.getElementById('pr-filter-count-rejected');

  if (cAll) cAll.innerText = allCount;
  if (cStep1) cStep1.innerText = step1Count;
  if (cStep2) cStep2.innerText = step2Count;
  if (cAppr) cAppr.innerText = approvedCount;
  if (cRej) cRej.innerText = rejectedCount;
}

// RENDER MULTI-LINE PR GALLERY
function renderPRs() {
  const container = document.getElementById('prs-grid');
  if (!container) return;

  updatePRFilterCounts();

  const searchInput = document.getElementById('gallery-search');
  const term = (searchInput ? searchInput.value : '').toLowerCase().trim();

  let filtered = prsData.filter(rawPr => {
    const pr = sanitizePR(rawPr);
    const isRejected = pr.status.toLowerCase().includes('reject') || (pr.step1 && pr.step1.rejected) || (pr.step2 && pr.step2.rejected);
    const step1Done = Boolean(pr.step1 && pr.step1.approved);
    const step2Done = Boolean(pr.step2 && pr.step2.approved);

    if (activePRFilter === 'pending-step1') return !step1Done && !isRejected;
    if (activePRFilter === 'pending-step2') return step1Done && !step2Done && !isRejected;
    if (activePRFilter === 'approved') return step1Done && step2Done && !isRejected;
    if (activePRFilter === 'rejected') return isRejected;
    return true;
  });

  if (term) {
    filtered = filtered.filter(pr => {
      const matchItems = pr.items.some(i => 
        (i.itemCode || '').toLowerCase().includes(term) ||
        (i.itemName || '').toLowerCase().includes(term) ||
        (i.itemSpecs || '').toLowerCase().includes(term)
      );
      return matchItems ||
             (pr.prNumber || '').toLowerCase().includes(term) ||
             (pr.department || '').toLowerCase().includes(term) ||
             (pr.requester || '').toLowerCase().includes(term) ||
             (pr.bomProject || '').toLowerCase().includes(term);
    });
  }

  filtered.sort((a, b) => {
    if (activePRSort === 'due') {
      return new Date(a.requiredDate || 0) - new Date(b.requiredDate || 0);
    } else if (activePRSort === 'budget') {
      return Number(b.estimatedTotal || 0) - Number(a.estimatedTotal || 0);
    } else if (activePRSort === 'priority') {
      const rank = p => {
        const low = (p.priority || '').toLowerCase();
        if (low.includes('crit') || low.includes('stop')) return 3;
        if (low.includes('urg')) return 2;
        return 1;
      };
      return rank(b) - rank(a);
    }
    return (b.prNumber || '').localeCompare(a.prNumber || '');
  });

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="col-span-full py-12 text-center bg-white rounded-2xl border border-slate-200">
        <div class="w-10 h-10 text-purple-300 mx-auto mb-2 flex items-center justify-center">
          <i data-lucide="file-check" class="w-8 h-8"></i>
        </div>
        <p class="text-sm font-semibold text-slate-700">No matching Purchase Requisitions</p>
        <p class="text-xs text-slate-400 mt-1">Try switching filter tabs or clearing your search keywords.</p>
      </div>
    `;
    lucide.createIcons();
    return;
  }

  const isStep2Authorized = isUserFinanceOrAdmin(currentUser);

  container.innerHTML = filtered.map(rawPr => {
    const pr = sanitizePR(rawPr);
    const isRejected = pr.status.toLowerCase().includes('reject') || pr.status.toLowerCase().includes('return') || (pr.step1 && pr.step1.rejected) || (pr.step2 && pr.step2.rejected);
    const step1Done = Boolean(pr.step1 && pr.step1.approved);
    const step2Done = Boolean(pr.step2 && pr.step2.approved);

    let rejectionCallout = '';
    if (isRejected) {
      const rejectedStep = (pr.step2 && pr.step2.rejected) ? pr.step2 : pr.step1;
      rejectionCallout = `
        <div class="bg-rose-50 border border-rose-200 rounded-xl p-2.5 text-xs text-rose-800 space-y-1">
          <div class="flex items-center gap-1.5 font-bold text-rose-900">
            <i data-lucide="alert-octagon" class="w-3.5 h-3.5 text-rose-600 shrink-0"></i>
            <span>Returned for Revision</span>
          </div>
          <p class="text-[11px] italic leading-tight">"${rejectedStep.notes || 'Please verify specifications and resubmit.'}"</p>
          <span class="text-[10px] text-rose-600 font-medium block">By: ${rejectedStep.by || 'Reviewer'} (${rejectedStep.date || 'Recently'})</span>
        </div>
      `;
    }

    let actionButtons = '';
    if (isRejected) {
      actionButtons = `
        <button onclick="openRevisePRModal('${pr.prNumber}')" class="w-full py-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded-lg font-semibold text-xs transition flex items-center justify-center gap-1.5 shadow-sm active:scale-95">
          <i data-lucide="edit-3" class="w-3.5 h-3.5"></i>
          <span>Revise &amp; Resubmit PR</span>
        </button>
      `;
    } else if (!step1Done) {
      actionButtons = `
        <button onclick="openApprovalModal('${pr.prNumber}', 1)" class="w-full py-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded-lg font-semibold text-xs transition flex items-center justify-center gap-1.5 shadow-sm active:scale-95">
          <i data-lucide="check-circle-2" class="w-3.5 h-3.5"></i>
          <span>Step 1: Tech Approval</span>
        </button>
      `;
    } else if (!step2Done) {
      if (isStep2Authorized) {
        actionButtons = `
          <button onclick="openApprovalModal('${pr.prNumber}', 2)" class="w-full py-1.5 bg-purple-600 hover:bg-purple-500 text-white rounded-lg font-semibold text-xs transition flex items-center justify-center gap-1.5 shadow-sm active:scale-95">
            <i data-lucide="check-circle-2" class="w-3.5 h-3.5"></i>
            <span>Step 2: Finance / Admin Sign-off</span>
          </button>
        `;
      } else {
        actionButtons = `
          <button type="button" onclick="showUnauthorizedStep2Notice()" class="w-full py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-500 rounded-lg font-semibold text-xs transition flex items-center justify-center gap-1.5 border border-slate-200 cursor-not-allowed">
            <i data-lucide="lock" class="w-3.5 h-3.5 text-slate-400"></i>
            <span>🔒 Step 2: Finance / Admin Only</span>
          </button>
        `;
      }
    } else if (pr.status !== 'Converted to PO') {
      actionButtons = `
        <button onclick="convertPRToPO('${pr.prNumber}')" class="w-full py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg font-semibold text-xs transition flex items-center justify-center gap-1.5 shadow-sm active:scale-95">
          <i data-lucide="arrow-right-circle" class="w-3.5 h-3.5"></i>
          <span>Convert to PO</span>
        </button>
      `;
    } else {
      actionButtons = `
        <div class="w-full py-1.5 bg-slate-100 text-slate-500 rounded-lg font-semibold text-xs text-center border border-slate-200">
          ✓ PO Issued
        </div>
      `;
    }

    let step1Text = 'Pending Tech';
    let step1Dot = 'bg-amber-400 animate-pulse';
    if (pr.step1 && pr.step1.rejected) {
      step1Text = '❌ Rejected: ' + (pr.step1.by || 'Tech');
      step1Dot = 'bg-rose-500';
    } else if (step1Done) {
      step1Text = '✓ ' + (pr.step1.by || 'Tech Lead');
      step1Dot = 'bg-emerald-500';
    }

    let step2Text = 'Pending Finance';
    let step2Dot = step1Done ? 'bg-purple-400 animate-pulse' : 'bg-slate-300';
    if (pr.step2 && pr.step2.rejected) {
      step2Text = '❌ Rejected: ' + (pr.step2.by || 'Finance');
      step2Dot = 'bg-rose-500';
    } else if (step2Done) {
      step2Text = '✓ ' + (pr.step2.by || 'Finance Head');
      step2Dot = 'bg-emerald-500';
    }

    // Multi-line preview list
    const itemsList = pr.items.slice(0, 2).map(it => `
      <div class="flex items-center justify-between text-[11px] py-0.5 border-b border-slate-100 last:border-b-0">
        <span class="text-slate-800 truncate pr-2 font-medium">${it.itemName}</span>
        <span class="mono text-slate-500 shrink-0 font-semibold">${it.quantity} ${it.uom}</span>
      </div>
    `).join('');

    const extraCount = pr.items.length > 2 ? `<span class="text-[10px] text-purple-700 font-semibold block pt-1">+ ${pr.items.length - 2} more item lines</span>` : '';

    return `
      <div class="bg-white rounded-2xl border border-slate-200 shadow-xs p-4 card-contain flex flex-col justify-between space-y-3 relative">
        <div>
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-1.5">
                <span class="mono text-xs font-bold text-purple-700 bg-purple-50 border border-purple-200 px-2 py-0.5 rounded">${pr.prNumber}</span>
                <span class="text-[10px] font-bold text-purple-900 bg-purple-100 px-1.5 py-0.5 rounded-full">${pr.items.length} Lines</span>
              </div>
              <span class="block text-[10px] text-slate-500 font-medium mt-1 truncate" title="${pr.department}">${pr.department}</span>
            </div>
            <div class="flex items-center gap-1 shrink-0">
              <span class="text-[10px] px-2 py-0.5 rounded-full border ${pr.priorityColor}">${pr.priority}</span>
              <button onclick="promptDelete('pr', '${pr.prNumber}')" aria-label="Delete PR" class="text-slate-300 hover:text-rose-600 hover:bg-rose-50 p-1 rounded transition">
                ${ICONS.trash}
              </button>
            </div>
          </div>

          <!-- Lines Preview Box -->
          <div class="mt-2.5 bg-slate-50 border border-slate-100 rounded-xl p-2.5 space-y-0.5">
            <span class="text-[9px] uppercase font-bold text-slate-400 block mb-1">Item Schedule:</span>
            ${itemsList}
            ${extraCount}
          </div>

          <!-- 2-Step Approval Status Pill -->
          <div class="mt-2.5 flex items-center gap-1.5 flex-wrap">
            <span class="w-2 h-2 rounded-full ${step1Dot} shrink-0"></span>
            <span class="text-[10px] font-semibold text-slate-600 truncate max-w-[125px]">Step 1: ${step1Text}</span>
            <span class="text-slate-300 text-xs">&bull;</span>
            <span class="w-2 h-2 rounded-full ${step2Dot} shrink-0"></span>
            <span class="text-[10px] font-semibold text-slate-600 truncate max-w-[125px]">Step 2: ${step2Text}</span>
          </div>
        </div>

        ${rejectionCallout}

        <div class="bg-slate-50 border border-slate-100 rounded-xl p-2.5 space-y-1 text-xs">
          <div class="flex justify-between items-center text-slate-600">
            <span class="text-[11px]">Total Requisition Budget:</span>
            <span class="mono font-bold text-emerald-700">$${Number(pr.estimatedTotal).toFixed(2)}</span>
          </div>
          <div class="flex justify-between items-center text-slate-600">
            <span class="text-[11px]">Required By:</span>
            <span class="mono font-medium text-slate-800">${pr.requiredDate}</span>
          </div>
          <div class="flex justify-between items-center text-slate-600">
            <span class="text-[11px]">Project:</span>
            <span class="text-slate-700 truncate font-medium max-w-[140px]">${pr.bomProject}</span>
          </div>
        </div>

        <div class="pt-2 border-t border-slate-100 space-y-2">
          ${actionButtons}
          <button onclick="viewPRVoucher('${pr.prNumber}')" class="w-full py-1 text-slate-600 hover:text-purple-700 hover:bg-purple-50 rounded-lg text-[11px] font-medium transition flex items-center justify-center gap-1">
            <i data-lucide="file-text" class="w-3.5 h-3.5"></i>
            <span>View Official Voucher Docket</span>
          </button>
        </div>
      </div>
    `;
  }).join('');

  lucide.createIcons();
}
