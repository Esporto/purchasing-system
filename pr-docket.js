// Form 01 docket (printable requisition voucher)
'use strict';

// FORM 01 PRINTABLE VOUCHER (MULTI-LINE SCHEDULE)
function viewPRVoucher(prNumber) {
  const rawPr = prsData.find(p => p.prNumber === prNumber);
  if (!rawPr) return;
  const pr = sanitizePR(rawPr);

  const body = document.getElementById('pr-voucher-body');
  if (!body) return;

  const isApproved = pr.status === 'Approved' || pr.status === 'Converted to PO';
  const isRejected = pr.status.toLowerCase().includes('reject');

  const rowsHtml = pr.items.map((it, idx) => `
    <tr class="${idx % 2 === 0 ? 'bg-white' : 'bg-slate-50/60'} border-b border-slate-200">
      <td class="p-2.5 text-center mono text-slate-500 font-semibold">${String(idx + 1).padStart(2, '0')}</td>
      <td class="p-2.5 mono font-bold text-sky-800">${it.itemCode}</td>
      <td class="p-2.5">
        <strong class="text-slate-900 block font-semibold">${it.itemName}</strong>
        <span class="text-[10px] text-slate-600 leading-tight block mt-0.5">${it.itemSpecs}</span>
      </td>
      <td class="p-2.5 text-right mono font-bold text-slate-800">${it.quantity.toLocaleString()} <span class="text-[10px] font-normal text-slate-500">${it.uom}</span></td>
      <td class="p-2.5 text-right mono text-slate-700">$${Number(it.unitRate).toFixed(2)}</td>
      <td class="p-2.5 text-right mono font-bold text-slate-900">$${Number(it.extendedTotal).toFixed(2)}</td>
    </tr>
  `).join('');

  // Controlled-document facts come from the server record, not from today's date
  const asDate = c => { const t = String(c || '').replace(' ', 'T'); return t ? new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(t) ? t : t + 'Z') : null; };
  const issuedDay = asDate(rawPr.createdAt) ? asDate(rawPr.createdAt).toLocaleDateString('en-GB') : '--';
  const revs = rawPr.revisions || [];
  const revNo = String(revs.length).padStart(2, '0');
  const revisionHtml = revs.length ? `
      <div class="border border-sky-200 bg-sky-50 rounded-xl p-2.5 text-[11px] text-sky-900">
        <strong>Revision ${revNo} &bull; ${revs[0].revisionDate} &bull; ${revs[0].revisedBy}:</strong> ${revs[0].notes}
        <span class="block text-[10px] text-sky-700 mt-0.5">Previous state: ${revs[0].previousState}. Both approval steps were reset and signed again for this revision.</span>
      </div>` : '';
  const poHtml = (rawPr.poNumbers && rawPr.poNumbers.length) ? `
      <div class="border border-emerald-200 bg-emerald-50 rounded-xl p-2.5 text-[11px] text-emerald-900">
        <strong>Converted to purchase order(s):</strong> <span class="mono font-bold">${rawPr.poNumbers.join(', ')}</span> (one PO per vendor)
      </div>` : '';
  // Status watermark & badge
  let statusColor = 'bg-amber-100 text-amber-900 border-amber-300';
  if (isApproved) statusColor = 'bg-emerald-100 text-emerald-900 border-emerald-300';
  if (isRejected) statusColor = 'bg-rose-100 text-rose-900 border-rose-300';

  body.innerHTML = `
    <div class="space-y-5">
      <!-- Corporate Letterhead -->
      <div class="border-b-2 border-slate-900 pb-3 flex flex-col sm:flex-row justify-between sm:items-start gap-3">
        <div class="flex items-start gap-3">
          <div class="w-12 h-12 rounded-xl bg-slate-900 text-white flex items-center justify-center font-black text-lg shrink-0 shadow-sm">
            AG
          </div>
          <div>
            <h1 class="text-lg sm:text-xl font-extrabold tracking-tight text-slate-950 uppercase">ALU-GLASS INDUSTRIAL GROUP</h1>
            <p class="text-[11px] text-slate-600 font-medium">Architectural Fenestration Systems &bull; Facade Engineering &bull; Material Supply</p>
            <p class="text-[10px] text-slate-400 font-mono mt-0.5">Document Ref: SOP-PROC-F01 &bull; Rev ${revNo} &bull; ISO 9001:2015 Compliant</p>
          </div>
        </div>
        <div class="sm:text-right border-t sm:border-t-0 pt-2 sm:pt-0 border-slate-200">
          <span class="mono text-base font-extrabold text-purple-900 block">${pr.prNumber}</span>
          <span class="text-[11px] text-slate-500 block">Issued: <strong>${issuedDay}</strong></span>
          <span class="inline-block mt-1 px-2.5 py-0.5 rounded text-[10px] font-bold uppercase border ${statusColor}">
            ${pr.status}
          </span>
        </div>
      </div>

      <!-- Document Header Metadata Grid -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-slate-50 border border-slate-200 rounded-xl p-3 text-xs">
        <div>
          <span class="text-[9px] uppercase tracking-wider font-bold text-slate-400 block">Originating Bay / Dept</span>
          <strong class="text-slate-800 text-[11px] block mt-0.5">${pr.department}</strong>
        </div>
        <div>
          <span class="text-[9px] uppercase tracking-wider font-bold text-slate-400 block">Requester Signatory</span>
          <strong class="text-slate-800 text-[11px] block mt-0.5">${pr.requester}</strong>
        </div>
        <div>
          <span class="text-[9px] uppercase tracking-wider font-bold text-slate-400 block">Project / BOM Assignment</span>
          <strong class="text-slate-800 text-[11px] block mt-0.5">${pr.bomProject}</strong>
        </div>
        <div>
          <span class="text-[9px] uppercase tracking-wider font-bold text-slate-400 block">Delivery Due Date</span>
          <strong class="mono text-slate-900 text-[11px] block mt-0.5">${pr.requiredDate}</strong>
        </div>
      </div>

      ${revisionHtml}${poHtml}
      <!-- Multi-Line Schedule Table -->
      <div class="border border-slate-200 rounded-xl overflow-hidden shadow-xs">
        <table class="w-full text-left text-xs border-collapse">
          <thead class="bg-slate-100 text-slate-700 font-bold border-b border-slate-200 text-[11px]">
            <tr>
              <th class="p-2.5 text-center w-12">Item</th>
              <th class="p-2.5 w-36">Code / SKU</th>
              <th class="p-2.5">Item Description &amp; Technical Specs</th>
              <th class="p-2.5 text-right w-24">Quantity</th>
              <th class="p-2.5 text-right w-24">Unit Rate</th>
              <th class="p-2.5 text-right w-28">Extended Total</th>
            </tr>
          </thead>
          <tbody>
            ${rowsHtml}
          </tbody>
          <tfoot class="bg-slate-50 border-t-2 border-slate-300 font-bold">
            <tr>
              <td colspan="3" class="p-2.5 text-[10px] text-slate-500 italic">
                Total Items Requested: ${pr.items.length} line(s) &bull; Aggregated Units: ${pr.totalUnits.toLocaleString()}
              </td>
              <td colspan="2" class="p-2.5 text-right text-slate-700 uppercase tracking-wider text-[11px]">
                Total Estimated Budget:
              </td>
              <td class="p-2.5 text-right mono text-emerald-800 text-sm font-extrabold">
                $${Number(pr.estimatedTotal).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>

      <!-- 3-Box Sequential Audit Signature Blocks -->
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1">
        
        <!-- Box 1: Originator Demand Verification -->
        <div class="signature-card border border-slate-200 rounded-xl p-3 bg-white flex flex-col justify-between h-36">
          <div>
            <div class="flex items-center justify-between">
              <span class="text-[9px] uppercase font-bold text-slate-400">1. Originating Requester</span>
              <span class="text-[9px] font-bold text-emerald-700 bg-emerald-50 px-1.5 py-0.2 rounded border border-emerald-200">Demand Verified</span>
            </div>
            <strong class="text-slate-900 block text-xs mt-1.5">${pr.requester}</strong>
            <span class="text-[10px] text-slate-500">${pr.department}</span>
          </div>
          <div class="border-t border-dashed border-slate-200 pt-1.5 text-[10px] text-slate-400 flex justify-between items-center mono">
            <span>Sign: <i>Electronically Logged</i></span>
            <span>Date: ${issuedDay}</span>
          </div>
        </div>

        <!-- Box 2: Technical & Production Lead -->
        <div class="signature-card border ${pr.step1?.rejected ? 'border-rose-300 bg-rose-50/40' : (pr.step1?.approved ? 'border-emerald-300 bg-emerald-50/40' : 'border-amber-200 bg-amber-50/30')} rounded-xl p-3 flex flex-col justify-between h-36">
          <div>
            <div class="flex items-center justify-between">
              <span class="text-[9px] uppercase font-bold text-slate-400">2. Technical / Production Lead</span>
              ${pr.step1?.rejected ? '<span class="text-[9px] font-bold text-rose-700 bg-rose-50 px-1.5 py-0.2 rounded border border-rose-200">Rejected</span>' : (pr.step1?.approved ? '<span class="text-[9px] font-bold text-emerald-700 bg-emerald-50 px-1.5 py-0.2 rounded border border-emerald-200">Endorsed</span>' : '<span class="text-[9px] font-bold text-amber-700 bg-amber-50 px-1.5 py-0.2 rounded border border-amber-200">Pending Review</span>')}
            </div>
            ${pr.step1?.rejected ? `
              <strong class="text-rose-700 block text-xs mt-1.5">REJECTED BY: ${pr.step1.by}</strong>
              <span class="text-[10px] text-slate-500">${pr.step1.role}</span>
              <p class="text-[9px] text-rose-700 italic mt-0.5 line-clamp-2">"${pr.step1.notes}"</p>
            ` : (pr.step1?.approved ? `
              <strong class="text-slate-900 block text-xs mt-1.5">${pr.step1.by}</strong>
              <span class="text-[10px] text-slate-500">${pr.step1.role}</span>
              <p class="text-[9px] text-slate-600 italic mt-0.5 line-clamp-2">"${pr.step1.notes || 'Specifications and CAD schedule checked.'}"</p>
            ` : `
              <span class="text-amber-800 text-[11px] font-semibold mt-2.5 block italic">Awaiting technical evaluation</span>
            `)}
          </div>
          <div class="border-t border-dashed border-slate-200 pt-1.5 text-[10px] text-slate-400 flex justify-between items-center mono">
            <span>Sign: <i>${pr.step1?.approved ? '✓ Stamped' : (pr.step1?.rejected ? '✗ Rejected' : '--')}</i></span>
            <span>${pr.step1?.date || 'Pending'}</span>
          </div>
        </div>

        <!-- Box 3: Finance Department Head / Master Admin -->
        <div class="signature-card border ${pr.step2?.rejected ? 'border-rose-300 bg-rose-50/40' : (pr.step2?.approved ? 'border-emerald-300 bg-emerald-50/40' : 'border-purple-200 bg-purple-50/30')} rounded-xl p-3 flex flex-col justify-between h-36">
          <div>
            <div class="flex items-center justify-between">
              <span class="text-[9px] uppercase font-bold text-slate-400">3. Finance Head / Authorization</span>
              ${pr.step2?.rejected ? '<span class="text-[9px] font-bold text-rose-700 bg-rose-50 px-1.5 py-0.2 rounded border border-rose-200">Budget Denied</span>' : (pr.step2?.approved ? '<span class="text-[9px] font-bold text-emerald-700 bg-emerald-50 px-1.5 py-0.2 rounded border border-emerald-200">Authorized</span>' : '<span class="text-[9px] font-bold text-purple-700 bg-purple-50 px-1.5 py-0.2 rounded border border-purple-200">Pending Budget</span>')}
            </div>
            ${pr.step2?.rejected ? `
              <strong class="text-rose-700 block text-xs mt-1.5">REJECTED BY: ${pr.step2.by}</strong>
              <span class="text-[10px] text-slate-500">${pr.step2.role}</span>
              <p class="text-[9px] text-rose-700 italic mt-0.5 line-clamp-2">"${pr.step2.notes}"</p>
            ` : (pr.step2?.approved ? `
              <strong class="text-slate-900 block text-xs mt-1.5">${pr.step2.by}</strong>
              <span class="text-[10px] text-slate-500">${pr.step2.role}</span>
              <p class="text-[9px] text-slate-600 italic mt-0.5 line-clamp-2">"${pr.step2.notes || 'Budget release and cost code approved.'}"</p>
            ` : `
              <span class="text-purple-800 text-[11px] font-semibold mt-2.5 block italic">Awaiting financial release</span>
            `)}
          </div>
          <div class="border-t border-dashed border-slate-200 pt-1.5 text-[10px] text-slate-400 flex justify-between items-center mono">
            <span>Sign: <i>${pr.step2?.approved ? '✓ Stamped' : (pr.step2?.rejected ? '✗ Denied' : '--')}</i></span>
            <span>${pr.step2?.date || 'Pending'}</span>
          </div>
        </div>

      </div>

      <!-- Compliance Footer & Disclaimer -->
      <div class="border-t border-slate-200 pt-2 text-[10px] text-slate-400 flex flex-col sm:flex-row justify-between gap-1">
        <span>&bull; SOP Rule 01: Zero purchasing permitted without fully authorized Form 01 docket.</span>
        <span>&bull; Verified with ALU-GLASS Procurement Control &bull; Page 1 of 1</span>
      </div>
    </div>
  `;

  openModal('pr-docket-modal');
}
