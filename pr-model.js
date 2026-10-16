// sanitizePR(): normalises a requisition object before it is rendered
'use strict';

// MULTI-ITEM DEFENSIVE SANITIZER
// Ensures every PR has an array of `items` and a computed `estimatedTotal`
function sanitizePR(raw) {
  if (!raw) return null;

  let items = [];
  if (Array.isArray(raw.items) && raw.items.length > 0) {
    items = raw.items.map(it => {
      const q = Number(it.quantity || it.qty || 1);
      const r = Number(it.unitRate || it.rate || 0);
      return {
        itemCode: it.itemCode || 'SKU-GEN',
        itemName: it.itemName || 'Architectural Specification Item',
        itemSpecs: it.itemSpecs || 'Standard architectural specifications',
        quantity: q,
        uom: (it.uom || 'UNITS').toUpperCase(),
        unitRate: r,
        extendedTotal: Number(it.extendedTotal || (q * r))
      };
    });
  } else {
    // Legacy single item migration
    const q = Number(raw.quantity || raw.qty || 1);
    const r = Number(raw.unitRate || raw.rate || raw.stdCost || 0);
    items = [{
      itemCode: raw.itemCode || 'SKU-GEN',
      itemName: raw.itemName || raw.name || raw.itemTitle || 'Architectural Specification SKU',
      itemSpecs: raw.itemSpecs || raw.specs || raw.description || 'Standard specifications',
      quantity: q,
      uom: (raw.uom || 'UNITS').toUpperCase(),
      unitRate: r,
      extendedTotal: Number(raw.estimatedTotal || (q * r))
    }];
  }

  const grandTotal = items.reduce((sum, it) => sum + (it.extendedTotal || 0), 0);
  const totalUnits = items.reduce((sum, it) => sum + (it.quantity || 0), 0);

  const priority = raw.priority || 'Routine';
  const step1 = raw.step1 || {};
  const step2 = raw.step2 || {};
  const status = raw.status || 'Pending Step 1: Technical Review';

  let statusBadge = raw.statusBadge;
  if (!statusBadge) {
    if (status.toLowerCase().includes('reject') || status.toLowerCase().includes('return')) {
      statusBadge = 'bg-rose-50 text-rose-800 border-rose-300 font-bold pulse-rose';
    } else if (status === 'Approved' || status === 'Converted to PO') {
      statusBadge = 'bg-emerald-50 text-emerald-800 border-emerald-300 font-bold';
    } else if (status.includes('Step 2')) {
      statusBadge = 'bg-purple-50 text-purple-800 border-purple-300 pulse-purple';
    } else {
      statusBadge = 'bg-amber-50 text-amber-800 border-amber-300 pulse-amber';
    }
  }

  return {
    prNumber: raw.prNumber || ('PR-' + Math.floor(1000 + Math.random() * 9000)),
    department: raw.department || raw.dept || 'Production - Fabrication Line A',
    requester: raw.requester || raw.requesterName || raw.submittedBy || 'Procurement Team',
    requiredDate: raw.requiredDate || raw.dueDate || '2026-10-05',
    priority: priority,
    priorityColor: getPriorityBadgeClass(priority),
    status: status,
    statusBadge: statusBadge,
    bomProject: raw.bomProject || raw.project || 'General Assembly / Project Demand',
    items: items,
    estimatedTotal: grandTotal,
    totalUnits: totalUnits,
    // Primary alias for card headers
    itemCode: items[0].itemCode,
    itemName: items[0].itemName,
    itemSpecs: items[0].itemSpecs,
    quantity: items[0].quantity,
    uom: items[0].uom,
    unitRate: items[0].unitRate,
    step1: {
      approved: Boolean(step1.approved),
      rejected: Boolean(step1.rejected),
      by: step1.by || '',
      role: step1.role || 'Production Head / Tech Lead',
      date: step1.date || '',
      notes: step1.notes || '',
      decision: step1.decision || (step1.approved ? 'Approved' : (step1.rejected ? 'Rejected' : ''))
    },
    step2: {
      approved: Boolean(step2.approved),
      rejected: Boolean(step2.rejected),
      by: step2.by || '',
      role: step2.role || 'Finance Department Head',
      date: step2.date || '',
      notes: step2.notes || '',
      decision: step2.decision || (step2.approved ? 'Approved' : (step2.rejected ? 'Rejected' : ''))
    },
    revisions: Array.isArray(raw.revisions) ? raw.revisions : []
  };
}

// MASTER MATERIALS CATALOG
const defaultMaterials = [];

// INITIAL MULTI-LINE DEMO REQUISITIONS
const defaultPRs = [];

const defaultSuppliers = [];

const defaultPipeline = [];

const defaultUsers = [];
