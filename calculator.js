// Landed-cost quick calculator
'use strict';

function runCalculator() {
  const qty = parseFloat(document.getElementById('calc-qty')?.value) || 1;
  const price = parseFloat(document.getElementById('calc-price')?.value) || 0;
  const discPct = parseFloat(document.getElementById('calc-discount')?.value) || 0;
  const freight = parseFloat(document.getElementById('calc-freight')?.value) || 0;
  const other = parseFloat(document.getElementById('calc-other')?.value) || 0;

  const netBase = price * (1 - (discPct / 100));
  const overhead = (freight + other) / qty;
  const landed = netBase + overhead;

  document.getElementById('calc-res-base').innerText = `$${price.toFixed(2)} (-${discPct}%)`;
  document.getElementById('calc-res-overhead').innerText = `+$${overhead.toFixed(3)} / unit`;
  document.getElementById('calc-res-landed').innerText = `$${landed.toFixed(3)} / unit`;
}

window.openModal = openModal;
window.closeModal = closeModal;
window.openSidebar = openSidebar;
window.closeSidebar = closeSidebar;
window.switchGallery = switchGallery;
window.switchEntryTab = switchEntryTab;
window.openNewEntryModal = openNewEntryModal;
window.filterCards = filterCards;
window.runCalculator = runCalculator;
