// Revising a rejected PR and converting an approved PR to POs
'use strict';

// MULTI-ITEM REVISION MODAL
let revisionLines = [];
function openRevisePRModal(prNumber) {
  const pr = prsData.find(p => p.prNumber === prNumber);
  if (!pr) return;

  document.getElementById('revise-target-pr').value = pr.prNumber;
  document.getElementById('revise-modal-pr-num').innerText = `${pr.prNumber} (${pr.items.length} Lines)`;
  document.getElementById('revise-due-date').value = pr.requiredDate;
  document.getElementById('revise-bom').value = unesc(pr.bomProject);
  document.getElementById('revise-changelog').value = "";

  const rejectedStep = (pr.step2 && pr.step2.rejected) ? pr.step2 : pr.step1;
  const feedbackEl = document.getElementById('revise-previous-feedback');
  if (feedbackEl) {
    feedbackEl.innerText = `${rejectedStep.by || 'Reviewer'} (${rejectedStep.role || 'Authority'}): "${rejectedStep.notes || 'Revise specifications and resubmit.'}"`;
  }

  revisionLines = JSON.parse(JSON.stringify(pr.items));
  renderRevisionItems();
  openModal('pr-revision-modal');
}

function renderRevisionItems() {
  const container = document.getElementById('revise-items-container');
  if (!container) return;

  container.innerHTML = revisionLines.map((it, idx) => `
    <div class="bg-white border border-slate-200 rounded-lg p-2.5 space-y-1.5">
      <div class="flex justify-between items-center text-xs">
        <span class="mono font-bold text-sky-700">${it.itemCode}</span>
        <span class="mono font-bold text-emerald-700" id="revise-sub-${idx}">$${Number(it.extendedTotal).toFixed(2)}</span>
      </div>
      <input type="text" value="${it.itemName}" oninput="onRevisionItemChange(${idx}, 'itemName', this.value)" class="w-full px-2 py-1 border border-slate-200 rounded text-xs font-semibold">
      <input type="text" value="${it.itemSpecs}" oninput="onRevisionItemChange(${idx}, 'itemSpecs', this.value)" class="w-full px-2 py-1 border border-slate-200 rounded text-xs text-slate-600">
      <div class="grid grid-cols-2 gap-2 pt-1">
        <div>
          <label class="block text-[10px] text-slate-500">Revised Qty (${it.uom})</label>
          <input type="number" min="1" value="${it.quantity}" oninput="onRevisionItemChange(${idx}, 'quantity', this.value)" class="w-full px-2 py-1 border border-slate-200 rounded text-xs mono">
        </div>
        <div>
          <label class="block text-[10px] text-slate-500">Unit Rate ($)</label>
          <input type="number" step="0.01" min="0" value="${it.unitRate}" oninput="onRevisionItemChange(${idx}, 'unitRate', this.value)" class="w-full px-2 py-1 border border-slate-200 rounded text-xs mono">
        </div>
      </div>
    </div>
  `).join('');

  calculateRevisionGrandTotal();
}

function onRevisionItemChange(idx, field, value) {
  if (field === 'quantity') {
    const q = Math.max(1, parseFloat(value) || 0);
    revisionLines[idx].quantity = q;
    revisionLines[idx].extendedTotal = q * revisionLines[idx].unitRate;
  } else if (field === 'unitRate') {
    const r = Math.max(0, parseFloat(value) || 0);
    revisionLines[idx].unitRate = r;
    revisionLines[idx].extendedTotal = revisionLines[idx].quantity * r;
  } else if (field === 'itemName') {
    revisionLines[idx].itemName = value;
  } else if (field === 'itemSpecs') {
    revisionLines[idx].itemSpecs = value;
  }

  const subEl = document.getElementById(`revise-sub-${idx}`);
  if (subEl) subEl.innerText = `$${revisionLines[idx].extendedTotal.toFixed(2)}`;
  calculateRevisionGrandTotal();
}

function calculateRevisionGrandTotal() {
  const grandTotal = revisionLines.reduce((sum, it) => sum + (it.extendedTotal || 0), 0);
  const display = document.getElementById('revise-est-budget');
  if (display) {
    display.innerText = `$${grandTotal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
}

async function submitPRRevision(e) {
  e.preventDefault();
  const prNumber = document.getElementById('revise-target-pr').value;
  const body = { required_date: document.getElementById('revise-due-date').value, bom_project: document.getElementById('revise-bom').value.trim(),
    changelog: document.getElementById('revise-changelog').value.trim(), items: revisionLines.map(prLine) };
  await mutate(() => api('PUT', `/prs/${encodeURIComponent(prNumber)}`, body), () => closeModal('pr-revision-modal'),
    "PR Resubmitted", `${prNumber} revised and returned to Step 1 Technical Review.`);
}

async function convertPRToPO(prNumber) {
  const r = await mutate(() => api('POST', `/prs/${encodeURIComponent(prNumber)}/convert`, {}), () => switchGallery('pipeline'));
  if (r) showToast("PO Issued", `${prNumber} became ${r.purchase_orders.map(p => p.po_number).join(', ')} (one PO per vendor).`);
}
