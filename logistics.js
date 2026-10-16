// logistics.js - Phase 3 screens: dock receiving (Form 04 GRN), quarantine / NCR, supplier invoices and the 3-way match
'use strict';

let grnsData = [], ncrsData = [], invoicesData = [], logiTab = 'pos';
const BAYS = ['Bay 1 (Extrusion Unloading)', 'Bay 2 (Glass Cradle Crane)', 'Bay 3 (Hardware & Carton Staging)', 'Bay 4 (Sealants & Chemical Storage)'];
const RECEIVABLE_STATES = ['Order Confirmed', 'In Transit', 'Arrived at Dock', 'Delayed', 'Partially Delivered (Open Balance)'];
const can = (...roles) => !!currentUser && roles.includes(currentUser.role);
const pill = (text, cls) => `<span class="text-[10px] px-2 py-0.5 rounded-full border font-semibold ${cls}">${text}</span>`;
const GRN_CLS = { 'Inspected & Passed': 'bg-emerald-100 text-emerald-800 border-emerald-300', 'Quarantined / Defect': 'bg-rose-100 text-rose-800 border-rose-300', 'Defect Resolved': 'bg-sky-100 text-sky-800 border-sky-300' };
const INV_CLS = { 'Matched - Ready for Payment': 'bg-emerald-100 text-emerald-800 border-emerald-300', 'Held - Variance': 'bg-rose-100 text-rose-800 border-rose-300',
                  'Released for Payment': 'bg-sky-100 text-sky-800 border-sky-300', 'Released (Override)': 'bg-amber-100 text-amber-800 border-amber-300' };
const BTN = 'px-3 py-1.5 rounded-lg text-xs font-semibold border transition';
const INPUT = 'w-full px-2 py-1 border border-slate-200 rounded-lg text-xs';

// ---- server records -> view objects (free text is escaped here, identifiers are validated by the server)
const mapNCR = n => ({ ...n, item_name: esc(n.item_name), reason: esc(n.reason), resolution_notes: esc(n.resolution_notes), resolved_by: esc(n.resolved_by) });
const mapGRN = g => ({ ...g, vendor: esc(g.vendor), delivery_note: esc(g.delivery_note), vehicle_plate: esc(g.vehicle_plate), dock_bay: esc(g.dock_bay),
  received_by: esc(g.received_by), dock_notes: esc(g.dock_notes), received_at: fmtWhen(g.received_at),
  lines: g.lines.map(l => ({ ...l, item_name: esc(l.item_name), rejection_reason: esc(l.rejection_reason) })), ncrs: g.ncrs.map(mapNCR) });
const mapInvoice = i => ({ ...i, vendor: esc(i.vendor), vendor_invoice_no: esc(i.vendor_invoice_no), entered_by: esc(i.entered_by), released_by: esc(i.released_by),
  override_reason: esc(i.override_reason), entered_at: fmtWhen(i.entered_at), released_at: fmtWhen(i.released_at),
  match: { lines: i.match.lines || [], issues: (i.match.issues || []).map(x => ({ ...x, message: esc(x.message) })) } });

// ---- shell: sub-tabs, containers and modals are added to the Logistics section once
function ensureLogisticsUI() {
  if (document.getElementById('logi-tabs')) return;
  const grid = document.getElementById('pipeline-grid');
  if (!grid) return;
  grid.insertAdjacentHTML('beforebegin', '<div id="logi-tabs" class="flex flex-wrap items-center gap-2"></div>');
  grid.insertAdjacentHTML('afterend', '<div id="logi-grns" class="hidden"></div><div id="logi-ncrs" class="hidden"></div><div id="logi-inv" class="hidden"></div>');
  const modal = (id, title, body) => `<div id="${id}" class="fixed inset-0 bg-slate-900/60 z-50 hidden flex items-center justify-center p-3 overflow-y-auto">
    <div class="bg-white rounded-2xl shadow-2xl w-full max-w-4xl my-6 overflow-hidden"><div class="bg-slate-900 text-white px-5 py-3 flex items-center justify-between">
    <h3 class="font-bold text-sm">${title}</h3><button type="button" onclick="closeModal('${id}')" class="text-slate-300 hover:text-white px-2">✕</button></div>${body}</div></div>`;
  const field = (id, label, extra = '') => `<label class="block text-xs font-medium text-slate-700">${label}<input id="${id}" required ${extra} class="${INPUT} mt-1"></label>`;
  document.body.insertAdjacentHTML('beforeend',
    modal('receive-modal', 'Warehouse Dock Receiving Gate (Form 04)', `<form onsubmit="submitReceive(event)" class="p-5 space-y-3 text-xs"><input type="hidden" id="rcv-po">
      <p id="rcv-head" class="mono font-bold text-emerald-800"></p>
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">${field('rcv-do', 'Vendor delivery note *', 'placeholder="e.g. DO-AA-88219"')}${field('rcv-plate', 'Truck plate *', 'placeholder="e.g. PP-3-4829"')}
        <label class="block text-xs font-medium text-slate-700">Dock bay<select id="rcv-bay" class="${INPUT} mt-1">${BAYS.map(b => `<option>${b}</option>`).join('')}</select></label></div>
      <div class="overflow-x-auto border border-slate-200 rounded-xl"><table class="w-full text-left"><thead class="bg-slate-50 text-slate-600 text-[11px]"><tr><th class="p-2">Item</th><th class="p-2 text-right">Ordered</th>
        <th class="p-2 text-right">Accepted so far</th><th class="p-2 w-24">Arrived today</th><th class="p-2 w-24">Rejected</th><th class="p-2 w-24 text-right">Accepted</th><th class="p-2">Rejection reason</th></tr></thead>
        <tbody id="receive-lines"></tbody></table></div>
      <label class="block font-medium text-slate-700">Dock notes<textarea id="rcv-notes" rows="2" class="${INPUT} mt-1" placeholder="Crates intact, heat numbers verified..."></textarea></label>
      <p class="text-[11px] text-slate-500 italic">Rejected goods go to the quarantine bay and open a Non-Conformance Report (NCR) for QC.</p>
      <div class="flex justify-end gap-2"><button type="button" onclick="closeModal('receive-modal')" class="${BTN} border-slate-200">Cancel</button>
      <button class="${BTN} bg-emerald-700 text-white border-emerald-700">Confirm Dock Receipt (Generate GRN)</button></div></form>`) +
    modal('grn-docket-modal', 'Goods Receiving Note Voucher (Form 04)', `<div class="px-5 py-2 flex justify-end gap-2 no-print"><button onclick="window.print()" class="${BTN} border-slate-300">Print GRN</button></div>
      <div id="grn-voucher-body" class="p-6 space-y-4 text-xs text-slate-800"></div>`) +
    modal('ncr-modal', 'QC Decision on Quarantined Goods', `<form onsubmit="submitNCR(event)" class="p-5 space-y-3 text-xs"><input type="hidden" id="ncr-id"><p id="ncr-head" class="font-semibold"></p>
      <label class="block font-medium">Disposition<select id="ncr-disp" class="${INPUT} mt-1"><option>Return to Vendor</option><option>Accept under Concession</option><option>Scrap</option></select></label>
      <label class="block font-medium">Notes (required)<textarea id="ncr-notes" required rows="3" class="${INPUT} mt-1"></textarea></label>
      <div class="flex justify-end gap-2"><button type="button" onclick="closeModal('ncr-modal')" class="${BTN} border-slate-200">Cancel</button><button class="${BTN} bg-slate-900 text-white border-slate-900">Record decision</button></div></form>`) +
    modal('po-lines-modal', 'PO Line Items', `<form onsubmit="submitPOLines(event)" class="p-5 space-y-3 text-xs"><input type="hidden" id="pol-po"><p id="pol-head" class="mono font-bold text-amber-800"></p>
      <div class="overflow-x-auto border border-slate-200 rounded-xl"><table class="w-full text-left"><thead class="bg-slate-50 text-slate-600 text-[11px]"><tr><th class="p-2">Item</th><th class="p-2 w-28">Quantity</th><th class="p-2 w-28">Unit rate ($)</th><th class="p-2 w-28 text-right">Line total</th><th class="p-2 w-8"></th></tr></thead>
        <tbody id="pol-rows"></tbody><tfoot><tr class="border-t border-slate-200 bg-slate-50"><td class="p-2 text-right font-bold" colspan="3">PO value</td><td class="p-2 text-right mono font-bold" id="pol-total">$0.00</td><td></td></tr></tfoot></table></div>
      <button type="button" onclick="addPOLineRow()" class="${BTN} border-slate-300">+ Add item</button>
      <p class="text-[11px] text-slate-500">Rates start at the catalogue standard cost - change them to the agreed PO price. The PO value is recalculated from these lines, and receiving and invoice matching use them.</p>
      <div class="flex justify-end gap-2"><button type="button" onclick="closeModal('po-lines-modal')" class="${BTN} border-slate-200">Cancel</button><button class="${BTN} bg-amber-600 text-white border-amber-600">Save line items</button></div></form>`) +
    modal('invoice-modal', 'Enter Supplier Invoice (3-Way Match)', `<form onsubmit="submitInvoice(event)" class="p-5 space-y-3 text-xs">
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-3"><label class="block font-medium">Purchase order<select id="inv-po" required onchange="fillInvoiceLines()" class="${INPUT} mt-1"></select></label>
      ${field('inv-no', "Supplier's invoice no. *")}${field('inv-date', 'Invoice date *', 'type="date"')}</div>
      <p class="text-[11px] text-slate-500">Type the figures exactly as printed on the supplier's invoice. Grey hints show the accepted quantity and PO rate.</p>
      <div class="overflow-x-auto border border-slate-200 rounded-xl"><table class="w-full text-left"><thead class="bg-slate-50 text-slate-600 text-[11px]"><tr><th class="p-2">Item</th><th class="p-2 w-32">Invoice qty</th><th class="p-2 w-32">Invoice unit rate</th></tr></thead><tbody id="inv-lines"></tbody></table></div>
      <div class="flex justify-end gap-2"><button type="button" onclick="closeModal('invoice-modal')" class="${BTN} border-slate-200">Cancel</button><button class="${BTN} bg-sky-700 text-white border-sky-700">Run 3-way match</button></div></form>`));
}

function setLogiTab(t) { logiTab = t; renderLogistics(); }

function renderLogistics() {
  ensureLogisticsUI();
  if (!document.getElementById('logi-tabs')) return;
  const openNcr = ncrsData.filter(n => n.status.startsWith('Open')).length;
  const tabs = [['pos', 'Open POs', pipelineData.length], ['grns', 'Dock Receipts (GRN)', grnsData.length], ['ncrs', 'Quarantine / NCR', openNcr], ['inv', 'Invoices & 3-Way Match', invoicesData.length]];
  document.getElementById('logi-tabs').innerHTML = tabs.map(([k, label, n]) => `<button onclick="setLogiTab('${k}')" class="${BTN} ${logiTab === k ? 'bg-slate-900 text-white border-slate-900' : 'bg-white text-slate-700 border-slate-200'}">${label} <span class="opacity-70">${n}</span></button>`).join('')
    + (can('finance', 'admin') ? `<button onclick="openInvoiceModal()" class="${BTN} bg-sky-700 text-white border-sky-700 ml-auto">+ Enter Invoice</button>` : '');
  document.getElementById('pipeline-grid').classList.toggle('hidden', logiTab !== 'pos');
  ['grns', 'ncrs', 'inv'].forEach(k => document.getElementById('logi-' + k).classList.toggle('hidden', logiTab !== k));
  const empty = t => `<div class="py-12 text-center bg-white rounded-2xl border border-slate-200 text-slate-500 text-xs">${t}</div>`;
  document.getElementById('logi-grns').innerHTML = grnsData.length ? `<div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">${grnsData.map(g => `
    <div class="bg-white rounded-2xl border border-slate-200 p-4 space-y-2 text-xs"><div class="flex justify-between items-center"><span class="mono font-bold text-emerald-800 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded">${g.grn_number}</span>${pill(g.status, GRN_CLS[g.status])}</div>
      <h4 class="font-bold text-slate-900">${g.vendor}</h4><p class="text-slate-600">PO <span class="mono">${g.po_number}</span> &bull; DO ${g.delivery_note} &bull; ${g.vehicle_plate}</p>
      <p class="text-slate-500">${g.dock_bay}<br>${g.received_by} &bull; ${g.received_at}</p>
      <p class="text-slate-700">${g.lines.map(l => `${l.item_code}: <b>${l.accepted_qty}</b> accepted${l.rejected_qty ? `, <b class="text-rose-700">${l.rejected_qty}</b> rejected` : ''}`).join('<br>')}</p>
      <button onclick="viewGRNDocket('${g.grn_number}')" class="${BTN} w-full border-slate-200 hover:bg-emerald-50">View Form 04 docket</button></div>`).join('')}</div>` : empty('No goods received yet. Open the Open POs tab and use "Receive Cargo".');
  document.getElementById('logi-ncrs').innerHTML = ncrsData.length ? `<div class="bg-white rounded-2xl border border-slate-200 overflow-x-auto"><table class="w-full text-left text-xs"><thead class="bg-slate-50 text-slate-600"><tr><th class="p-2.5">NCR</th><th class="p-2.5">GRN / PO</th><th class="p-2.5">Item</th><th class="p-2.5 text-right">Qty</th><th class="p-2.5">Defect</th><th class="p-2.5">Status / decision</th><th class="p-2.5"></th></tr></thead><tbody>${ncrsData.map(n => `
    <tr class="border-t border-slate-100"><td class="p-2.5 mono font-bold">${n.ncr_number}</td><td class="p-2.5 mono">${n.grn_number}<br>${n.po_number}</td><td class="p-2.5">${n.item_name}<div class="mono text-[10px] text-slate-500">${n.item_code}</div></td>
    <td class="p-2.5 text-right mono">${n.quantity} ${n.uom}</td><td class="p-2.5">${n.reason}</td>
    <td class="p-2.5">${n.status.startsWith('Open') ? pill(n.status, 'bg-rose-100 text-rose-800 border-rose-300') : `${pill('Closed', 'bg-slate-100 text-slate-700 border-slate-300')} <b>${n.disposition}</b><div class="text-[11px] text-slate-500">${n.resolved_by}: ${n.resolution_notes}</div>`}</td>
    <td class="p-2.5">${n.status.startsWith('Open') && can('engineer', 'admin') ? `<button onclick="openNCRModal('${n.ncr_number}')" class="${BTN} border-slate-300">QC decision</button>` : ''}</td></tr>`).join('')}</tbody></table></div>` : empty('No quarantined goods.');
  document.getElementById('logi-inv').innerHTML = invoicesData.length ? `<div class="grid grid-cols-1 lg:grid-cols-2 gap-4">${invoicesData.map(i => {
    const released = i.status.startsWith('Released'), m = i.match;
    return `<div class="bg-white rounded-2xl border border-slate-200 p-4 space-y-2 text-xs"><div class="flex justify-between items-center"><span class="mono font-bold text-sky-800">${i.ap_number}</span>${pill(i.status, INV_CLS[i.status])}</div>
      <p class="font-bold text-slate-900">${i.vendor}</p><p class="text-slate-600">Invoice <b>${i.vendor_invoice_no}</b> &bull; PO <span class="mono">${i.po_number}</span> &bull; ${i.invoice_date} &bull; <b class="mono">${money(i.invoice_total)}</b></p>
      ${m.issues.length ? `<ul class="bg-rose-50 border border-rose-200 rounded-xl p-2.5 space-y-0.5 text-rose-900">${m.issues.map(x => `<li><b>${x.check}</b> (line ${x.line}, ${x.item_code}): ${x.message}</li>`).join('')}</ul>` : '<p class="bg-emerald-50 border border-emerald-200 rounded-xl p-2.5 text-emerald-900">PO rate, accepted quantity and invoice all agree.</p>'}
      <table class="w-full text-[11px]"><thead class="text-slate-500"><tr><th class="text-left">Item</th><th class="text-right">PO rate</th><th class="text-right">Inv. rate</th><th class="text-right">Accepted</th><th class="text-right">Billed</th></tr></thead><tbody>${m.lines.map(l => `<tr class="border-t border-slate-100"><td class="mono">${l.item_code}</td><td class="text-right mono">${l.po_rate}</td><td class="text-right mono ${l.price_ok ? '' : 'text-rose-700 font-bold'}">${l.invoice_rate}</td><td class="text-right mono">${l.accepted_qty}</td><td class="text-right mono ${l.qty_ok ? '' : 'text-rose-700 font-bold'}">${l.already_invoiced_qty + l.invoice_qty}</td></tr>`).join('')}</tbody></table>
      ${released ? `<p class="text-slate-500">Released by ${i.released_by} &bull; ${i.released_at}${i.override_reason ? `<br>Override reason: ${i.override_reason}` : ''}</p>` : `<div class="flex flex-wrap gap-2 pt-1">
        ${can('finance', 'admin', 'purchasing') ? `<button onclick="invoiceAction('${i.ap_number}','rematch')" class="${BTN} border-slate-300">Re-match</button>` : ''}
        ${can('finance', 'admin') && i.status.startsWith('Matched') ? `<button onclick="invoiceAction('${i.ap_number}','release')" class="${BTN} bg-emerald-700 text-white border-emerald-700">Release for payment</button>` : ''}
        ${can('admin') && i.status.startsWith('Held') ? `<button onclick="invoiceAction('${i.ap_number}','override')" class="${BTN} border-amber-400 text-amber-800">Override hold</button>` : ''}</div>`}</div>`; }).join('')}</div>` : empty('No supplier invoices entered yet.');
}

// ---- PO card buttons (used by renderPipeline)
function poActionButtons(po) {
  if (!RECEIVABLE_STATES.includes(po.status)) return '';
  const buying = can('purchasing', 'admin'), receiving = can('warehouse', 'purchasing', 'admin'), untouched = !po.lines.some(l => l.arrived_qty > 0);
  const out = [];
  if (receiving && po.lines.length) out.push(`<button onclick="openReceiveModal('${po.poNumber}')" class="${BTN} w-full bg-emerald-700 text-white border-emerald-700">Receive Cargo (Form 04 GRN)</button>`);
  if (buying && (!po.lines.length || untouched)) out.push(`<button onclick="openPOLinesModal('${po.poNumber}')" class="${BTN} w-full border-amber-400 text-amber-800">${po.lines.length ? 'Edit line items' : 'Add line items to enable receiving'}</button>`);
  if (!po.lines.length && !buying && receiving) out.push('<p class="text-[11px] text-amber-700">No line items yet - purchasing must add them before goods can be received.</p>');
  return out.length ? `<div class="space-y-1.5">${out.join('')}</div>` : '';
}

// ---- PO line-item editor
let polOptions = [];
function openPOLinesModal(poNumber) {
  const po = pipelineData.find(p => p.poNumber === poNumber);
  if (!po) return;
  const have = po.lines.map(l => l.item_code), mine = materialsData.filter(m => m.supplier === po.vendor || have.includes(m.code));
  polOptions = mine.length ? mine : materialsData;
  document.getElementById('pol-po').value = poNumber;
  document.getElementById('pol-head').innerHTML = `${poNumber} &bull; ${po.vendor}`;
  document.getElementById('pol-rows').innerHTML = '';
  if (po.lines.length) po.lines.forEach(l => addPOLineRow(l.item_code, l.ordered_qty, l.unit_rate)); else addPOLineRow();
  openModal('po-lines-modal');
}
function addPOLineRow(code = '', qty = '', rate = '') {
  const opts = polOptions.map(m => `<option value="${m.code}" data-cost="${m.stdCost}" ${m.code === code ? 'selected' : ''}>${m.code} - ${m.name}</option>`).join('');
  document.getElementById('pol-rows').insertAdjacentHTML('beforeend', `<tr class="border-t border-slate-100">
    <td class="p-2"><select class="pl-code ${INPUT}" onchange="polPickItem(this)"><option value="">Select item...</option>${opts}</select></td>
    <td class="p-2"><input type="number" min="0" step="any" class="pl-qty ${INPUT}" value="${qty}" oninput="recalcPOLines()"></td>
    <td class="p-2"><input type="number" min="0" step="any" class="pl-rate ${INPUT}" value="${rate}" oninput="recalcPOLines()"></td>
    <td class="p-2 text-right mono pl-total">$0.00</td><td class="p-2"><button type="button" onclick="this.closest('tr').remove(); recalcPOLines()" class="text-rose-600" aria-label="Remove line">✕</button></td></tr>`);
  recalcPOLines();
}
function polPickItem(sel) {
  const row = sel.closest('tr'), cost = sel.selectedOptions[0] && sel.selectedOptions[0].dataset.cost;
  if (cost !== undefined && !row.querySelector('.pl-rate').value) row.querySelector('.pl-rate').value = cost;
  recalcPOLines();
}
function recalcPOLines() {
  let total = 0;
  document.querySelectorAll('#pol-rows tr').forEach(r => {
    const t = (Number(r.querySelector('.pl-qty').value) || 0) * (Number(r.querySelector('.pl-rate').value) || 0);
    r.querySelector('.pl-total').textContent = money(t); total += t;
  });
  document.getElementById('pol-total').textContent = money(total);
}
async function submitPOLines(e) {
  e.preventDefault();
  const lines = [...document.querySelectorAll('#pol-rows tr')].map(r => ({ item_code: r.querySelector('.pl-code').value, quantity: Number(r.querySelector('.pl-qty').value),
    rate: r.querySelector('.pl-rate').value })).filter(l => l.item_code || l.quantity)
    .map(l => ({ item_code: l.item_code, quantity: l.quantity, ...(l.rate !== '' ? { unit_rate: Number(l.rate) } : {}) }));
  if (!lines.length || lines.some(l => !l.item_code || !(l.quantity > 0))) { showToast('Incomplete lines', 'Pick an item and a quantity greater than zero on every line.', 'error'); return; }
  if (new Set(lines.map(l => l.item_code)).size !== lines.length) { showToast('Duplicate item', 'Each item may appear only once on a PO - combine the quantities.', 'error'); return; }
  const po = document.getElementById('pol-po').value;
  await mutate(() => api('POST', `/orders/${encodeURIComponent(po)}/lines`, { lines }), () => closeModal('po-lines-modal'), 'PO line items saved', `${po} now has ${lines.length} line item(s).`);
}

// ---- Form 04: receiving
function openReceiveModal(poNumber) {
  const po = pipelineData.find(p => p.poNumber === poNumber);
  if (!po) return;
  document.getElementById('rcv-po').value = poNumber;
  document.getElementById('rcv-head').textContent = `${poNumber} • ${unesc(po.vendor)}`;
  ['rcv-do', 'rcv-plate', 'rcv-notes'].forEach(id => { document.getElementById(id).value = ''; });
  document.getElementById('receive-lines').innerHTML = po.lines.filter(l => l.open_balance > 0).map(l => `<tr class="border-t border-slate-100" data-code="${l.item_code}">
    <td class="p-2"><b>${l.item_name}</b><div class="mono text-[10px] text-slate-500">${l.item_code} &bull; ${l.uom}</div></td><td class="p-2 text-right mono">${l.ordered_qty}</td><td class="p-2 text-right mono">${l.accepted_qty}</td>
    <td class="p-2"><input type="number" min="0" step="any" class="rc-arr ${INPUT}" oninput="recalcReceiveRows()" placeholder="0"></td>
    <td class="p-2"><input type="number" min="0" step="any" class="rc-rej ${INPUT}" oninput="recalcReceiveRows()" placeholder="0"></td>
    <td class="p-2 text-right mono font-bold text-emerald-700 rc-acc">0</td><td class="p-2"><input class="rc-why ${INPUT}" placeholder="required if rejected"></td></tr>`).join('')
    || '<tr><td class="p-3 text-slate-500" colspan="7">Nothing left to receive on this PO.</td></tr>';
  openModal('receive-modal');
}
function recalcReceiveRows() {
  document.querySelectorAll('#receive-lines tr[data-code]').forEach(r => {
    const arr = Number(r.querySelector('.rc-arr').value) || 0, rej = Number(r.querySelector('.rc-rej').value) || 0;
    r.querySelector('.rc-acc').textContent = Math.max(arr - rej, 0);
    r.querySelector('.rc-acc').classList.toggle('text-rose-700', rej > arr);
  });
}
async function submitReceive(e) {
  e.preventDefault();
  const num = (r, c) => Number(r.querySelector(c).value) || 0;
  const lines = [...document.querySelectorAll('#receive-lines tr[data-code]')].map(r => ({ item_code: r.dataset.code, arrived_qty: num(r, '.rc-arr'), rejected_qty: num(r, '.rc-rej'),
    accepted_qty: Math.max(num(r, '.rc-arr') - num(r, '.rc-rej'), 0), rejection_reason: r.querySelector('.rc-why').value.trim() })).filter(l => l.arrived_qty > 0);
  if (!lines.length) { showToast('Nothing received', 'Enter the arrived quantity for at least one item.', 'error'); return; }
  const v = id => document.getElementById(id).value.trim();
  const po = v('rcv-po');
  const r = await mutate(() => api('POST', `/orders/${encodeURIComponent(po)}/receive`, { delivery_note: v('rcv-do'), vehicle_plate: v('rcv-plate'), dock_bay: document.getElementById('rcv-bay').value, dock_notes: v('rcv-notes'), lines }),
    () => closeModal('receive-modal'));
  if (r) { showToast('GRN generated', `${r.grn.grn_number} logged${r.ncrs.length ? ` - ${r.ncrs.length} item(s) sent to quarantine` : ''}.`); logiTab = 'grns'; renderLogistics(); viewGRNDocket(r.grn.grn_number); }
}

function viewGRNDocket(number) {
  const g = grnsData.find(x => x.grn_number === number);
  if (!g) return;
  const rows = g.lines.map(l => `<tr class="border-t border-slate-200"><td class="p-2"><b>${l.item_name}</b><div class="mono text-[10px] text-slate-500">${l.item_code}</div></td><td class="p-2 text-right mono">${l.ordered_qty}</td><td class="p-2 text-right mono">${l.arrived_qty}</td>
    <td class="p-2 text-right mono font-bold text-emerald-700">${l.accepted_qty}</td><td class="p-2 text-right mono font-bold ${l.rejected_qty ? 'text-rose-700' : 'text-slate-400'}">${l.rejected_qty}</td><td class="p-2">${l.rejection_reason || '-'} <span class="text-slate-400">${l.uom}</span></td></tr>`).join('');
  const meta = (k, v) => `<div><span class="block text-[10px] uppercase text-slate-400">${k}</span><b>${v}</b></div>`;
  document.getElementById('grn-voucher-body').innerHTML = `
    <div class="flex justify-between items-start border-b-2 border-slate-900 pb-3"><div><h2 class="text-lg font-black tracking-tight">GOODS RECEIVING NOTE</h2><p class="text-[11px] text-slate-500">Form 04 &bull; Warehouse Gate &bull; SOP rule 04</p></div>
      <div class="text-right"><p class="mono text-base font-black">${g.grn_number}</p>${pill(g.status, GRN_CLS[g.status])}</div></div>
    <div class="grid grid-cols-2 sm:grid-cols-3 gap-3">${meta('Vendor', g.vendor)}${meta('Purchase order', g.po_number)}${meta('Delivery note', g.delivery_note)}${meta('Vehicle', g.vehicle_plate)}${meta('Dock bay', g.dock_bay)}${meta('Received', g.received_at)}</div>
    <table class="w-full text-left border border-slate-200"><thead class="bg-slate-100 text-[11px]"><tr><th class="p-2">Item</th><th class="p-2 text-right">Ordered</th><th class="p-2 text-right">Arrived</th><th class="p-2 text-right">Accepted</th><th class="p-2 text-right">Rejected</th><th class="p-2">Defect / notes</th></tr></thead><tbody>${rows}</tbody></table>
    <p><b>Dock notes:</b> ${g.dock_notes || '-'}</p>
    ${g.ncrs.length ? `<div class="border border-rose-200 bg-rose-50 rounded-xl p-3 space-y-1"><b>Non-conformance reports</b>${g.ncrs.map(n => `<p><span class="mono font-bold">${n.ncr_number}</span> &bull; ${n.quantity} ${n.uom} ${n.item_code} &bull; ${n.status.startsWith('Open') ? 'IN QUARANTINE - awaiting QC decision' : `${n.disposition} by ${n.resolved_by}`}</p>`).join('')}</div>` : ''}
    <div class="grid grid-cols-2 gap-4 pt-3"><div class="border border-slate-300 rounded-xl p-3 h-28"><span class="text-[10px] uppercase text-slate-400">Received &amp; inspected by</span><p class="font-bold mt-1">${g.received_by}</p><p class="text-[11px] text-slate-500">${g.received_at}<br>Electronically logged</p></div>
      <div class="border border-slate-300 rounded-xl p-3 h-28"><span class="text-[10px] uppercase text-slate-400">QC disposition</span><p class="font-bold mt-1">${g.ncrs.length ? g.status : 'No defects raised'}</p></div></div>
    <p class="text-[10px] text-slate-400 text-center">Zero ERP entry without a verified Form 04 GRN. Accepted value ${money(g.total_accepted_value)}.</p>`;
  openModal('grn-docket-modal');
}

// ---- QC decisions
function openNCRModal(number) {
  const n = ncrsData.find(x => x.ncr_number === number);
  if (!n) return;
  document.getElementById('ncr-id').value = number;
  document.getElementById('ncr-head').innerHTML = `${n.ncr_number}: ${n.quantity} ${n.uom} of ${n.item_name} - ${n.reason}`;
  document.getElementById('ncr-notes').value = '';
  openModal('ncr-modal');
}
async function submitNCR(e) {
  e.preventDefault();
  const id = document.getElementById('ncr-id').value;
  await mutate(() => api('POST', `/ncrs/${encodeURIComponent(id)}/resolve`, { disposition: document.getElementById('ncr-disp').value, notes: document.getElementById('ncr-notes').value.trim() }),
    () => closeModal('ncr-modal'), 'QC decision recorded', `${id} closed.`);
}

// ---- supplier invoices and 3-way match
function openInvoiceModal() {
  const pos = pipelineData.filter(p => p.lines.some(l => l.accepted_qty > 0));
  if (!pos.length) { showToast('Nothing to invoice', 'Goods must be received on a PO before its invoice can be matched.', 'error'); return; }
  document.getElementById('inv-po').innerHTML = pos.map(p => `<option value="${p.poNumber}">${p.poNumber} - ${p.vendor}</option>`).join('');
  document.getElementById('inv-no').value = '';
  document.getElementById('inv-date').value = new Date().toISOString().slice(0, 10);
  fillInvoiceLines();
  openModal('invoice-modal');
}
function fillInvoiceLines() {
  const po = pipelineData.find(p => p.poNumber === document.getElementById('inv-po').value);
  document.getElementById('inv-lines').innerHTML = po ? po.lines.map(l => `<tr class="border-t border-slate-100" data-code="${l.item_code}"><td class="p-2"><b>${l.item_name}</b><div class="mono text-[10px] text-slate-500">${l.item_code}</div></td>
    <td class="p-2"><input type="number" min="0" step="any" class="iv-q ${INPUT}" placeholder="accepted ${l.accepted_qty}"></td><td class="p-2"><input type="number" min="0" step="any" class="iv-r ${INPUT}" placeholder="PO rate ${l.unit_rate}"></td></tr>`).join('') : '';
}
async function submitInvoice(e) {
  e.preventDefault();
  const lines = [...document.querySelectorAll('#inv-lines tr[data-code]')].filter(r => Number(r.querySelector('.iv-q').value) > 0)
    .map(r => ({ item_code: r.dataset.code, quantity: Number(r.querySelector('.iv-q').value), unit_rate: Number(r.querySelector('.iv-r').value) || 0 }));
  if (!lines.length) { showToast('No lines', 'Enter the quantity billed for at least one item.', 'error'); return; }
  const r = await mutate(() => api('POST', '/invoices', { po_number: document.getElementById('inv-po').value, vendor_invoice_no: document.getElementById('inv-no').value.trim(),
    invoice_date: document.getElementById('inv-date').value, lines }), () => closeModal('invoice-modal'));
  if (r) { logiTab = 'inv'; renderLogistics(); showToast(r.status.startsWith('Matched') ? 'Invoice matched' : 'Invoice on hold', `${r.ap_number}: ${r.status}.`, r.status.startsWith('Matched') ? undefined : 'error'); }
}
async function invoiceAction(ap, action) {
  let body = {};
  if (action === 'override') { const reason = prompt('Reason for overriding the 3-way match hold (required, kept in the audit log):'); if (!reason) return; body = { reason }; }
  await mutate(() => api('POST', `/invoices/${encodeURIComponent(ap)}/${action}`, body), null,
    { rematch: 'Re-matched', release: 'Released for payment', override: 'Override recorded' }[action], `${ap} updated.`);
}
