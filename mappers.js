// Server records -> the shapes the views expect (text is HTML-escaped here)
'use strict';

const fmtWhen = d => !d ? '' : (String(d).includes('T') ? new Date(d).toLocaleDateString() + ' ' + new Date(d).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : d);
const money = n => '$' + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const CATS = { aluminum: ['Aluminum Profile', 'from-slate-700 to-slate-900'], glass: ['Architectural Glass', 'from-teal-700 to-cyan-900'],
               hardware: ['Hardware Accessories', 'from-amber-700 to-stone-900'], sealant: ['Sealants & Gaskets', 'from-emerald-800 to-slate-900'] };
const mapMaterial = m => ({ code: m.code, category: m.category, categoryLabel: esc((CATS[m.category] || [m.category])[0]), name: esc(m.name), specs: esc(m.specs),
  uom: esc(m.uom), currentStock: m.current_stock, safetyStock: m.safety_stock, reorderPoint: m.reorder_point, stdCost: m.std_cost, supplier: esc(m.supplier),
  imageBg: (CATS[m.category] || [0, 'from-sky-700 to-slate-900'])[1], icon: 'box', status: m.status,
  details: { tolerance: esc(m.tolerance), packaging: esc(m.packaging), usageRate: esc(m.usage_rate), leadTime: esc(m.lead_time), productionLink: esc(m.bom_link) } });
const mapSupplier = s => ({ id: s.id, name: esc(s.name), category: esc(s.category), tier: esc(s.tier),
  tierColor: s.score >= 85 ? 'bg-emerald-100 text-emerald-800 border-emerald-300' : 'bg-amber-100 text-amber-800 border-amber-300', score: s.score,
  paymentTerms: esc(s.payment_terms), leadTime: esc(s.lead_time), contact: esc(s.contact), otif: esc(s.otif), qcRate: esc(s.qc_rate) });
const mapOrder = o => ({ poNumber: o.po_number, vendor: esc(o.vendor), items: esc(o.items), amount: money(o.amount_usd), rawAmount: o.amount_usd, dueDate: o.due_date,
  status: o.status, alert: esc(o.alert),
  alertBadge: (o.days_overdue > 0 || /expedite/i.test(o.alert)) ? 'bg-rose-100 text-rose-800 border-rose-300 font-bold'
              : (o.alert && o.alert !== 'On Track' ? 'bg-sky-100 text-sky-800 border-sky-300' : 'bg-emerald-100 text-emerald-800 border-emerald-300'),
  progressPct: o.progress_pct, dockAction: esc(o.dock_action),
      lines: (o.lines || []).map(l => ({ ...l, item_name: esc(l.item_name) })) });
const PR_BADGE = s => s.startsWith('Pending Step 1') ? 'bg-amber-50 text-amber-800 border-amber-300 pulse-amber'
  : s.startsWith('Pending Step 2') ? 'bg-purple-50 text-purple-800 border-purple-300 pulse-purple'
  : s.startsWith('Rejected') ? 'bg-rose-50 text-rose-800 border-rose-300 font-bold pulse-rose'
  : s === 'Approved' ? 'bg-emerald-50 text-emerald-800 border-emerald-300 font-bold'
  : s === 'Cancelled' ? 'bg-slate-100 text-slate-600 border-slate-300' : 'bg-sky-50 text-sky-800 border-sky-300';
const mapStep = t => ({ approved: !!t.approved, rejected: !!t.rejected, by: esc(t.by), role: esc(t.role), date: fmtWhen(t.date), notes: esc(t.notes), decision: t.decision || '' });
const mapPR = p => Object.assign(sanitizePR({ prNumber: p.pr_number, department: esc(p.department), requester: esc(p.requester), requiredDate: p.required_date,
  priority: p.priority, priorityColor: getPriorityBadgeClass(p.priority), status: p.status, statusBadge: PR_BADGE(p.status), bomProject: esc(p.bom_project),
  items: p.items.map(i => ({ itemCode: i.item_code, itemName: esc(i.item_name), itemSpecs: esc(i.item_specs), quantity: i.quantity, uom: esc(i.uom), unitRate: i.unit_rate, extendedTotal: i.extended_total })),
  estimatedTotal: p.estimated_total, step1: mapStep(p.step1), step2: mapStep(p.step2), poNumbers: p.po_numbers,
  revisions: p.revisions.map(r => ({ revisionDate: fmtWhen(r.revision_date), revisedBy: esc(r.revised_by), notes: esc(r.notes), previousState: r.previous_state })) }), { createdAt: p.created_at, poNumbers: p.po_numbers });
const mapUser = u => ({ username: u.username, fullName: esc(u.full_name), name: esc(u.full_name), role: u.role, roleLabel: esc(u.role_label || u.role), status: u.status || 'allowed' });
const prLine = l => ({ item_code: l.itemCode, quantity: Number(l.quantity), ...(Number.isFinite(Number(l.unitRate)) ? { unit_rate: Number(l.unitRate) } : {}) });
