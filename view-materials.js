// Materials gallery rendering
'use strict';

function renderMaterials(items = materialsData) {
  const container = document.getElementById('materials-grid');
  if (!container) return;

  if (!items || items.length === 0) {
    container.innerHTML = `
      <div class="col-span-full py-12 text-center bg-white rounded-2xl border border-slate-200">
        <div class="w-10 h-10 text-slate-300 mx-auto mb-2 flex items-center justify-center">${ICONS.box}</div>
        <p class="text-sm font-semibold text-slate-700">No matching materials found</p>
        <p class="text-xs text-slate-400 mt-1">Try adjusting search terms or category filters.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = items.map(m => {
    let badge = '';
    if (m.status === 'reorder' || m.currentStock <= m.safetyStock) {
      badge = '<span class="bg-rose-100 text-rose-800 border border-rose-300 px-2 py-0.5 rounded text-[10px] font-bold flex items-center gap-1 shrink-0"><span class="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse"></span>Reorder</span>';
    } else if (m.status === 'low' || m.currentStock <= m.reorderPoint) {
      badge = '<span class="bg-amber-100 text-amber-800 border border-amber-300 px-2 py-0.5 rounded text-[10px] font-bold flex items-center gap-1 shrink-0"><span class="w-1.5 h-1.5 rounded-full bg-amber-500"></span>Low</span>';
    } else {
      badge = '<span class="bg-emerald-100 text-emerald-800 border border-emerald-300 px-2 py-0.5 rounded text-[10px] font-semibold flex items-center gap-1 shrink-0"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>In Stock</span>';
    }

    const pct = Math.min(100, Math.round((m.currentStock / (m.reorderPoint || 1)) * 100));
    const barColor = pct < 50 ? 'bg-rose-500' : (pct < 100 ? 'bg-amber-500' : 'bg-emerald-500');

    return `
      <div class="bg-white rounded-2xl border border-slate-200 shadow-xs p-4 card-contain flex flex-col justify-between space-y-3 relative">
        <div>
          <div class="flex items-start justify-between gap-2">
            <div class="flex items-center gap-2 min-w-0">
              <div class="w-8 h-8 rounded-lg bg-gradient-to-br ${m.imageBg || 'from-slate-700 to-slate-900'} text-white flex items-center justify-center shrink-0 shadow-xs">
                ${getCardIcon(m.icon)}
              </div>
              <div class="min-w-0">
                <span class="mono text-[10px] font-bold text-sky-700 uppercase truncate block">${m.code}</span>
                <span class="block text-[10px] text-slate-400 capitalize truncate">${m.categoryLabel || m.category}</span>
              </div>
            </div>
            <div class="flex items-center gap-1 shrink-0">
              ${badge}
              <button onclick="promptDelete('material', '${m.code}')" aria-label="Delete SKU" class="text-slate-300 hover:text-rose-600 hover:bg-rose-50 p-1 rounded transition">
                ${ICONS.trash}
              </button>
            </div>
          </div>

          <h3 class="font-bold text-slate-900 text-xs sm:text-sm mt-2 line-clamp-1" title="${m.name}">${m.name}</h3>
          <p class="text-[11px] text-slate-500 mt-1 line-clamp-2" title="${m.specs}">${m.specs}</p>
        </div>

        <div class="space-y-1.5 bg-slate-50 border border-slate-100 rounded-xl p-2.5">
          <div class="flex justify-between items-center text-xs">
            <span class="text-slate-500 text-[11px]">Stock Balance:</span>
            <span class="mono font-bold text-slate-800">${m.currentStock} <span class="font-normal text-slate-400 text-[10px]">${m.uom}</span></span>
          </div>
          <div class="w-full bg-slate-200 rounded-full h-1.5 overflow-hidden">
            <div class="${barColor} h-1.5 rounded-full transition-all duration-300" style="width: ${pct}%"></div>
          </div>
          <div class="flex justify-between items-center text-[10px] text-slate-400 pt-0.5">
            <span>ROP: <strong class="mono text-slate-600">${m.reorderPoint} ${m.uom}</strong></span>
            <span>Safety: <strong class="mono text-slate-600">${m.safetyStock} ${m.uom}</strong></span>
          </div>
        </div>

        <div class="pt-2 border-t border-slate-100 flex items-center justify-between text-xs">
          <div>
            <span class="text-[10px] text-slate-400 uppercase block">Std Cost</span>
            <span class="mono font-bold text-emerald-700 text-xs sm:text-sm">$${Number(m.stdCost).toFixed(2)}</span>
          </div>
          <button onclick="viewMaterialDetail('${m.code}')" class="px-2.5 py-1.5 bg-slate-100 hover:bg-sky-50 hover:text-sky-700 text-slate-700 rounded-lg font-medium text-[11px] transition flex items-center gap-1 active:scale-95">
            ${ICONS.eye}
            <span>Docket</span>
          </button>
        </div>
      </div>
    `;
  }).join('');
}
