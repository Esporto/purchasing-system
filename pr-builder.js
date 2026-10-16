// Multi-line PR builder (new requisition form)
'use strict';

// MULTI-LINE PR BUILDER ENGINE
function addPRLineRow(preset = null) {
  const defaultMat = materialsData[0] || {};
  const newLine = preset || {
    itemCode: defaultMat.code || 'AL-76-SLD-BLK',
    itemName: defaultMat.name || 'Sliding Frame Outer 76 Series',
    itemSpecs: defaultMat.specs || 'Alloy 6063-T5 | 1.4mm',
    quantity: 100,
    uom: defaultMat.uom || 'KG',
    unitRate: defaultMat.stdCost || 2.65,
    extendedTotal: (100 * (defaultMat.stdCost || 2.65))
  };

  prLinesBuilder.push(newLine);
  renderPRLinesBuilder();
}

function removePRLineRow(index) {
  if (prLinesBuilder.length <= 1) {
    showToast("Minimum Line", "A Purchase Requisition must contain at least one line item.", "error");
    return;
  }
  prLinesBuilder.splice(index, 1);
  renderPRLinesBuilder();
}

function onPRLineSKUSelect(index, code) {
  const mat = materialsData.find(m => m.code === code);
  if (!mat) return;

  prLinesBuilder[index].itemCode = mat.code;
  prLinesBuilder[index].itemName = mat.name;
  prLinesBuilder[index].itemSpecs = mat.specs;
  prLinesBuilder[index].uom = mat.uom;
  prLinesBuilder[index].unitRate = mat.stdCost;
  prLinesBuilder[index].extendedTotal = prLinesBuilder[index].quantity * mat.stdCost;

  renderPRLinesBuilder();
}

function onPRLineFieldChange(index, field, value) {
  if (field === 'quantity') {
    const q = Math.max(1, parseFloat(value) || 0);
    prLinesBuilder[index].quantity = q;
    prLinesBuilder[index].extendedTotal = q * prLinesBuilder[index].unitRate;
  } else if (field === 'unitRate') {
    const r = Math.max(0, parseFloat(value) || 0);
    prLinesBuilder[index].unitRate = r;
    prLinesBuilder[index].extendedTotal = prLinesBuilder[index].quantity * r;
  } else if (field === 'itemSpecs') {
    prLinesBuilder[index].itemSpecs = value;
  } else if (field === 'itemName') {
    prLinesBuilder[index].itemName = value;
  }

  // Update line subtotal display without full rerender
  const lineSubtotalEl = document.getElementById(`pr-line-subtotal-${index}`);
  if (lineSubtotalEl) {
    lineSubtotalEl.innerText = `$${prLinesBuilder[index].extendedTotal.toFixed(2)}`;
  }
  calculatePRGrandTotal();
}

function calculatePRGrandTotal() {
  const grandTotal = prLinesBuilder.reduce((sum, it) => sum + (it.extendedTotal || 0), 0);
  const totalEl = document.getElementById('pr-lines-grand-total');
  if (totalEl) {
    totalEl.innerText = `$${grandTotal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
}

function renderPRLinesBuilder() {
  const container = document.getElementById('pr-lines-builder-container');
  if (!container) return;

  container.innerHTML = prLinesBuilder.map((line, idx) => {
    const skuOptions = materialsData.map(m => 
      `<option value="${m.code}" ${m.code === line.itemCode ? 'selected' : ''}>${m.code} — ${m.name}</option>`
    ).join('');

    return `
      <div class="bg-white border border-purple-200/80 rounded-xl p-3 shadow-xs space-y-2 relative">
        <div class="flex items-center justify-between gap-2">
          <span class="text-[10px] font-bold text-purple-900 bg-purple-100 px-2 py-0.5 rounded-full mono">
            Item Line #${idx + 1}
          </span>
          <div class="flex items-center gap-2">
            <span class="mono font-bold text-emerald-700 text-xs" id="pr-line-subtotal-${idx}">
              $${Number(line.extendedTotal).toFixed(2)}
            </span>
            <button type="button" onclick="removePRLineRow(${idx})" class="text-slate-400 hover:text-rose-600 p-1 transition" title="Remove Line">
              ${ICONS.trash}
            </button>
          </div>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-3 gap-2">
          <div class="sm:col-span-2">
            <label class="block text-[10px] text-slate-500 font-medium">Select SKU *</label>
            <select onchange="onPRLineSKUSelect(${idx}, this.value)" class="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-xs mono">
              ${skuOptions}
            </select>
          </div>
          <div>
            <label class="block text-[10px] text-slate-500 font-medium">Item Description</label>
            <input type="text" value="${line.itemName}" oninput="onPRLineFieldChange(${idx}, 'itemName', this.value)" class="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-xs">
          </div>
        </div>

        <div>
          <label class="block text-[10px] text-slate-500 font-medium">Technical Specification Reference</label>
          <input type="text" value="${line.itemSpecs}" oninput="onPRLineFieldChange(${idx}, 'itemSpecs', this.value)" class="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-xs">
        </div>

        <div class="grid grid-cols-3 gap-2 pt-0.5">
          <div>
            <label class="block text-[10px] text-slate-500 font-medium">Quantity *</label>
            <input type="number" min="1" value="${line.quantity}" oninput="onPRLineFieldChange(${idx}, 'quantity', this.value)" class="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-xs mono">
          </div>
          <div>
            <label class="block text-[10px] text-slate-500 font-medium">UOM</label>
            <input type="text" readonly value="${line.uom}" class="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-xs mono bg-slate-100 text-slate-600 font-bold">
          </div>
          <div>
            <label class="block text-[10px] text-slate-500 font-medium">Unit Rate ($) *</label>
            <input type="number" step="0.01" min="0" value="${line.unitRate}" oninput="onPRLineFieldChange(${idx}, 'unitRate', this.value)" class="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-xs mono">
          </div>
        </div>
      </div>
    `;
  }).join('');

  calculatePRGrandTotal();
  lucide.createIcons();
}
