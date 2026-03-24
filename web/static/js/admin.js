/**
 * Claw Boutique Admin Dashboard
 * admin.js — all UI logic, API calls, and state management
 */

'use strict';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const API_BASE = window.STORE_API_URL || '';
const REFRESH_INTERVAL_MS = 30_000;

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

function fmt_currency(n) {
  return '$' + Number(n || 0).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function fmt_date(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function fmt_datetime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function time_ago(iso) {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return m + 'm ago';
  const h = Math.floor(m / 60);
  if (h < 24) return h + 'h ago';
  return Math.floor(h / 24) + 'd ago';
}

function el(id) { return document.getElementById(id); }

function set_html(id, html) {
  const e = el(id);
  if (e) e.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------
const STATUS_CLASSES = {
  pending:    'bg-yellow-100 text-yellow-800',
  confirmed:  'bg-blue-100 text-blue-800',
  processing: 'bg-purple-100 text-purple-800',
  shipped:    'bg-indigo-100 text-indigo-800',
  delivered:  'bg-green-100 text-green-800',
  cancelled:  'bg-red-100 text-red-800',
  refunded:   'bg-orange-100 text-orange-800',
  open:       'bg-red-100 text-red-800',
  resolved:   'bg-green-100 text-green-800',
};

function status_badge(status) {
  const cls = STATUS_CLASSES[status] || 'bg-slate-100 text-slate-700';
  return `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${cls} capitalize">${status || '—'}</span>`;
}

// ---------------------------------------------------------------------------
// Toast notifications
// ---------------------------------------------------------------------------
function show_toast(message, type = 'success') {
  const container = el('toast-container');
  const id = 'toast-' + Date.now();
  const colors = {
    success: 'bg-green-600',
    error:   'bg-red-600',
    info:    'bg-blue-600',
    warning: 'bg-amber-500',
  };
  const icons = {
    success: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>',
    error:   '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>',
    info:    '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>',
    warning: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>',
  };
  const color = colors[type] || colors.success;
  const icon  = icons[type]  || icons.success;

  const div = document.createElement('div');
  div.id = id;
  div.className = `pointer-events-auto flex items-center gap-3 ${color} text-white text-sm font-medium px-4 py-3 rounded-xl shadow-lg min-w-[260px] max-w-sm transition-all duration-300 opacity-0 translate-x-4`;
  div.innerHTML = `
    <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">${icon}</svg>
    <span class="flex-1">${message}</span>
    <button onclick="document.getElementById('${id}').remove()" class="flex-shrink-0 opacity-70 hover:opacity-100">
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
    </button>`;
  container.appendChild(div);

  requestAnimationFrame(() => {
    div.classList.remove('opacity-0', 'translate-x-4');
  });

  setTimeout(() => {
    div.classList.add('opacity-0', 'translate-x-4');
    setTimeout(() => div.remove(), 300);
  }, 4000);
}

// ---------------------------------------------------------------------------
// API wrapper
// ---------------------------------------------------------------------------
async function api_get(path) {
  const res = await fetch(API_BASE + path);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

async function api_patch(path, body) {
  const res = await fetch(API_BASE + path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.message || `PATCH ${path} failed: ${res.status}`);
  }
  return res.json();
}

async function api_post(path, body) {
  const res = await fetch(API_BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.message || `POST ${path} failed: ${res.status}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
const NAV_ITEMS = [
  { id: 'dashboard',   label: 'Dashboard',   icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6' },
  { id: 'orders',      label: 'Orders',      icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2' },
  { id: 'escalations', label: 'Escalations', icon: 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z', badge: true },
  { id: 'products',    label: 'Products',    icon: 'M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4' },
  { id: 'memory',      label: 'Memory',      icon: 'M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z' },
  { id: 'insights',    label: 'AI Insights',  icon: 'M13 10V3L4 14h7v7l9-11h-7z' },
];

let _current_section = 'dashboard';

function build_nav(container_id) {
  const container = el(container_id);
  if (!container) return;
  container.innerHTML = NAV_ITEMS.map(item => `
    <a href="#" class="sidebar-link" id="nav-${container_id}-${item.id}" data-section="${item.id}" onclick="AdminApp.navigate('${item.id}'); return false;">
      <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${item.icon}"/>
      </svg>
      <span class="flex-1">${item.label}</span>
      ${item.badge ? `<span id="esc-badge-${container_id}" class="hidden inline-flex items-center justify-center w-5 h-5 text-xs font-bold bg-red-500 text-white rounded-full">0</span>` : ''}
    </a>
  `).join('');
}

function update_nav_active(section) {
  ['desktop-sidebar-nav', 'mobile-sidebar-nav'].forEach(navId => {
    NAV_ITEMS.forEach(item => {
      const link = el(`nav-${navId}-${item.id}`);
      if (!link) return;
      link.classList.toggle('active', item.id === section);
    });
  });
}

function update_escalation_badge(count) {
  ['desktop-sidebar-nav', 'mobile-sidebar-nav'].forEach(navId => {
    const badge = el(`esc-badge-${navId}`);
    if (!badge) return;
    if (count > 0) {
      badge.textContent = count > 99 ? '99+' : count;
      badge.classList.remove('hidden');
    } else {
      badge.classList.add('hidden');
    }
  });
}

const PAGE_META = {
  dashboard:   { title: 'Dashboard',   subtitle: 'Overview of your store' },
  orders:      { title: 'Orders',      subtitle: 'Manage and update customer orders' },
  escalations: { title: 'Escalations', subtitle: 'Resolve flagged customer conversations' },
  products:    { title: 'Products',    subtitle: 'Read-only view of your product catalog' },
  memory:      { title: 'Memory / Learning', subtitle: 'Saved AI interaction memories' },
  insights:    { title: 'AI Insights', subtitle: 'Daily business analysis powered by ClawBot' },
};

function navigate(section) {
  _current_section = section;

  // Hide all sections
  document.querySelectorAll('.section-panel').forEach(s => s.classList.add('hidden'));
  el(`section-${section}`)?.classList.remove('hidden');

  // Update header
  const meta = PAGE_META[section] || {};
  set_html('page-title', meta.title || section);
  set_html('page-subtitle', meta.subtitle || '');

  update_nav_active(section);

  // Close mobile nav
  el('mobile-nav')?.classList.add('hidden');

  // Load section data
  switch (section) {
    case 'dashboard':   load_dashboard(); break;
    case 'orders':      load_orders(); break;
    case 'escalations': load_escalations(); break;
    case 'products':    load_products(); break;
    case 'memory':      load_memory(); break;
    case 'insights':    load_insights(); break;
  }
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
async function load_dashboard() {
  try {
    const [stats, orders, escalations] = await Promise.allSettled([
      api_get('/api/stats'),
      api_get('/api/orders?limit=10'),
      api_get('/api/escalations?resolved=false'),
    ]);

    if (stats.status === 'fulfilled') {
      const s = stats.value;
      set_html('stat-total-orders',  s.total_orders  ?? '—');
      set_html('stat-pending-orders', s.pending_orders ?? '—');
      set_html('stat-revenue',        fmt_currency(s.total_revenue));
      set_html('stat-escalations',    s.active_escalations ?? '—');
      update_escalation_badge(s.active_escalations || 0);
    }

    if (orders.status === 'fulfilled') {
      render_recent_orders(orders.value);
    }

    if (escalations.status === 'fulfilled') {
      render_recent_escalations(escalations.value);
      update_escalation_badge(escalations.value.length || 0);
    }

    update_last_refreshed();
  } catch (e) {
    show_toast('Failed to load dashboard data', 'error');
  }
}

function render_recent_orders(orders) {
  if (!orders || !orders.length) {
    set_html('recent-orders-list', '<div class="px-5 py-8 text-center text-slate-400 text-sm">No orders yet.</div>');
    return;
  }
  const html = orders.slice(0, 10).map(o => `
    <div class="flex items-center justify-between px-5 py-3 hover:bg-slate-50 cursor-pointer transition-colors" onclick="AdminApp.navigate('orders'); AdminApp.open_order_detail(${o.id})">
      <div class="flex items-center gap-3 min-w-0">
        <div class="w-8 h-8 rounded-lg bg-slate-100 flex items-center justify-center flex-shrink-0">
          <svg class="w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z"/></svg>
        </div>
        <div class="min-w-0">
          <div class="text-sm font-medium text-slate-800 truncate">${o.customer?.name || 'Unknown'}</div>
          <div class="text-xs text-slate-400">#${o.id}</div>
        </div>
      </div>
      <div class="flex items-center gap-3 flex-shrink-0">
        ${status_badge(o.status)}
        <span class="text-sm font-semibold text-slate-700">${fmt_currency(o.total)}</span>
      </div>
    </div>
  `).join('');
  set_html('recent-orders-list', html);
}

function render_recent_escalations(escalations) {
  if (!escalations || !escalations.length) {
    set_html('recent-escalations-list', '<div class="px-5 py-8 text-center text-green-600 text-sm font-medium">No open escalations</div>');
    return;
  }
  const html = escalations.slice(0, 5).map(e => `
    <div class="px-5 py-3 hover:bg-slate-50 cursor-pointer transition-colors" onclick="AdminApp.navigate('escalations')">
      <div class="flex items-start justify-between gap-2">
        <div class="min-w-0">
          <div class="text-sm font-medium text-slate-800 truncate">${e.customer_phone || '—'}</div>
          <div class="text-xs text-red-600 font-medium truncate">${e.reason || '—'}</div>
          <div class="text-xs text-slate-400 mt-0.5">${time_ago(e.created_at)}</div>
        </div>
        <span class="inline-flex w-2 h-2 rounded-full bg-red-400 flex-shrink-0 mt-1.5"></span>
      </div>
    </div>
  `).join('');
  set_html('recent-escalations-list', html);
}

function update_last_refreshed() {
  const e = el('last-updated');
  if (e) e.textContent = 'Updated ' + new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

// ---------------------------------------------------------------------------
// Orders
// ---------------------------------------------------------------------------
let _orders_filter = 'all';
let _all_orders = [];

async function load_orders() {
  try {
    const data = await api_get('/api/orders');
    _all_orders = Array.isArray(data) ? data : (data.orders || []);
    render_orders_table();
  } catch (e) {
    set_html('orders-table-body', `<tr><td colspan="6" class="px-4 py-8 text-center text-red-500 text-sm">Failed to load orders: ${e.message}</td></tr>`);
  }
}

function render_orders_table() {
  const filtered = _orders_filter === 'all'
    ? _all_orders
    : _all_orders.filter(o => o.status === _orders_filter);

  // Update tab counts
  const tabs = el('order-filter-tabs');
  if (tabs) {
    tabs.querySelectorAll('[data-status]').forEach(btn => {
      const s = btn.dataset.status;
      const count = s === 'all' ? _all_orders.length : _all_orders.filter(o => o.status === s).length;
      const label = btn.textContent.replace(/\s*\(\d+\)/, '');
      btn.textContent = count > 0 ? `${label} (${count})` : label;
    });
  }

  if (!filtered.length) {
    set_html('orders-table-body', `<tr><td colspan="6" class="px-4 py-8 text-center text-slate-400 text-sm">No orders found${_orders_filter !== 'all' ? ' for this status' : ''}.</td></tr>`);
    return;
  }

  const html = filtered.map(o => `
    <tr class="hover:bg-slate-50 cursor-pointer transition-colors" onclick="AdminApp.open_order_detail(${o.id})">
      <td class="px-4 py-3">
        <span class="text-xs font-mono text-slate-500">#${o.id}</span>
      </td>
      <td class="px-4 py-3">
        <div class="text-sm font-medium text-slate-800">${o.customer?.name || '—'}</div>
        <div class="text-xs text-slate-400">${o.customer?.phone || ''}</div>
      </td>
      <td class="px-4 py-3 hidden md:table-cell text-xs text-slate-500">${fmt_date(o.created_at)}</td>
      <td class="px-4 py-3 text-sm font-semibold text-slate-700">${fmt_currency(o.total)}</td>
      <td class="px-4 py-3">${status_badge(o.status)}</td>
      <td class="px-4 py-3 hidden lg:table-cell">
        <div class="flex items-center gap-1.5">
          ${order_action_buttons(o)}
        </div>
      </td>
    </tr>
  `).join('');
  set_html('orders-table-body', html);
}

function order_action_buttons(o) {
  const btns = [];
  if (o.status === 'pending') {
    btns.push(`<button onclick="event.stopPropagation(); AdminApp.update_order_status(${o.id}, 'confirmed')" class="px-2.5 py-1 text-xs font-medium bg-blue-600 hover:bg-blue-700 text-white rounded-md transition-colors">Confirm</button>`);
  }
  if (o.status === 'confirmed' || o.status === 'processing') {
    btns.push(`<button onclick="event.stopPropagation(); AdminApp.open_ship_modal(${o.id})" class="px-2.5 py-1 text-xs font-medium bg-indigo-600 hover:bg-indigo-700 text-white rounded-md transition-colors">Ship</button>`);
  }
  if (o.status === 'shipped') {
    btns.push(`<button onclick="event.stopPropagation(); AdminApp.update_order_status(${o.id}, 'delivered')" class="px-2.5 py-1 text-xs font-medium bg-green-600 hover:bg-green-700 text-white rounded-md transition-colors">Delivered</button>`);
  }
  if (!['delivered','cancelled','refunded'].includes(o.status)) {
    btns.push(`<button onclick="event.stopPropagation(); AdminApp.cancel_order(${o.id})" class="px-2.5 py-1 text-xs font-medium bg-slate-100 hover:bg-red-100 text-slate-600 hover:text-red-700 rounded-md transition-colors">Cancel</button>`);
  }
  return btns.join('');
}

async function open_order_detail(order_id) {
  const panel = el('order-detail-panel');
  const content = el('order-detail-content');
  panel.classList.remove('hidden');
  content.innerHTML = '<div class="text-center py-6 text-slate-400 text-sm">Loading...</div>';

  try {
    const o = await api_get(`/api/orders/${order_id}`);
    content.innerHTML = render_order_detail_html(o);
  } catch (e) {
    content.innerHTML = `<div class="text-center py-6 text-red-500 text-sm">Failed to load order: ${e.message}</div>`;
  }
}

function render_order_detail_html(o) {
  const items_html = (o.items || []).map(i => `
    <div class="flex items-center justify-between py-2">
      <div class="min-w-0">
        <div class="text-sm font-medium text-slate-700 truncate">${i.product_name || i.name}</div>
        <div class="text-xs text-slate-400">Qty: ${i.qty}</div>
      </div>
      <span class="text-sm font-semibold text-slate-700 flex-shrink-0 ml-2">${fmt_currency(i.unit_price * i.qty)}</span>
    </div>
  `).join('');

  const history_html = (o.status_history || []).map(h => `
    <div class="flex items-center gap-2 py-1">
      <div class="w-1.5 h-1.5 rounded-full bg-amber-400 flex-shrink-0"></div>
      <div class="text-xs text-slate-600">${status_badge(h.status)} <span class="text-slate-400">${fmt_datetime(h.changed_at)}</span></div>
    </div>
  `).join('') || '<div class="text-xs text-slate-400">No history available</div>';

  const tracking_html = o.tracking_url
    ? `<a href="${o.tracking_url}" target="_blank" rel="noopener" class="text-xs text-amber-600 hover:text-amber-700 underline break-all">${o.tracking_url}</a>`
    : '<span class="text-xs text-slate-400">No tracking info</span>';

  return `
    <div>
      <div class="flex items-center justify-between mb-1">
        <span class="text-xs text-slate-500 font-mono">#${o.id}</span>
        ${status_badge(o.status)}
      </div>
      <div class="text-xs text-slate-400">${fmt_datetime(o.created_at)}</div>
    </div>

    <div class="border border-slate-200 rounded-lg p-3">
      <div class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Customer</div>
      <div class="text-sm font-medium text-slate-800">${o.customer?.name || '—'}</div>
      <div class="text-xs text-slate-500">${o.customer?.phone || ''}</div>
      <div class="text-xs text-slate-500">${o.customer?.email || ''}</div>
    </div>

    <div class="border border-slate-200 rounded-lg p-3">
      <div class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Items</div>
      <div class="divide-y divide-slate-100">${items_html}</div>
      <div class="flex items-center justify-between pt-2 border-t border-slate-200 mt-2">
        <span class="text-xs font-semibold text-slate-600">Total</span>
        <span class="text-sm font-bold text-slate-800">${fmt_currency(o.total)}</span>
      </div>
    </div>

    <div class="border border-slate-200 rounded-lg p-3">
      <div class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Tracking</div>
      ${tracking_html}
    </div>

    <div class="border border-slate-200 rounded-lg p-3">
      <div class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Status History</div>
      ${history_html}
    </div>

    <div class="space-y-2">
      <div class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Actions</div>
      <div class="flex flex-wrap gap-2">
        ${order_action_buttons(o)}
      </div>
    </div>
  `;
}

async function update_order_status(order_id, new_status, tracking_url) {
  try {
    const body = { status: new_status };
    if (tracking_url) body.tracking_url = tracking_url;
    await api_patch(`/api/orders/${order_id}/status`, body);
    show_toast(`Order ${new_status} successfully`, 'success');
    load_orders();
    // Refresh detail panel if open
    if (!el('order-detail-panel').classList.contains('hidden')) {
      open_order_detail(order_id);
    }
  } catch (e) {
    show_toast('Failed to update order: ' + e.message, 'error');
  }
}

async function cancel_order(order_id) {
  if (!confirm('Cancel this order?')) return;
  await update_order_status(order_id, 'cancelled');
}

// Ship modal
let _pending_ship_order_id = null;

function open_ship_modal(order_id) {
  _pending_ship_order_id = order_id;
  el('tracking-url-input').value = '';
  el('tracking-url-error').classList.add('hidden');
  el('ship-modal').classList.remove('hidden');
}

function close_ship_modal() {
  el('ship-modal').classList.add('hidden');
  _pending_ship_order_id = null;
}

async function confirm_ship() {
  const url = el('tracking-url-input').value.trim();
  if (!url) {
    el('tracking-url-error').classList.remove('hidden');
    return;
  }
  el('tracking-url-error').classList.add('hidden');
  close_ship_modal();
  await update_order_status(_pending_ship_order_id, 'shipped', url);
}

// ---------------------------------------------------------------------------
// Escalations
// ---------------------------------------------------------------------------
let _all_escalations = [];
let _pending_resolve_id = null;

async function load_escalations() {
  try {
    const data = await api_get('/api/escalations');
    _all_escalations = Array.isArray(data) ? data : (data.escalations || []);
    render_escalations();
    update_escalation_badge(_all_escalations.filter(e => !e.resolved).length);
  } catch (e) {
    set_html('escalations-list', `<div class="bg-white rounded-xl border border-slate-200 p-8 text-center text-red-500 text-sm">Failed to load escalations: ${e.message}</div>`);
  }
}

function render_escalations() {
  const list = el('escalations-list');
  if (!_all_escalations.length) {
    list.innerHTML = '<div class="bg-white rounded-xl border border-slate-200 p-8 text-center text-green-600 text-sm font-medium">No escalations found — all clear!</div>';
    return;
  }

  const html = _all_escalations.map(e => {
    const is_open = !e.resolved;
    const display_status = e.resolved ? 'resolved' : 'open';
    return `
      <div class="bg-white rounded-xl border ${is_open ? 'border-red-200' : 'border-slate-200'} shadow-sm overflow-hidden">
        <div class="flex items-start justify-between px-5 py-4 ${is_open ? 'bg-red-50' : 'bg-slate-50'} border-b ${is_open ? 'border-red-100' : 'border-slate-100'}">
          <div class="flex items-center gap-3">
            <div class="w-9 h-9 rounded-full ${is_open ? 'bg-red-100' : 'bg-slate-200'} flex items-center justify-center flex-shrink-0">
              <svg class="w-4 h-4 ${is_open ? 'text-red-500' : 'text-slate-500'}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
              </svg>
            </div>
            <div>
              <div class="text-sm font-semibold text-slate-800">${e.customer_phone || '—'}</div>
              <div class="text-xs text-slate-500">${fmt_datetime(e.created_at)} &bull; ${time_ago(e.created_at)}</div>
            </div>
          </div>
          <div class="flex items-center gap-2">
            ${status_badge(display_status)}
            ${is_open ? `<button onclick="AdminApp.open_resolve_modal('${e.id}')" class="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors shadow-sm">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
              Resolve
            </button>` : ''}
          </div>
        </div>
        <div class="px-5 py-4 space-y-3">
          <div>
            <span class="text-xs font-semibold text-slate-500 uppercase tracking-wide">Reason</span>
            <p class="text-sm text-red-700 font-medium mt-0.5">${e.reason || '—'}</p>
          </div>
          <div>
            <span class="text-xs font-semibold text-slate-500 uppercase tracking-wide">Summary</span>
            <p class="text-sm text-slate-700 mt-0.5 leading-relaxed">${e.summary || '—'}</p>
          </div>
          ${e.resolution ? `
          <div class="p-3 bg-green-50 rounded-lg border border-green-200">
            <span class="text-xs font-semibold text-green-700 uppercase tracking-wide">Resolution</span>
            <p class="text-sm text-green-800 mt-0.5">${e.resolution}</p>
            ${e.action_taken ? `<span class="inline-block mt-1 text-xs font-medium text-green-600 bg-green-100 px-2 py-0.5 rounded-full">${e.action_taken.replace(/_/g,' ')}</span>` : ''}
          </div>` : ''}
          ${(e.message_thread && e.message_thread.length) ? `
          <div>
            <span class="text-xs font-semibold text-slate-500 uppercase tracking-wide">Message Thread</span>
            <div class="mt-2 space-y-2 max-h-40 overflow-y-auto">
              ${e.message_thread.map(m => `
                <div class="flex ${m.role === 'customer' ? 'justify-start' : 'justify-end'}">
                  <div class="max-w-xs px-3 py-2 rounded-xl text-xs ${m.role === 'customer' ? 'bg-slate-100 text-slate-700' : 'bg-amber-500 text-white'}">
                    ${m.content}
                    <div class="text-xs opacity-60 mt-0.5">${time_ago(m.timestamp)}</div>
                  </div>
                </div>
              `).join('')}
            </div>
          </div>` : ''}
        </div>
      </div>
    `;
  }).join('');
  list.innerHTML = html;
}

function open_resolve_modal(escalation_id) {
  _pending_resolve_id = escalation_id;
  const e = _all_escalations.find(x => String(x.id) === String(escalation_id));
  if (e) {
    el('resolve-modal-context').innerHTML = `
      <div class="text-xs font-semibold text-slate-500 mb-1 uppercase tracking-wide">Escalation Context</div>
      <div class="text-sm font-medium text-slate-800">${e.customer_phone}</div>
      <div class="text-xs text-red-600 font-medium mt-1">${e.reason}</div>
      <div class="text-xs text-slate-600 mt-1 leading-relaxed">${e.summary}</div>
    `;
  }
  el('resolve-notes').value = '';
  el('resolve-action').value = 'resolved_via_chat';
  el('resolve-modal').classList.remove('hidden');
}

function close_resolve_modal() {
  el('resolve-modal').classList.add('hidden');
  _pending_resolve_id = null;
}

async function confirm_resolve() {
  if (!_pending_resolve_id) return;
  const action_taken = el('resolve-action').value;
  const resolution = el('resolve-notes').value.trim();

  try {
    await api_post(`/api/escalations/${_pending_resolve_id}/resolve`, { action_taken, resolution });
    show_toast('Escalation resolved successfully', 'success');
    close_resolve_modal();
    load_escalations();
    // Refresh dashboard badge
    api_get('/api/escalations?resolved=false')
      .then(data => update_escalation_badge(Array.isArray(data) ? data.length : 0))
      .catch(() => {});
  } catch (e) {
    show_toast('Failed to resolve escalation: ' + e.message, 'error');
  }
}

// ---------------------------------------------------------------------------
// Products
// ---------------------------------------------------------------------------
async function load_products() {
  try {
    const data = await api_get('/api/products');
    const products = Array.isArray(data) ? data : (data.products || []);
    el('products-count').textContent = `${products.length} SKU${products.length !== 1 ? 's' : ''}`;

    if (!products.length) {
      set_html('products-table-body', '<tr><td colspan="6" class="px-4 py-8 text-center text-slate-400 text-sm">No products found.</td></tr>');
      return;
    }

    const html = products.map(p => {
      const low = p.stock_qty < 5;
      return `
        <tr class="hover:bg-slate-50 transition-colors ${p.stock_qty === 0 ? 'bg-red-50/40' : low ? 'bg-amber-50/40' : ''}">
          <td class="px-4 py-3">
            <div class="text-sm font-medium text-slate-800">${p.name}</div>
          </td>
          <td class="px-4 py-3 hidden md:table-cell">
            <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700 capitalize">${p.category}</span>
          </td>
          <td class="px-4 py-3 hidden lg:table-cell text-sm text-slate-600">${p.size || '—'}</td>
          <td class="px-4 py-3 hidden lg:table-cell text-sm text-slate-600">${p.color || '—'}</td>
          <td class="px-4 py-3 text-sm font-semibold text-slate-700">${fmt_currency(p.price)}</td>
          <td class="px-4 py-3">
            <div class="flex items-center gap-2">
              <span class="text-sm font-medium ${p.stock_qty === 0 ? 'text-red-600' : low ? 'text-amber-600' : 'text-slate-700'}">${p.stock_qty}</span>
              ${p.stock_qty === 0 ? '<span class="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-semibold bg-red-100 text-red-700">Out</span>' : low ? '<span class="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-semibold bg-amber-100 text-amber-700">Low</span>' : ''}
            </div>
          </td>
        </tr>
      `;
    }).join('');
    set_html('products-table-body', html);
  } catch (e) {
    set_html('products-table-body', `<tr><td colspan="6" class="px-4 py-8 text-center text-red-500 text-sm">Failed to load products: ${e.message}</td></tr>`);
  }
}

// ---------------------------------------------------------------------------
// Memory
// ---------------------------------------------------------------------------
async function load_memory() {
  try {
    const data = await api_get('/api/memory');
    const memories = Array.isArray(data) ? data : (data.memories || []);
    render_memory(memories);
  } catch (e) {
    set_html('memory-list', `<div class="bg-white rounded-xl border border-slate-200 p-8 text-center text-red-500 text-sm">Failed to load memories: ${e.message}</div>`);
  }
}

function render_memory(memories) {
  if (!memories.length) {
    set_html('memory-list', '<div class="bg-white rounded-xl border border-slate-200 p-8 text-center text-slate-400 text-sm">No memories recorded yet.</div>');
    return;
  }

  const html = memories.map(m => {
    const tags = Array.isArray(m.tags)
      ? m.tags
      : (typeof m.tags === 'string' ? m.tags.split(',').map(t => t.trim()).filter(Boolean) : []);
    return `
      <div class="bg-white rounded-xl border border-slate-200 shadow-sm p-4">
        <div class="flex items-start justify-between gap-3">
          <div class="flex items-center gap-3 min-w-0">
            <div class="w-9 h-9 rounded-full bg-amber-100 flex items-center justify-center flex-shrink-0">
              <svg class="w-4 h-4 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
              </svg>
            </div>
            <div class="min-w-0">
              <div class="text-sm font-semibold text-slate-800">${m.customer_phone || '—'}</div>
              <div class="text-xs text-slate-400">${fmt_date(m.created_at)}</div>
            </div>
          </div>
          ${m.interaction_type ? `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800 flex-shrink-0 capitalize">${m.interaction_type}</span>` : ''}
        </div>
        <div class="mt-3 space-y-2">
          ${m.summary ? `<div><span class="text-xs font-semibold text-slate-500 uppercase tracking-wide">Summary</span><p class="text-sm text-slate-700 mt-0.5 leading-relaxed">${m.summary}</p></div>` : ''}
          ${m.resolution ? `<div><span class="text-xs font-semibold text-slate-500 uppercase tracking-wide">Resolution</span><p class="text-sm text-slate-700 mt-0.5">${m.resolution}</p></div>` : ''}
          ${tags.length ? `<div class="flex flex-wrap gap-1.5 mt-2">
            ${tags.map(t => `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-600">${t}</span>`).join('')}
          </div>` : ''}
        </div>
      </div>
    `;
  }).join('');
  set_html('memory-list', html);
}

function open_add_memory_modal() {
  ['mem-phone','mem-type','mem-summary','mem-resolution','mem-tags'].forEach(id => { el(id).value = ''; });
  el('add-memory-modal').classList.remove('hidden');
}

function close_memory_modal() {
  el('add-memory-modal').classList.add('hidden');
}

async function confirm_add_memory() {
  const phone = el('mem-phone').value.trim();
  const type = el('mem-type').value.trim();
  const summary = el('mem-summary').value.trim();
  const resolution = el('mem-resolution').value.trim();
  const tags = el('mem-tags').value.trim().split(',').map(t => t.trim()).filter(Boolean);

  if (!phone || !summary) {
    show_toast('Customer phone and summary are required.', 'warning');
    return;
  }

  try {
    await api_post('/api/memory', { customer_phone: phone, interaction_type: type, summary, resolution, tags });
    show_toast('Memory saved successfully', 'success');
    close_memory_modal();
    load_memory();
  } catch (e) {
    show_toast('Failed to save memory: ' + e.message, 'error');
  }
}

// ---------------------------------------------------------------------------
// AI Insights (demo — uses real stats, generates recommendations)
// ---------------------------------------------------------------------------

async function load_insights() {
  const container = el('insights-content');
  if (!container) return;
  container.innerHTML = '<div class="text-center py-8 text-slate-400 text-sm">Analyzing your store data...</div>';

  try {
    const [stats, stockData] = await Promise.all([
      api_get('/api/stats'),
      api_get('/api/stock/analysis?low_stock_only=true'),
    ]);

    const today = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
    const avgOrderValue = stats.total_orders > 0 ? (stats.total_revenue / stats.total_orders) : 0;
    const lowStockItems = stockData.alerts || [];
    const criticalCount = stockData.critical_count || 0;

    const insights = [];

    // Revenue insight
    insights.push({
      icon: '📊',
      title: 'Revenue Summary',
      body: `Total revenue is ${fmt_currency(stats.total_revenue)} across ${stats.total_orders} orders. Average order value is ${fmt_currency(avgOrderValue)}.`,
      recommendation: avgOrderValue < 50
        ? 'Consider bundling products or adding a "frequently bought together" section to increase average order value above $50.'
        : 'Your average order value is healthy. Consider a loyalty program to drive repeat purchases.',
      priority: 'info',
    });

    // Pending orders insight
    if (stats.pending_orders > 0) {
      insights.push({
        icon: '⏳',
        title: `${stats.pending_orders} Pending Order${stats.pending_orders > 1 ? 's' : ''}`,
        body: `You have ${stats.pending_orders} order${stats.pending_orders > 1 ? 's' : ''} waiting to be confirmed. Quick order confirmation improves customer satisfaction and reduces cancellations.`,
        recommendation: 'Aim to confirm orders within 2 hours of placement. Customers who receive fast confirmation are 40% less likely to cancel.',
        priority: 'warning',
      });
    }

    // Stock insight
    if (lowStockItems.length > 0) {
      const outOfStock = lowStockItems.filter(i => i.urgency === 'out_of_stock');
      const critical = lowStockItems.filter(i => i.urgency === 'critical');
      insights.push({
        icon: '📦',
        title: `Stock Alert: ${lowStockItems.length} Item${lowStockItems.length > 1 ? 's' : ''} Need Attention`,
        body: `${outOfStock.length} item${outOfStock.length !== 1 ? 's are' : ' is'} out of stock and ${critical.length} ${critical.length !== 1 ? 'are' : 'is'} critically low.${outOfStock.length > 0 ? ' Out-of-stock items: ' + outOfStock.map(i => i.name).join(', ') + '.' : ''}`,
        recommendation: 'Restock high-demand items first. Based on sell rate, prioritize: ' + lowStockItems.slice(0, 3).map(i => `${i.name} (reorder ${i.suggested_reorder} units)`).join(', ') + '.',
        priority: 'critical',
      });
    } else {
      insights.push({
        icon: '✅',
        title: 'Stock Levels Healthy',
        body: 'All products have adequate stock levels. No immediate reorders needed.',
        recommendation: 'Review your stock levels weekly. Set up automated reorder points for your top sellers.',
        priority: 'success',
      });
    }

    // Escalation insight
    if (stats.active_escalations > 0) {
      insights.push({
        icon: '🚨',
        title: `${stats.active_escalations} Unresolved Escalation${stats.active_escalations > 1 ? 's' : ''}`,
        body: `Customer complaints that go unresolved for more than 24 hours have a 3x higher churn risk.`,
        recommendation: 'Resolve open escalations promptly. Consider offering a discount or replacement to recover dissatisfied customers.',
        priority: 'critical',
      });
    }

    // Category mix suggestion (always show)
    insights.push({
      icon: '💡',
      title: 'Category Optimization',
      body: `Your catalog has ${stats.total_products} products. Accessories typically have the highest margin and lowest return rate in fashion e-commerce.`,
      recommendation: 'Consider expanding your accessories line. Cross-sell accessories at checkout (e.g., "Complete the look with matching earrings") to boost AOV by 15-25%.',
      priority: 'info',
    });

    // WhatsApp engagement suggestion
    insights.push({
      icon: '💬',
      title: 'WhatsApp Engagement',
      body: `Cart abandonment recovery messages via WhatsApp have a 45-60% open rate compared to 20% for email. Your store uses WhatsApp for post-purchase surveys and cart recovery.`,
      recommendation: 'Send a weekly "new arrivals" broadcast to customers who opted in. Personalized product recommendations based on past purchases can drive 3x higher conversion.',
      priority: 'info',
    });

    const priorityColors = {
      critical: 'border-red-200 bg-red-50',
      warning: 'border-amber-200 bg-amber-50',
      success: 'border-green-200 bg-green-50',
      info: 'border-blue-200 bg-blue-50',
    };

    const priorityTextColors = {
      critical: 'text-red-700',
      warning: 'text-amber-700',
      success: 'text-green-700',
      info: 'text-blue-700',
    };

    const html = `
      <div class="mb-4 flex items-center justify-between">
        <div class="flex items-center gap-2">
          <div class="w-8 h-8 rounded-lg bg-amber-100 flex items-center justify-center">
            <svg class="w-4 h-4 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
          </div>
          <div>
            <div class="text-sm font-semibold text-slate-700">ClawBot Daily Analysis</div>
            <div class="text-xs text-slate-400">${today}</div>
          </div>
        </div>
        <span class="text-xs text-slate-400 bg-slate-100 px-2 py-1 rounded-full">Powered by Claude</span>
      </div>
      <div class="space-y-4">
        ${insights.map(i => `
          <div class="rounded-xl border ${priorityColors[i.priority]} p-4">
            <div class="flex items-start gap-3">
              <span class="text-lg flex-shrink-0">${i.icon}</span>
              <div class="flex-1 min-w-0">
                <h4 class="text-sm font-semibold ${priorityTextColors[i.priority]}">${i.title}</h4>
                <p class="text-sm text-slate-600 mt-1">${i.body}</p>
                <div class="mt-2 flex items-start gap-2 bg-white/60 rounded-lg p-2.5">
                  <svg class="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/></svg>
                  <p class="text-xs text-slate-600"><strong class="text-slate-700">Recommendation:</strong> ${i.recommendation}</p>
                </div>
              </div>
            </div>
          </div>
        `).join('')}
      </div>
    `;
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = `<div class="text-center py-8 text-red-500 text-sm">Failed to generate insights: ${e.message}</div>`;
  }
}

// ---------------------------------------------------------------------------
// Auto-refresh
// ---------------------------------------------------------------------------
let _refresh_timer = null;

function start_auto_refresh() {
  _refresh_timer = setInterval(() => {
    if (_current_section === 'dashboard') {
      load_dashboard();
    }
    // Always refresh escalation badge
    api_get('/api/escalations?resolved=false')
      .then(data => update_escalation_badge(Array.isArray(data) ? data.length : 0))
      .catch(() => {});
  }, REFRESH_INTERVAL_MS);
}

// ---------------------------------------------------------------------------
// Refresh button spinner
// ---------------------------------------------------------------------------
function trigger_refresh() {
  const icon = el('refresh-icon');
  icon.classList.add('animate-spin');
  const p = (_current_section === 'dashboard') ? load_dashboard()
    : (_current_section === 'orders') ? load_orders()
    : (_current_section === 'escalations') ? load_escalations()
    : (_current_section === 'products') ? load_products()
    : (_current_section === 'memory') ? load_memory()
    : load_insights();
  Promise.resolve(p).finally(() => {
    setTimeout(() => icon.classList.remove('animate-spin'), 500);
  });
}

// ---------------------------------------------------------------------------
// Order filter tabs
// ---------------------------------------------------------------------------
function init_order_tabs() {
  const tabs = el('order-filter-tabs');
  if (!tabs) return;
  tabs.addEventListener('click', e => {
    const btn = e.target.closest('[data-status]');
    if (!btn) return;
    _orders_filter = btn.dataset.status;
    tabs.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    render_orders_table();
  });
}

// ---------------------------------------------------------------------------
// Mobile menu
// ---------------------------------------------------------------------------
function init_mobile_menu() {
  el('mobile-menu-btn')?.addEventListener('click', () => {
    el('mobile-nav')?.classList.toggle('hidden');
  });
  el('mobile-nav')?.addEventListener('click', e => {
    if (e.target === el('mobile-nav')) el('mobile-nav').classList.add('hidden');
  });
}

// ---------------------------------------------------------------------------
// Modal wiring
// ---------------------------------------------------------------------------
function init_modals() {
  // Resolve modal
  el('close-resolve-modal')?.addEventListener('click', close_resolve_modal);
  el('cancel-resolve-modal')?.addEventListener('click', close_resolve_modal);
  el('confirm-resolve-btn')?.addEventListener('click', confirm_resolve);
  el('resolve-modal')?.addEventListener('click', e => { if (e.target === el('resolve-modal')) close_resolve_modal(); });

  // Ship modal
  el('close-ship-modal')?.addEventListener('click', close_ship_modal);
  el('cancel-ship-modal')?.addEventListener('click', close_ship_modal);
  el('confirm-ship-btn')?.addEventListener('click', confirm_ship);
  el('ship-modal')?.addEventListener('click', e => { if (e.target === el('ship-modal')) close_ship_modal(); });
  el('tracking-url-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') confirm_ship(); });

  // Memory modal
  el('close-memory-modal')?.addEventListener('click', close_memory_modal);
  el('cancel-memory-modal')?.addEventListener('click', close_memory_modal);
  el('confirm-memory-btn')?.addEventListener('click', confirm_add_memory);
  el('add-memory-modal')?.addEventListener('click', e => { if (e.target === el('add-memory-modal')) close_memory_modal(); });
  el('add-memory-btn')?.addEventListener('click', open_add_memory_modal);

  // Close order detail
  el('close-order-detail')?.addEventListener('click', () => {
    el('order-detail-panel')?.classList.add('hidden');
  });

  // Refresh button
  el('refresh-btn')?.addEventListener('click', trigger_refresh);
}

// ---------------------------------------------------------------------------
// Keyboard shortcut: Escape closes modals
// ---------------------------------------------------------------------------
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    close_resolve_modal();
    close_ship_modal();
    close_memory_modal();
    el('mobile-nav')?.classList.add('hidden');
  }
});

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  build_nav('desktop-sidebar-nav');
  build_nav('mobile-sidebar-nav');
  init_mobile_menu();
  init_modals();
  init_order_tabs();
  navigate('dashboard');
  start_auto_refresh();
});

// ---------------------------------------------------------------------------
// Public API (called from inline onclick handlers in HTML)
// ---------------------------------------------------------------------------
window.AdminApp = {
  navigate,
  open_order_detail,
  update_order_status,
  cancel_order,
  open_ship_modal,
  open_resolve_modal,
};
