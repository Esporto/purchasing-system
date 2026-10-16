// Create forms: material, PR, supplier, PO
'use strict';

async function submitMaterial(e) {
  e.preventDefault();
  const form = e.target;
  const v = id => document.getElementById(id).value.trim();
  const num = id => parseFloat(document.getElementById(id).value) || 0;
  const code = v('mat-code').toUpperCase(), uom = v('mat-uom').toUpperCase();
  if (materialsData.some(m => m.code === code)) { showToast("SKU Exists", `Material code ${code} is already registered.`, "error"); return; }
  const body = { code, category: document.getElementById('mat-category').value, name: v('mat-name'), specs: v('mat-specs'), uom,
    current_stock: num('mat-stock'), safety_stock: num('mat-safety'), reorder_point: num('mat-rop'), std_cost: num('mat-cost'),
    supplier: document.getElementById('mat-vendor-select').value, bom_link: v('mat-bom') || 'General Assembly',
    tolerance: '± 0.05 mm standard tolerance', packaging: 'Production export packaging', lead_time: '7 days', usage_rate: `${Math.round(num('mat-rop') / 10)} ${uom} / day` };
  await mutate(() => api('POST', '/materials', body), () => { closeModal('new-entry-modal'); form.reset(); switchGallery('materials'); }, "SKU Added", `${body.name} (${code}) created.`);
}

// MULTI-LINE PR SUBMISSION
async function submitPR(e) {
  e.preventDefault();
  const form = e.target;
  if (!prLinesBuilder || prLinesBuilder.length === 0) { showToast("No Line Items", "Please add at least one item line to your requisition.", "error"); return; }
  const body = { department: document.getElementById('pr-department').value, priority: document.getElementById('pr-priority').value,
    required_date: document.getElementById('pr-due-date').value, bom_project: document.getElementById('pr-bom-proj').value.trim(), items: prLinesBuilder.map(prLine) };
  const r = await mutate(() => api('POST', '/prs', body), () => { closeModal('new-entry-modal'); form.reset(); switchGallery('prs'); });
  if (r) showToast("PR Submitted", `Requisition ${r.pr_number} with ${r.items.length} line items submitted.`);
}

async function submitSupplier(e) {
  e.preventDefault();
  const form = e.target;
  const v = id => document.getElementById(id).value.trim();
  const id = v('sup-id').toUpperCase();
  if (suppliersData.some(s => s.id === id)) { showToast("Vendor Exists", `Vendor ID ${id} is already registered.`, "error"); return; }
  const body = { id, name: v('sup-name'), category: v('sup-cat'), tier: document.getElementById('sup-tier').value, score: parseInt(v('sup-score')) || 85,
    payment_terms: v('sup-terms'), lead_time: v('sup-lead'), otif: v('sup-otif'), contact: v('sup-contact'), qc_rate: '99.0%' };
  await mutate(() => api('POST', '/suppliers', body), () => { closeModal('new-entry-modal'); form.reset(); switchGallery('suppliers'); }, "Vendor Added", `${body.name} registered on ASL.`);
}

async function submitPO(e) {
  e.preventDefault();
  const form = e.target;
  const v = id => document.getElementById(id).value.trim();
  const status = document.getElementById('po-status').value;
  const po_number = v('po-num').toUpperCase();
  if (pipelineData.some(p => p.poNumber === po_number)) { showToast("PO Exists", `${po_number} already exists.`, "error"); return; }
  const body = { po_number, vendor: document.getElementById('po-vendor-select').value, items: v('po-items'), amount_usd: parseFloat(v('po-val')) || 0,
    due_date: document.getElementById('po-due').value, status, alert: status === 'Delayed' ? "🔴 Expedite Required" : "On Track",
    progress_pct: status === 'In Transit' ? 70 : (status === 'Arrived at Dock' ? 90 : (status === 'Delayed' ? 40 : 25)), dock_action: v('po-action') || 'PO dispatched to vendor.' };
  await mutate(() => api('POST', '/orders', body), () => { closeModal('new-entry-modal'); form.reset(); switchGallery('pipeline'); }, "PO Issued", `Order ${po_number} dispatched.`);
}
