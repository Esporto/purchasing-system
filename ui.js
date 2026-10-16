// Modals, sidebars and toasts
'use strict';

function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('hidden');
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('hidden');
}

function openSidebar(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('hidden');
}

function closeSidebar(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('hidden');
}

function showToast(title, message, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  const bg = type === 'success' ? 'bg-emerald-900 border-emerald-700 text-emerald-100' : 'bg-rose-900 border-rose-700 text-rose-100';

  toast.className = `p-3 rounded-xl border shadow-xl flex items-start gap-2 text-xs transition transform translate-y-2 opacity-0 pointer-events-auto ${bg}`;
  toast.innerHTML = `
    <div class="flex-1 min-w-0">
      <strong class="block font-semibold text-white truncate">${esc(title)}</strong>
      <span class="text-[11px] opacity-90 break-words">${esc(message)}</span>
    </div>
  `;

  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.remove('translate-y-2', 'opacity-0'));

  setTimeout(() => {
    toast.classList.add('opacity-0', 'translate-y-2');
    setTimeout(() => toast.remove(), 250);
  }, 4000);
}


