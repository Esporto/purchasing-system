// Step 1 / Step 2 approval modal
'use strict';

// MULTI-ITEM PR APPROVAL MODAL TRIGGER
function openApprovalModal(prNumber, step) {
  const rawPr = prsData.find(p => p.prNumber === prNumber);
  if (!rawPr) return;
  const pr = sanitizePR(rawPr);

  if (step === 2) {
    const canApproveStep2 = isUserFinanceOrAdmin(currentUser);
    if (!canApproveStep2) {
      showToast("Authorization Restricted", "Step 2 Final Authorization strictly requires Finance Department Head or Master Admin authority.", "error");
      return;
    }
  }

  document.getElementById('pr-approval-target-pr').value = prNumber;
  document.getElementById('pr-approval-target-step').value = step;

  const headerEl = document.getElementById('pr-modal-header');
  const titleEl = document.getElementById('pr-modal-title');
  const prNumEl = document.getElementById('pr-modal-pr-num');
  const securityNotice = document.getElementById('pr-step2-security-notice');
  const roleSelect = document.getElementById('pr-approver-role');
  const decisionSelect = document.getElementById('pr-approver-decision');
  const remarksInput = document.getElementById('pr-approver-remarks');

  if (decisionSelect) decisionSelect.value = "Approved";
  if (remarksInput) remarksInput.value = "";

  if (prNumEl) prNumEl.innerText = `${pr.prNumber} (${pr.items.length} Line Items)`;
  if (document.getElementById('pr-approval-bom-display')) {
    document.getElementById('pr-approval-bom-display').innerText = pr.bomProject;
  }
  if (document.getElementById('pr-approval-budget')) {
    document.getElementById('pr-approval-budget').innerText = `$${Number(pr.estimatedTotal).toFixed(2)}`;
  }
  if (document.getElementById('pr-approval-due')) {
    document.getElementById('pr-approval-due').innerText = pr.requiredDate;
  }

  // Populate Items Breakdown Table
  const itemsTbody = document.getElementById('pr-approval-items-tbody');
  if (itemsTbody) {
    itemsTbody.innerHTML = pr.items.map(it => `
      <tr class="hover:bg-slate-50">
        <td class="p-2 mono font-bold text-sky-700">${it.itemCode}</td>
        <td class="p-2 font-medium text-slate-800">${it.itemName}</td>
        <td class="p-2 text-right mono font-semibold">${it.quantity} ${it.uom}</td>
        <td class="p-2 text-right mono text-slate-600">$${Number(it.unitRate).toFixed(2)}</td>
        <td class="p-2 text-right mono font-bold text-emerald-700">$${Number(it.extendedTotal).toFixed(2)}</td>
      </tr>
    `).join('');
  }

  const approverNameInput = document.getElementById('pr-approver-name');
  if (approverNameInput && currentUser) {
    approverNameInput.value = currentUser.fullName || currentUser.name || '';
  }

  if (step === 1) {
    titleEl.innerText = "Step 1: Production & Technical Lead Review";
    if (headerEl) headerEl.className = "bg-amber-700 text-white px-6 py-4 flex items-center justify-between shrink-0";
    if (securityNotice) securityNotice.classList.add('hidden');
    if (roleSelect) {
      roleSelect.innerHTML = `
        <option value="Production Head / Tech Lead">Production Head / Project Tech Lead</option>
        <option value="Master Admin / General Manager">Master Admin / General Manager</option>
      `;
      roleSelect.value = isUserAdmin(currentUser) ? "Master Admin / General Manager" : "Production Head / Tech Lead";
    }
  } else {
    titleEl.innerText = "Step 2: Finance Head / Master Admin Authorization";
    if (headerEl) headerEl.className = "bg-purple-900 text-white px-6 py-4 flex items-center justify-between shrink-0";
    if (securityNotice) securityNotice.classList.remove('hidden');
    if (roleSelect) {
      roleSelect.innerHTML = `
        <option value="Finance Department Head">Finance Department Head</option>
        <option value="Master Admin / General Manager">Master Admin / General Manager</option>
      `;
      roleSelect.value = isUserAdmin(currentUser) ? "Master Admin / General Manager" : "Finance Department Head";
    }
  }

  handleDecisionChange();
  openModal('pr-approval-modal');
}

function handleDecisionChange() {
  const decision = document.getElementById('pr-approver-decision')?.value;
  const step = parseInt(document.getElementById('pr-approval-target-step')?.value || '1');
  const submitBtn = document.getElementById('pr-modal-submit-btn');
  const label = document.getElementById('pr-remarks-label');
  const hint = document.getElementById('pr-remarks-hint');
  const remarksTextarea = document.getElementById('pr-approver-remarks');

  if (decision === 'Rejected') {
    if (label) label.innerHTML = '<span class="text-rose-700 font-bold">Mandatory Reason for Rejection *</span>';
    if (hint) hint.innerText = "Explain why this requisition is rejected so the requester can revise it.";
    if (remarksTextarea) {
      remarksTextarea.required = true;
      remarksTextarea.placeholder = "e.g. Profile thickness or quantity exceeds BOM allowance. Revise line items.";
    }
    if (submitBtn) {
      submitBtn.className = "px-5 py-2 bg-rose-600 hover:bg-rose-500 text-white font-semibold rounded-xl shadow-sm transition";
      submitBtn.innerHTML = "Reject &amp; Return Requisition";
    }
  } else {
    if (label) label.innerText = "Signatory Notes & Verification Remarks";
    if (hint) hint.innerText = "Stamped on the audit voucher docket.";
    if (remarksTextarea) {
      remarksTextarea.required = false;
      remarksTextarea.placeholder = "e.g. Specifications verified against CAD profile and cutting list.";
    }
    if (submitBtn) {
      submitBtn.className = step === 1 
        ? "px-5 py-2 bg-amber-600 hover:bg-amber-500 text-white font-semibold rounded-xl shadow-sm transition"
        : "px-5 py-2 bg-purple-600 hover:bg-purple-500 text-white font-semibold rounded-xl shadow-sm transition";
      submitBtn.innerHTML = "Sign &amp; Authorize";
    }
  }
}

function showUnauthorizedStep2Notice() {
  showToast("Access Restricted", "Step 2 sign-off requires Finance Department Head or Master Admin clearance.", "error");
}

async function submitPRApproval(e) {
  e.preventDefault();
  const prNumber = document.getElementById('pr-approval-target-pr').value;
  const step = parseInt(document.getElementById('pr-approval-target-step').value);
  const decision = document.getElementById('pr-approver-decision').value;
  const remarks = document.getElementById('pr-approver-remarks').value.trim();
  if (decision === 'Rejected' && !remarks) { showToast("Reason Required", "Please provide a reason for rejecting this requisition.", "error"); return; }
  await mutate(() => api('POST', `/prs/${encodeURIComponent(prNumber)}/approve`, { step, decision, remarks }), () => closeModal('pr-approval-modal'),
    decision === 'Rejected' ? "PR Returned for Revision" : (step === 1 ? "Step 1 Endorsed" : "Step 2 Authorized"), `${prNumber}: ${decision} at Step ${step}.`);
}
