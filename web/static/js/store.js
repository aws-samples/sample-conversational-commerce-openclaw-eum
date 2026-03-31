/**
 * Claw Boutique – Storefront JS
 * All state is managed here; the HTML file contains only structure.
 */

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const WHATSAPP_NUMBER = '15550001234'; // placeholder – replace with real number
const API_BASE = window.STORE_API_URL || '';  // set via config.js or same origin

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let allProducts = [];
let activeCategory = 'all';
let cart = loadCart();
let currentView = 'catalog'; // 'catalog' | 'checkout' | 'confirmation'
let lastOrder = null;
let _abandonmentTimer = null;
const ABANDONMENT_TIMEOUT_MS = 10 * 1000; // 10 seconds (short for demo)
let _sessionId = localStorage.getItem('cb_session_id') || (() => {
  const id = 'sess_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
  localStorage.setItem('cb_session_id', id);
  return id;
})();

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

function loadCart() {
  try {
    return JSON.parse(localStorage.getItem('cb_cart') || '[]');
  } catch {
    return [];
  }
}

function saveCart() {
  localStorage.setItem('cb_cart', JSON.stringify(cart));
}

// ---------------------------------------------------------------------------
// Cart helpers
// ---------------------------------------------------------------------------

function cartCount() {
  return cart.reduce((sum, item) => sum + item.qty, 0);
}

function cartTotal() {
  return cart.reduce((sum, item) => sum + item.price * item.qty, 0);
}

function addToCart(product) {
  const existing = cart.find(i => i.product_id === product.id);
  if (existing) {
    existing.qty += 1;
  } else {
    cart.push({
      product_id: product.id,
      name: product.name,
      color: product.color,
      size: product.size,
      price: product.price,
      qty: 1,
    });
  }
  saveCart();
  renderCartBadge();
  renderCartPanel();
  showCartFlash(product.name);
  saveCartToServer();
  resetAbandonmentTimer();
}

function updateQty(productId, delta) {
  const pid = typeof productId === 'string' ? parseInt(productId, 10) : productId;
  const item = cart.find(i => i.product_id === pid);
  if (!item) return;
  item.qty += delta;
  if (item.qty <= 0) {
    cart = cart.filter(i => i.product_id !== pid);
  }
  saveCart();
  renderCartBadge();
  renderCartPanel();
}

function removeFromCart(productId) {
  const pid = typeof productId === 'string' ? parseInt(productId, 10) : productId;
  cart = cart.filter(i => i.product_id !== pid);
  saveCart();
  renderCartBadge();
  renderCartPanel();
}

// ---------------------------------------------------------------------------
// Fetch products
// ---------------------------------------------------------------------------

async function fetchProducts() {
  const grid = document.getElementById('product-grid');
  grid.innerHTML = `
    <div class="col-span-full flex justify-center items-center py-24">
      <div class="flex flex-col items-center gap-3 text-stone-400">
        <svg class="animate-spin w-8 h-8" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
        </svg>
        <span class="text-sm tracking-wide">Loading collection…</span>
      </div>
    </div>`;

  try {
    const res = await fetch(`${API_BASE}/api/products`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    allProducts = await res.json();
  } catch (err) {
    console.error('Failed to load products:', err);
    // Fall back to mock data so the UI is always usable
    allProducts = getMockProducts();
  }

  renderProducts();
}

// ---------------------------------------------------------------------------
// Mock product data (fallback when API is unavailable)
// ---------------------------------------------------------------------------

function getMockProducts() {
  return [
    { id: 'p1',  name: 'Ribbed Crop Top',         description: 'Soft stretch ribbed fabric',     category: 'tops',        size: 'S',  color: 'Ivory',      price: 38.00,  stock_qty: 5 },
    { id: 'p2',  name: 'Linen Button-Down',        description: 'Relaxed linen blend',            category: 'tops',        size: 'M',  color: 'Sand',       price: 54.00,  stock_qty: 3 },
    { id: 'p3',  name: 'Fitted Bandeau Top',       description: 'Seamless bandeau silhouette',    category: 'tops',        size: 'L',  color: 'Black',      price: 28.00,  stock_qty: 0 },
    { id: 'p4',  name: 'Puff-Sleeve Blouse',       description: 'Floaty chiffon puff sleeves',    category: 'tops',        size: 'XS', color: 'Blush',      price: 62.00,  stock_qty: 2 },
    { id: 'p5',  name: 'Wrap Midi Dress',          description: 'Adjustable wrap silhouette',     category: 'dresses',     size: 'S',  color: 'Terracotta', price: 98.00,  stock_qty: 4 },
    { id: 'p6',  name: 'Slip Dress',               description: 'Satin-finish slip dress',        category: 'dresses',     size: 'M',  color: 'Champagne',  price: 85.00,  stock_qty: 1 },
    { id: 'p7',  name: 'Floral Mini Dress',        description: 'Ditsy floral print cotton',      category: 'dresses',     size: 'XS', color: 'Multi',      price: 72.00,  stock_qty: 6 },
    { id: 'p8',  name: 'Linen Maxi Dress',         description: 'Effortless linen maxi',          category: 'dresses',     size: 'L',  color: 'Ecru',       price: 118.00, stock_qty: 0 },
    { id: 'p9',  name: 'High-Waist Wide Leg',      description: 'Tailored wide-leg trousers',     category: 'bottoms',     size: 'S',  color: 'Camel',      price: 88.00,  stock_qty: 3 },
    { id: 'p10', name: 'Denim Micro Skirt',        description: 'Vintage wash denim',             category: 'bottoms',     size: 'M',  color: 'Mid Wash',   price: 56.00,  stock_qty: 7 },
    { id: 'p11', name: 'Pleated Midi Skirt',       description: 'Flowing pleated satin',          category: 'bottoms',     size: 'L',  color: 'Sage',       price: 68.00,  stock_qty: 2 },
    { id: 'p12', name: 'Linen Shorts',             description: 'Relaxed tailored fit',           category: 'bottoms',     size: 'XS', color: 'Stone',      price: 44.00,  stock_qty: 4 },
    { id: 'p13', name: 'Pearl Drop Earrings',      description: 'Freshwater pearl drops',         category: 'accessories', size: 'OS', color: 'White',      price: 24.00,  stock_qty: 10 },
    { id: 'p14', name: 'Woven Straw Tote',         description: 'Hand-woven summer tote',         category: 'accessories', size: 'OS', color: 'Natural',    price: 65.00,  stock_qty: 5 },
    { id: 'p15', name: 'Tortoise Hair Clip',       description: 'Oversized claw clip',            category: 'accessories', size: 'OS', color: 'Tortoise',   price: 14.00,  stock_qty: 0 },
    { id: 'p16', name: 'Gold Chain Bracelet',      description: 'Dainty link chain',              category: 'accessories', size: 'OS', color: 'Gold',       price: 32.00,  stock_qty: 8 },
  ];
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function getCategories() {
  const cats = ['all', ...new Set(allProducts.map(p => p.category))];
  return cats;
}

function renderCategoryTabs() {
  const tabs = document.getElementById('category-tabs');
  const categories = getCategories();

  tabs.innerHTML = categories.map(cat => {
    const label = cat.charAt(0).toUpperCase() + cat.slice(1);
    const active = cat === activeCategory;
    return `
      <button
        data-cat="${cat}"
        class="category-tab px-5 py-2 rounded-full text-sm font-medium tracking-wide transition-all duration-200
          ${active
            ? 'bg-amber-800 text-white shadow-sm'
            : 'bg-white text-stone-500 hover:bg-stone-100 border border-stone-200'
          }"
      >${label}</button>`;
  }).join('');

  tabs.querySelectorAll('.category-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      activeCategory = btn.dataset.cat;
      renderCategoryTabs();
      renderProducts();
    });
  });
}

function colorDot(color) {
  const map = {
    'Black': '#1c1c1c', 'White': '#f5f5f5', 'Ivory': '#fffff0',
    'Blush': '#f7c6c6', 'Sand': '#c2a97e', 'Camel': '#c19a6b',
    'Terracotta': '#c0725a', 'Champagne': '#f7e7ce', 'Ecru': '#c2b280',
    'Sage': '#8fad91', 'Stone': '#b0a89a', 'Multi': 'linear-gradient(135deg,#f7c6c6,#c0725a,#8fad91)',
    'Gold': '#d4a843', 'Tortoise': '#8b5e3c', 'Natural': '#d4c5a9',
    'Mid Wash': '#6b8cbe', 'Indigo': '#3a3f7e',
  };
  const bg = map[color] || '#d6d3d1';
  return `<span class="inline-block w-3 h-3 rounded-full border border-stone-200 flex-shrink-0" style="background:${bg}" title="${color}"></span>`;
}

function productGradient(product) {
  const gradients = {
    'tops':        { from: '#fef3c7', to: '#fde68a', accent: '#92400e' },
    'dresses':     { from: '#fce7f3', to: '#fbcfe8', accent: '#9d174d' },
    'bottoms':     { from: '#dbeafe', to: '#bfdbfe', accent: '#1e40af' },
    'accessories': { from: '#d1fae5', to: '#a7f3d0', accent: '#065f46' },
  };
  return gradients[product.category?.toLowerCase()] || { from: '#f5f5f4', to: '#e7e5e4', accent: '#57534e' };
}

function productSvgIcon(category) {
  const icons = {
    'tops': `<svg viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg" class="w-20 h-20 opacity-20">
      <path d="M25 20L15 30L20 35L25 30V60H55V30L60 35L65 30L55 20H45C45 23.3 42.8 26 40 26S35 23.3 35 20H25Z" stroke="currentColor" stroke-width="2" fill="none"/>
    </svg>`,
    'dresses': `<svg viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg" class="w-20 h-20 opacity-20">
      <path d="M30 15L25 25L32 30L28 65H52L48 30L55 25L50 15H30Z" stroke="currentColor" stroke-width="2" fill="none"/>
      <path d="M35 15C35 15 37 20 40 20S45 15 45 15" stroke="currentColor" stroke-width="1.5" fill="none"/>
    </svg>`,
    'bottoms': `<svg viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg" class="w-20 h-20 opacity-20">
      <path d="M25 20H55V35L45 65H42L40 40L38 65H35L25 35V20Z" stroke="currentColor" stroke-width="2" fill="none"/>
    </svg>`,
    'accessories': `<svg viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg" class="w-20 h-20 opacity-20">
      <rect x="20" y="30" width="40" height="30" rx="4" stroke="currentColor" stroke-width="2" fill="none"/>
      <path d="M30 30V25C30 20 35 16 40 16S50 20 50 25V30" stroke="currentColor" stroke-width="2" fill="none"/>
      <circle cx="40" cy="45" r="4" stroke="currentColor" stroke-width="1.5" fill="none"/>
    </svg>`,
  };
  return icons[category?.toLowerCase()] || icons['accessories'];
}

function renderProductCard(product) {
  const inStock = product.stock_qty > 0;
  const grad = productGradient(product);

  return `
    <div class="product-card bg-white rounded-2xl overflow-hidden shadow-sm border border-stone-100 flex flex-col transition-all duration-200 hover:shadow-md ${!inStock ? 'opacity-60' : ''}">
      <!-- Product image placeholder -->
      <div class="relative aspect-[3/4] flex items-center justify-center overflow-hidden" style="background:linear-gradient(135deg, ${grad.from}, ${grad.to}); color: ${grad.accent}">
        ${productSvgIcon(product.category)}
        <div class="absolute bottom-3 left-3 right-3 text-center">
          <span class="text-xs font-medium tracking-wider uppercase opacity-30" style="color:${grad.accent}">${escHtml(product.name)}</span>
        </div>
        <div class="absolute top-3 left-3 flex flex-col gap-1">
          ${!inStock ? `<span class="bg-stone-500 text-white text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full">Sold out</span>` : ''}
        </div>
        <div class="absolute top-3 right-3 bg-white/80 backdrop-blur-sm text-stone-500 text-[10px] font-medium uppercase tracking-wider px-2 py-0.5 rounded-full border border-stone-200">
          ${product.category}
        </div>
      </div>

      <!-- Details -->
      <div class="p-4 flex flex-col gap-3 flex-1">
        <div class="flex-1">
          <h3 class="font-semibold text-stone-800 leading-tight">${escHtml(product.name)}</h3>
          ${product.description ? `<p class="text-stone-400 text-xs mt-1 leading-relaxed">${escHtml(product.description)}</p>` : ''}
        </div>

        <div class="flex items-center gap-2 text-xs text-stone-500">
          ${colorDot(product.color)}
          <span>${escHtml(product.color)}</span>
          <span class="text-stone-300">·</span>
          <span class="font-medium text-stone-600">Size ${escHtml(product.size)}</span>
        </div>

        <div class="flex items-center justify-between mt-auto pt-2 border-t border-stone-100">
          <span class="text-stone-800 font-semibold text-base">$${product.price.toFixed(2)}</span>
          <button
            data-product-id="${product.id}"
            class="add-to-cart-btn text-xs font-semibold uppercase tracking-wider px-4 py-2 rounded-full transition-all duration-200
              ${inStock
                ? 'bg-amber-800 text-white hover:bg-amber-700 active:scale-95 cursor-pointer'
                : 'bg-stone-200 text-stone-400 cursor-not-allowed'
              }"
            ${!inStock ? 'disabled' : ''}
          >
            ${inStock ? 'Add to Cart' : 'Sold Out'}
          </button>
        </div>
      </div>
    </div>`;
}

function renderProducts() {
  const grid = document.getElementById('product-grid');
  const filtered = activeCategory === 'all'
    ? allProducts
    : allProducts.filter(p => p.category === activeCategory);

  // Push out-of-stock items to end
  filtered.sort((a, b) => (a.stock_qty > 0 ? 0 : 1) - (b.stock_qty > 0 ? 0 : 1));

  if (filtered.length === 0) {
    grid.innerHTML = `
      <div class="col-span-full flex flex-col items-center justify-center py-24 text-stone-400">
        <svg class="w-12 h-12 mb-3 opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0H4"/>
        </svg>
        <p class="text-sm">No products in this category yet.</p>
      </div>`;
    return;
  }

  grid.innerHTML = filtered.map(renderProductCard).join('');

  grid.querySelectorAll('.add-to-cart-btn:not([disabled])').forEach(btn => {
    btn.addEventListener('click', () => {
      const product = allProducts.find(p => String(p.id) === btn.dataset.productId);
      if (product) addToCart(product);
    });
  });
}

// ---------------------------------------------------------------------------
// Cart panel
// ---------------------------------------------------------------------------

function renderCartBadge() {
  const badge = document.getElementById('cart-badge');
  const count = cartCount();
  badge.textContent = count;
  badge.classList.toggle('hidden', count === 0);
}

function renderCartPanel() {
  const list = document.getElementById('cart-items');
  const total = document.getElementById('cart-total');
  const emptyMsg = document.getElementById('cart-empty');
  const cartFooter = document.getElementById('cart-footer');
  const headerEl = document.getElementById('cart-header-title');

  if (cart.length === 0) {
    list.innerHTML = '';
    emptyMsg.classList.remove('hidden');
    cartFooter.classList.add('hidden');
    if (headerEl) headerEl.textContent = 'Your Cart';
    return;
  }

  emptyMsg.classList.add('hidden');
  cartFooter.classList.remove('hidden');
  const count = cartCount();
  if (headerEl) headerEl.textContent = `Your Cart (${count})`;

  list.innerHTML = cart.map(item => `
    <div class="flex gap-3 py-4 border-b border-stone-100 last:border-0" data-pid="${item.product_id}">
      <div class="w-14 h-16 rounded-lg bg-gradient-to-br from-stone-100 to-stone-200 flex items-center justify-center flex-shrink-0">
        <span class="text-stone-300 text-lg">✦</span>
      </div>
      <div class="flex-1 min-w-0">
        <p class="font-medium text-stone-800 text-sm leading-tight truncate">${escHtml(item.name)}</p>
        <p class="text-stone-400 text-xs mt-0.5">${escHtml(item.color)} · Size ${escHtml(item.size)}</p>
        <div class="flex items-center justify-between mt-2">
          <div class="flex items-center gap-1">
            <button class="qty-btn dec w-6 h-6 rounded-full bg-stone-100 hover:bg-stone-200 text-stone-600 text-sm font-medium flex items-center justify-center transition-colors" data-pid="${item.product_id}" data-delta="-1">−</button>
            <span class="w-6 text-center text-sm font-semibold text-stone-700">${item.qty}</span>
            <button class="qty-btn inc w-6 h-6 rounded-full bg-stone-100 hover:bg-stone-200 text-stone-600 text-sm font-medium flex items-center justify-center transition-colors" data-pid="${item.product_id}" data-delta="1">+</button>
          </div>
          <div class="flex items-center gap-2">
            <span class="text-stone-800 font-semibold text-sm">$${(item.price * item.qty).toFixed(2)}</span>
            <button class="remove-btn text-stone-300 hover:text-red-400 transition-colors" data-pid="${item.product_id}">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>`).join('');

  const totalVal = cartTotal();
  total.textContent = `$${totalVal.toFixed(2)}`;

  // Dynamic free shipping indicator
  const shippingMsg = document.getElementById('shipping-msg');
  if (shippingMsg) {
    if (totalVal >= 100) {
      shippingMsg.textContent = 'You qualify for free shipping!';
      shippingMsg.className = 'text-center text-xs text-green-600 font-medium mt-3';
    } else {
      const remaining = (100 - totalVal).toFixed(2);
      shippingMsg.textContent = `$${remaining} away from free shipping`;
      shippingMsg.className = 'text-center text-xs text-stone-400 mt-3';
    }
  }

  list.querySelectorAll('.qty-btn').forEach(btn => {
    btn.addEventListener('click', () => updateQty(btn.dataset.pid, parseInt(btn.dataset.delta)));
  });
  list.querySelectorAll('.remove-btn').forEach(btn => {
    btn.addEventListener('click', () => removeFromCart(btn.dataset.pid));
  });
}

function openCart() {
  const panel = document.getElementById('cart-panel');
  const overlay = document.getElementById('cart-overlay');
  panel.classList.remove('translate-x-full');
  overlay.classList.remove('opacity-0', 'pointer-events-none');
  renderCartPanel();
}

function closeCart() {
  const panel = document.getElementById('cart-panel');
  const overlay = document.getElementById('cart-overlay');
  panel.classList.add('translate-x-full');
  overlay.classList.add('opacity-0', 'pointer-events-none');
}

// ---------------------------------------------------------------------------
// Flash notification
// ---------------------------------------------------------------------------

function showCartFlash(name) {
  const flash = document.getElementById('cart-flash');
  flash.textContent = `"${name}" added to cart`;
  flash.classList.remove('opacity-0', 'translate-y-2');
  flash.classList.add('opacity-100', 'translate-y-0');
  setTimeout(() => {
    flash.classList.add('opacity-0', 'translate-y-2');
    flash.classList.remove('opacity-100', 'translate-y-0');
  }, 2500);
}

// ---------------------------------------------------------------------------
// Checkout
// ---------------------------------------------------------------------------

function showCheckout() {
  if (cart.length === 0) return;
  closeCart();
  currentView = 'checkout';

  document.getElementById('catalog-view').classList.add('hidden');
  document.getElementById('checkout-view').classList.remove('hidden');
  document.getElementById('confirmation-view').classList.add('hidden');

  renderCheckoutSummary();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function renderCheckoutSummary() {
  const summary = document.getElementById('checkout-summary');
  summary.innerHTML = cart.map(item => `
    <div class="flex justify-between items-center py-2 border-b border-stone-100 last:border-0">
      <div>
        <p class="text-sm font-medium text-stone-700">${escHtml(item.name)}</p>
        <p class="text-xs text-stone-400">${escHtml(item.color)} · Size ${escHtml(item.size)} · Qty ${item.qty}</p>
      </div>
      <span class="text-sm font-semibold text-stone-800">$${(item.price * item.qty).toFixed(2)}</span>
    </div>`).join('') + `
    <div class="flex justify-between items-center pt-3">
      <span class="font-semibold text-stone-800">Total</span>
      <span class="font-bold text-amber-800 text-lg">$${cartTotal().toFixed(2)}</span>
    </div>`;
}

async function submitOrder(event) {
  event.preventDefault();
  const form = event.target;
  const btn = document.getElementById('place-order-btn');
  const errorEl = document.getElementById('checkout-error');

  // Prevent double-clicks
  if (btn.disabled) return;

  const name = form.customer_name.value.trim();
  const email = form.customer_email.value.trim();
  const phone = form.customer_phone.value.trim();

  // Basic E.164 validation
  if (!/^\+[1-9]\d{6,14}$/.test(phone)) {
    errorEl.textContent = 'Please enter a valid phone number in E.164 format (e.g. +14155551234).';
    errorEl.classList.remove('hidden');
    return;
  }

  errorEl.classList.add('hidden');
  btn.disabled = true;
  btn.textContent = 'Placing Order…';

  const body = {
    customer_name: name,
    customer_email: email,
    customer_phone: phone,
    items: cart.map(i => ({ product_id: i.product_id, qty: i.qty })),
  };

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    const res = await fetch(`${API_BASE}/api/orders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    clearTimeout(timeout);

    let data;
    try { data = await res.json(); } catch { data = {}; }

    if (!res.ok) {
      throw new Error(data.message || data.error || `Server error ${res.status}`);
    }

    lastOrder = {
      order_id: data.order_id || data.id || `CB-${Date.now()}`,
      customer_name: name,
      customer_email: email,
      items: [...cart],
      total: cartTotal(),
    };

    // Save phone for abandonment recovery and clear timer
    localStorage.setItem('cb_customer_phone', phone);
    clearAbandonmentTimer();

    cart = [];
    saveCart();
    renderCartBadge();

    showConfirmation();
  } catch (err) {
    const msg = err.name === 'AbortError'
      ? 'Request timed out. Please try again.'
      : (err.message || 'Something went wrong. Please try again.');
    errorEl.textContent = msg;
    errorEl.classList.remove('hidden');
    btn.disabled = false;
    btn.textContent = 'Place Order';
  }
}

// ---------------------------------------------------------------------------
// Order confirmation
// ---------------------------------------------------------------------------

function showConfirmation() {
  currentView = 'confirmation';
  document.getElementById('catalog-view').classList.add('hidden');
  document.getElementById('checkout-view').classList.add('hidden');
  document.getElementById('confirmation-view').classList.remove('hidden');
  window.scrollTo({ top: 0, behavior: 'smooth' });

  if (!lastOrder) return;

  document.getElementById('conf-order-id').textContent = lastOrder.order_id;
  document.getElementById('conf-customer-name').textContent = lastOrder.customer_name;
  document.getElementById('conf-customer-email').textContent = lastOrder.customer_email;
  document.getElementById('conf-total').textContent = `$${lastOrder.total.toFixed(2)}`;

  const confItems = document.getElementById('conf-items');
  confItems.innerHTML = lastOrder.items.map(item => `
    <div class="flex justify-between items-center py-2 border-b border-stone-100 last:border-0">
      <div>
        <p class="text-sm font-medium text-stone-700">${escHtml(item.name)}</p>
        <p class="text-xs text-stone-400">${escHtml(item.color)} · Size ${escHtml(item.size)} · Qty ${item.qty}</p>
      </div>
      <span class="text-sm font-semibold text-stone-800">$${(item.price * item.qty).toFixed(2)}</span>
    </div>`).join('');
}

function backToShopping() {
  currentView = 'catalog';
  document.getElementById('catalog-view').classList.remove('hidden');
  document.getElementById('checkout-view').classList.add('hidden');
  document.getElementById('confirmation-view').classList.add('hidden');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ---------------------------------------------------------------------------
// Cart abandonment tracking
// ---------------------------------------------------------------------------

function saveCartToServer() {
  if (cart.length === 0) return;
  fetch(`${API_BASE}/api/carts/save`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: _sessionId,
      items: cart.map(i => ({ product_id: i.product_id, name: i.name, qty: i.qty, price: i.price })),
    }),
  }).catch(() => {}); // fire-and-forget
}

function resetAbandonmentTimer() {
  clearTimeout(_abandonmentTimer);
  if (cart.length === 0) return;
  _abandonmentTimer = setTimeout(triggerAbandonmentRecovery, ABANDONMENT_TIMEOUT_MS);
}

function clearAbandonmentTimer() {
  clearTimeout(_abandonmentTimer);
  _abandonmentTimer = null;
}

function triggerAbandonmentRecovery() {
  // Cart recovery is handled by OpenClaw via the recover_cart tool,
  // not auto-triggered from the storefront.
}

// ---------------------------------------------------------------------------
// Review submission (handled via WhatsApp survey, no web form)
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  // Cart button
  document.getElementById('cart-btn').addEventListener('click', openCart);
  document.getElementById('close-cart-btn').addEventListener('click', closeCart);
  document.getElementById('cart-overlay').addEventListener('click', closeCart);

  // Checkout trigger
  document.getElementById('checkout-btn').addEventListener('click', showCheckout);

  // Checkout form
  document.getElementById('checkout-form').addEventListener('submit', submitOrder);

  // Back to shopping
  document.getElementById('back-to-catalog-btn').addEventListener('click', () => {
    backToShopping();
  });
  document.getElementById('conf-back-btn').addEventListener('click', backToShopping);

  // Phone format hint: auto-prepend + if user hasn't; save for abandonment tracking
  const phoneInput = document.getElementById('customer_phone');
  phoneInput.addEventListener('blur', () => {
    const val = phoneInput.value.trim();
    if (val && !val.startsWith('+')) {
      phoneInput.value = '+' + val;
    }
    if (val) {
      localStorage.setItem('cb_customer_phone', phoneInput.value.trim());
      // Update server cart with phone
      saveCartToServer();
    }
  });

  // Auto-fill checkout for demo convenience
  const savedPhone = localStorage.getItem('cb_customer_phone') || '';
  document.getElementById('customer_phone').value = savedPhone;
  document.getElementById('customer_name').value = localStorage.getItem('cb_customer_name') || 'Demo Tester';
  document.getElementById('customer_email').value = localStorage.getItem('cb_customer_email') || 'test@example.com';
  localStorage.setItem('cb_customer_phone', savedPhone);

  // Initial render
  renderCartBadge();
  renderCategoryTabs();
  fetchProducts();

  // Restart abandonment timer if cart has items
  if (cart.length > 0) resetAbandonmentTimer();
});
