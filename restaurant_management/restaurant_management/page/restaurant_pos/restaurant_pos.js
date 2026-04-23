frappe.pages["restaurant-pos"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Restaurant POS",
		single_column: true,
	});

	// Hide the default Frappe page title bar
	$(page.wrapper).find(".page-head").hide();

	$(frappe.render_template("restaurant_pos")).appendTo(page.body);
	new RestaurantPOS(page);
};

/* ═══════════════════════════════════════════════════════
   RESTAURANT POS — v2.2
   Fixes:
     - Item qty always starts at 1 (single stable event delegation)
     - Table occupancy bar with accurate seat count
     - Covers / guest count per order
═══════════════════════════════════════════════════════ */
class RestaurantPOS {
	constructor(page) {
		this.page            = page;
		this.order_items     = {};   // { item_id: { menu_item, item_name, price, quantity } }
		this.order_type      = "Dine In";
		this.selected_table  = null;
		this.covers          = null; // guest count
		this.currency_symbol = "₹";
		this.menu_items      = {};   // { category: [items] }
		this.active_category = null;
		this.orders_filter   = "active";

		this._init();
	}

	_init() {
		this._collapse_frappe_sidebar();
		this._load_settings();
		this._setup_tabs();
		this._setup_topbar_controls();
		this._setup_menu_item_clicks(); // ← single binding, not per-render
		this._setup_order_events();
		this._setup_clock();
		this.load_menu();
		this.load_tables();
	}

	/* ─────────────────────────────────────────
	   COLLAPSE FRAPPE NATIVE SIDEBAR BY DEFAULT
	───────────────────────────────────────── */
	_collapse_frappe_sidebar() {
		frappe.after_ajax(() => {
			setTimeout(() => {
				// Only collapse if not already collapsed
				if (!$("body").hasClass("sidebar-collapsed") &&
					!$(".layout-side-section").hasClass("hidden")) {
					const $link = $(".collapse-sidebar-link");
					if ($link.length) {
						$link.trigger("click");
					}
				}
			}, 350);
		});
	}

	/* ─────────────────────────────
	   SETTINGS
	───────────────────────────── */
	_load_settings() {
		frappe.call({
			method: "frappe.client.get",
			args: { doctype: "Restaurant Settings" },
			async: false,
			callback: (r) => {
				if (r.message) {
					this.currency_symbol = r.message.default_currency_symbol || "₹";
				}
			},
		});
	}

	/* ─────────────────────────────
	   LIVE CLOCK
	───────────────────────────── */
	_setup_clock() {
		const tick = () => {
			const n = new Date();
			const p = (v) => String(v).padStart(2, "0");
			$("#rpos-clock").text(`${p(n.getHours())}:${p(n.getMinutes())}:${p(n.getSeconds())}`);
		};
		tick();
		setInterval(tick, 1000);
	}

	/* ─────────────────────────────
	   TAB NAVIGATION
	───────────────────────────── */
	_setup_tabs() {
		$(".rpos-tab").on("click", (e) => {
			this._switch_tab($(e.currentTarget).data("tab"));
		});
	}

	_switch_tab(tab) {
		$(".rpos-tab").removeClass("active");
		$(`.rpos-tab[data-tab="${tab}"]`).addClass("active");
		$(".rpos-pane").removeClass("active");
		$(`#tab-${tab}`).addClass("active");

		if (tab === "new-order") {
			$("#rpos-topbar-controls").show();
			$("#rpos-topbar-orders-ctrl").hide();
		} else if (tab === "orders-list") {
			$("#rpos-topbar-controls").hide();
			$("#rpos-topbar-orders-ctrl").show();
			this.load_orders();
		} else {
			$("#rpos-topbar-controls").hide();
			$("#rpos-topbar-orders-ctrl").hide();
			if (tab === "tables-view") this.load_tables();
		}
	}

	/* ─────────────────────────────
	   TOPBAR CONTROLS
	───────────────────────────── */
	_setup_topbar_controls() {
		// Order type toggle
		$(".rpos-type-btn").on("click", (e) => {
			$(".rpos-type-btn").removeClass("active");
			$(e.currentTarget).addClass("active");
			this.order_type = $(e.currentTarget).data("type");

			if (this.order_type === "Parcel") {
				$("#rpos-table-wrap, #rpos-guests-wrap").hide();
				this.selected_table = null;
				this.covers = null;
			} else {
				$("#rpos-table-wrap, #rpos-guests-wrap").show();
			}
		});

		// Table selector
		$("#table-selector").on("change", (e) => {
			this.selected_table = $(e.currentTarget).val() || null;
		});

		// Covers / guest count
		$("#covers-input").on("input", (e) => {
			const val = parseInt($(e.currentTarget).val(), 10);
			this.covers = val > 0 ? val : null;
		});

		// Orders filter buttons
		$(document).on("click", ".rpos-filter-btn", (e) => {
			$(".rpos-filter-btn").removeClass("active");
			$(e.currentTarget).addClass("active");
			this.orders_filter = $(e.currentTarget).data("status");
			this.load_orders();
		});

		// Refresh orders
		$(document).on("click", "#btn-refresh-orders", () => this.load_orders());
	}

	/* ─────────────────────────────
	   MENU ITEM CLICKS — single stable binding
	   ⚠ Key fix: bound ONCE on #rpos-root, never re-bound
	   This prevents qty doubling/tripling when switching categories
	───────────────────────────── */
	_setup_menu_item_clicks() {
		// Single delegation on stable parent — survives any #menu-items re-render
		$("#rpos-root").on("click", ".rpos-item-card, .rpos-item-add", (e) => {
			e.stopPropagation();
			const $card     = $(e.currentTarget).closest(".rpos-item-card");
			const item_id   = $card.data("item");
			const item_name = $card.data("name");
			const price     = parseFloat($card.data("price"));
			if (!item_id || isNaN(price)) return;
			this.add_item(item_id, item_name, price);
			// Visual pulse feedback
			$card.addClass("rpos-card-pulse");
			setTimeout(() => $card.removeClass("rpos-card-pulse"), 300);
		});
	}

	/* ─────────────────────────────
	   ORDER EVENTS
	───────────────────────────── */
	_setup_order_events() {
		$("#btn-clear-order").on("click", () => {
			if (Object.keys(this.order_items).length === 0) return;
			frappe.confirm(__("Clear the current order?"), () => this.clear_order());
		});

		$("#btn-save-order").on("click", () => this.place_order());

		// Menu search
		$("#menu-search").on("input", (e) => {
			const val = $(e.currentTarget).val();
			$("#rpos-search-clear").toggleClass("visible", !!val);
			this.filter_menu(val);
		});

		$("#rpos-search-clear").on("click", () => {
			$("#menu-search").val("").trigger("input");
		});
	}

	/* ═══════════════════════════════════════
	   ORDERS LIST
	═══════════════════════════════════════ */
	load_orders() {
		$("#orders-list").html(`
			<div class="rpos-orders-empty">
				<div class="rpos-spinner" style="margin:0 auto 14px"></div>
				<p>Loading orders…</p>
			</div>
		`);

		let filters = {};
		if (this.orders_filter === "active") {
			filters.status = ["in", ["In Progress", "Preparing", "Ready", "Served"]];
		} else {
			filters.status = this.orders_filter;
		}

		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Restaurant Order",
				filters,
				fields: ["name", "order_type", "table", "status", "total_amount",
					"total_qty", "order_date", "customer_name", "payment_status"],
				order_by: "modified desc",
				limit_page_length: 50,
			},
			callback: (r) => {
				if (r.message) this.render_orders(r.message);
			},
		});
	}

	render_orders(orders) {
		const $list = $("#orders-list").empty();

		if (this.orders_filter === "active") {
			$("#orders-badge").text(orders.length || "");
		}

		if (orders.length === 0) {
			$list.html(`
				<div class="rpos-orders-empty">
					<div class="rp-empty-icon">📭</div>
					<p>No orders found</p>
				</div>
			`);
			return;
		}

		const statusColors = {
			"In Progress": "#FF9800", "Preparing": "#FFC107",
			"Ready": "#9C27B0", "Served": "#00BCD4",
			"Completed": "#4CAF50", "Cancelled": "#EF4444",
		};

		orders.forEach((order) => {
			const typePill = order.order_type === "Dine In" && order.table
				? `<span class="rpos-oc-pill rpos-oc-pill-dine">🪑 ${order.table}</span>`
				: `<span class="rpos-oc-pill rpos-oc-pill-parcel">📦 Parcel</span>`;

			$list.append(`
				<div class="rpos-order-card" data-order="${order.name}">
					<div>
						<div class="rpos-oc-name">${order.name}</div>
						<div class="rpos-oc-meta">
							${typePill}
							<span class="rpos-oc-time">
								<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
									<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
								</svg>
								${this._time_ago(order.order_date)}
							</span>
							${order.customer_name ? `<span class="rpos-oc-customer">${order.customer_name}</span>` : ""}
						</div>
					</div>
					<div class="rpos-oc-center">
						<span class="rpos-oc-status" style="background:${statusColors[order.status] || '#888'}">${order.status}</span>
						<span class="rpos-oc-amount">${this.currency_symbol}${parseFloat(order.total_amount).toFixed(2)}</span>
						${order.payment_status === "Paid" ? `<span class="rpos-oc-paid">💰 Paid</span>` : ""}
					</div>
					<div class="rpos-oc-actions">${this._get_action_btns(order)}</div>
				</div>
			`);
		});

		$list.find(".rpos-action-btn").on("click", (e) => {
			e.stopPropagation();
			const $btn = $(e.currentTarget);
			const orderName = $btn.data("order");
			const status    = $btn.data("status");
			if (status === "PAYMENT")    this.show_payment_dialog(orderName);
			else if (status === "PRINT_BILL") this.print_bill(orderName);
			else this.update_order_status(orderName, status);
		});
	}

	_get_action_btns(order) {
		switch (order.status) {
			case "In Progress":
				return `<button class="rpos-action-btn rpos-ab-preparing" data-order="${order.name}" data-status="Preparing">🔥 Start Preparing</button>`;
			case "Preparing":
				return `<button class="rpos-action-btn rpos-ab-ready" data-order="${order.name}" data-status="Ready">✅ Mark Ready</button>`;
			case "Ready":
				return `<button class="rpos-action-btn rpos-ab-served" data-order="${order.name}" data-status="Served">🍽️ Mark Served</button>`;
			case "Served": {
				let b = `<button class="rpos-action-btn rpos-ab-print" data-order="${order.name}" data-status="PRINT_BILL">🧾 Print Bill</button>`;
				b += order.payment_status !== "Paid"
					? `<button class="rpos-action-btn rpos-ab-payment" data-order="${order.name}" data-status="PAYMENT">💰 Collect Payment</button>`
					: `<button class="rpos-action-btn rpos-ab-complete" data-order="${order.name}" data-status="Completed">✔️ Complete</button>`;
				return b;
			}
			case "Completed":
				return `<span class="rpos-done-label">✅ Done</span>`;
			default: return "";
		}
	}

	update_order_status(order_name, status) {
		frappe.call({
			method: "restaurant_management.restaurant_management.api.update_order_status",
			args: { order_name, status },
			callback: (r) => {
				if (r.message?.status === "success") {
					frappe.show_alert({ message: r.message.message, indicator: "green" });
					this.load_orders();
					this.load_tables();
				}
			},
		});
	}

	show_payment_dialog(order_name) {
		const d = new frappe.ui.Dialog({
			title: __("Collect Payment — {0}", [order_name]),
			fields: [{ label: __("Payment Mode"), fieldname: "payment_mode", fieldtype: "Select",
				options: "Cash\nCard\nUPI\nOther", default: "Cash", reqd: 1 }],
			primary_action_label: __("Confirm Payment"),
			primary_action: (values) => {
				frappe.call({
					method: "restaurant_management.restaurant_management.api.collect_payment",
					args: { order_name, payment_mode: values.payment_mode },
					callback: (r) => {
						if (r.message?.status === "success") {
							frappe.show_alert({ message: r.message.message, indicator: "green" });
							d.hide(); this.load_orders();
						}
					},
				});
			},
		});
		d.show();
	}

	print_bill(order_name) {
		frappe.call({
			method: "restaurant_management.restaurant_management.api.get_bill_data",
			args: { order_name },
			callback: (res) => {
				if (!res.message) return;
				let f = document.getElementById("receipt-print-frame");
				if (!f) {
					f = Object.assign(document.createElement("iframe"),
						{ id: "receipt-print-frame", style: "display:none" });
					document.body.appendChild(f);
				}
				const doc = f.contentWindow.document;
				doc.open(); doc.write(res.message); doc.close();
				setTimeout(() => { f.contentWindow.focus(); f.contentWindow.print(); }, 500);
			},
		});
	}

	_time_ago(dt) {
		if (!dt) return "";
		const d = Math.floor((Date.now() - new Date(dt)) / 60000);
		if (d < 1) return "just now";
		if (d < 60) return `${d}m ago`;
		const h = Math.floor(d / 60);
		return h < 24 ? `${h}h ago` : `${Math.floor(h/24)}d ago`;
	}

	/* ═══════════════════════════════════════
	   MENU
	═══════════════════════════════════════ */
	load_menu() {
		frappe.call({
			method: "restaurant_management.restaurant_management.api.get_menu_items",
			callback: (r) => {
				if (!r.message) return;
				this.menu_items = r.message;
				this.render_categories();
				const first = Object.keys(this.menu_items)[0];
				if (first) {
					this.active_category = first;
					this.render_menu_items(first);
				} else {
					this._show_items_empty("No menu items found");
				}
			},
		});
	}

	load_tables() {
		frappe.call({
			method: "restaurant_management.restaurant_management.api.get_tables",
			callback: (r) => {
				if (!r.message) return;
				const $sel = $("#table-selector");
				$sel.find("option:not(:first)").remove();
				r.message.forEach((t) => {
					if (t.status === "Available") {
						$sel.append(`<option value="${t.name}">Table ${t.table_number} (${t.seating_capacity} seats)</option>`);
					}
				});
				this.render_tables(r.message);
			},
		});
	}

	render_categories() {
		const $c = $("#menu-categories").empty();
		Object.keys(this.menu_items).forEach((cat) => {
			const count = this.menu_items[cat].length;
			$c.append(`
				<button class="rpos-cat-btn ${cat === this.active_category ? "active" : ""}" data-category="${cat}">
					${cat} <span class="rpos-cat-count">${count}</span>
				</button>
			`);
		});

		$c.on("click", ".rpos-cat-btn", (e) => {
			$(".rpos-cat-btn").removeClass("active");
			$(e.currentTarget).addClass("active");
			this.active_category = $(e.currentTarget).data("category");
			this.render_menu_items(this.active_category);
		});
	}

	/* ─────────────────────────────
	   Render items — NO click binding here anymore.
	   All clicks are handled by _setup_menu_item_clicks()
	   so qty is always exactly +1 per click.
	───────────────────────────── */
	render_menu_items(category) {
		const $grid = $("#menu-items").empty();
		const items = this.menu_items[category] || [];
		if (!items.length) { this._show_items_empty("No items in this category"); return; }
		items.forEach((item) => this._render_item_card($grid, item));
	}

	filter_menu(search_text) {
		search_text = (search_text || "").toLowerCase().trim();
		if (!search_text) {
			if (this.active_category) this.render_menu_items(this.active_category);
			return;
		}
		const $grid   = $("#menu-items").empty();
		const results = Object.values(this.menu_items).flat()
			.filter(i => i.item_name.toLowerCase().includes(search_text));
		if (!results.length) { this._show_items_empty(`No results for "${search_text}"`); return; }
		results.forEach((item) => this._render_item_card($grid, item));
	}

	_render_item_card($container, item) {
		const imgHtml = item.image
			? `<img src="${item.image}" class="rpos-item-img" alt="${item.item_name}"
				onerror="this.parentElement.innerHTML='<div class=\\'rpos-item-placeholder\\'>🍽️</div>'">`
			: `<div class="rpos-item-placeholder">🍽️</div>`;

		// Show current qty badge if item already in cart
		const inCart   = this.order_items[item.name];
		const badgeHtml = inCart
			? `<span class="rpos-item-qty-badge visible">×${inCart.quantity}</span>`
			: `<span class="rpos-item-qty-badge"></span>`;

		$container.append(`
			<div class="rpos-item-card" data-item="${item.name}" data-name="${item.item_name}" data-price="${item.price}">
				<div class="rpos-item-img-wrap">
					${imgHtml}
					<button class="rpos-item-add" data-item="${item.name}" data-name="${item.item_name}" data-price="${item.price}" title="Add to order">+</button>
				</div>
				<div class="rpos-item-body">
					<div class="rpos-item-name">${item.item_name}</div>
					${item.description ? `<div class="rpos-item-desc">${item.description}</div>` : ""}
					<div class="rpos-item-footer">
						<span class="rpos-item-price">${this.currency_symbol}${parseFloat(item.price).toFixed(2)}</span>
						${badgeHtml}
					</div>
				</div>
			</div>
		`);
	}

	_show_items_empty(msg) {
		$("#menu-items").html(`
			<div class="rpos-items-empty">
				<div class="rp-empty-icon">🥗</div>
				<p>${msg}</p>
			</div>
		`);
	}

	/* ─────────────────────────────
	   Update the qty badge on a single card without re-rendering
	───────────────────────────── */
	_refresh_card_badge(item_id) {
		const $card  = $(`#menu-items .rpos-item-card[data-item="${item_id}"]`);
		if (!$card.length) return;
		const $badge = $card.find(".rpos-item-qty-badge");
		const entry  = this.order_items[item_id];
		if (entry) {
			$badge.text(`×${entry.quantity}`).addClass("visible");
		} else {
			$badge.text("").removeClass("visible");
		}
	}

	/* ═══════════════════════════════════════
	   CART
	═══════════════════════════════════════ */
	add_item(item_id, item_name, price) {
		if (this.order_items[item_id]) {
			this.order_items[item_id].quantity += 1;
		} else {
			// Default quantity = 1 (always starts at 1, never 0)
			this.order_items[item_id] = { menu_item: item_id, item_name, price, quantity: 1 };
		}
		this.render_order();
		this._refresh_card_badge(item_id);
	}

	remove_item(item_id) {
		delete this.order_items[item_id];
		this.render_order();
		this._refresh_card_badge(item_id);
	}

	update_quantity(item_id, delta) {
		if (!this.order_items[item_id]) return;
		this.order_items[item_id].quantity += delta;
		if (this.order_items[item_id].quantity <= 0) {
			delete this.order_items[item_id];
		}
		this.render_order();
		this._refresh_card_badge(item_id);
	}

	render_order() {
		const $c   = $("#order-items").empty();
		const items = Object.values(this.order_items);

		if (!items.length) {
			$c.html(`
				<div class="rpos-cart-empty">
					<div class="rpos-empty-bowl">🥣</div>
					<p>Cart is empty</p>
					<small>Tap any item to add</small>
				</div>
			`);
			$("#order-count").text("0 items");
			$("#order-total, #order-subtotal").text(`${this.currency_symbol}0.00`);
			return;
		}

		let total = 0, qty_total = 0;

		items.forEach((item) => {
			const amount = item.price * item.quantity;
			total     += amount;
			qty_total += item.quantity;

			$c.append(`
				<div class="rpos-cart-row" data-item="${item.menu_item}">
					<div class="rpos-cart-row-info">
						<div class="rpos-cart-row-name">${item.item_name}</div>
						<div class="rpos-cart-row-unit">${this.currency_symbol}${item.price.toFixed(2)} each</div>
					</div>
					<div class="rpos-qty-ctrl">
						<button class="rpos-qty-btn rpos-btn-minus" data-item="${item.menu_item}">−</button>
						<span class="rpos-qty-val">${item.quantity}</span>
						<button class="rpos-qty-btn rpos-btn-plus"  data-item="${item.menu_item}">+</button>
					</div>
					<div class="rpos-cart-row-amount">${this.currency_symbol}${amount.toFixed(2)}</div>
					<button class="rpos-cart-remove" data-item="${item.menu_item}" title="Remove">
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="13" height="13">
							<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
						</svg>
					</button>
				</div>
			`);
		});

		// Bind cart row controls
		$c.find(".rpos-btn-minus").on("click",      (e) => this.update_quantity($(e.currentTarget).data("item"), -1));
		$c.find(".rpos-btn-plus").on("click",       (e) => this.update_quantity($(e.currentTarget).data("item"),  1));
		$c.find(".rpos-cart-remove").on("click",    (e) => this.remove_item($(e.currentTarget).data("item")));

		const totalStr = `${this.currency_symbol}${total.toFixed(2)}`;
		$("#order-count").text(`${qty_total} item${qty_total !== 1 ? "s" : ""}`);
		$("#order-subtotal, #order-total").text(totalStr);

		// Bounce animation on total update
		const $tot = $("#order-total");
		$tot.css("transform", "scale(1.12)");
		setTimeout(() => $tot.css("transform", "scale(1)"), 180);
	}

	clear_order() {
		const ids = Object.keys(this.order_items);
		this.order_items = {};
		this.render_order();
		ids.forEach((id) => this._refresh_card_badge(id));
	}

	place_order() {
		const items = Object.values(this.order_items);
		if (!items.length) { frappe.msgprint(__("Please add at least one item.")); return; }
		if (this.order_type === "Dine In" && !this.selected_table) {
			frappe.msgprint(__("Please select a table for Dine In orders."));
			return;
		}

		const $btn = $("#btn-save-order").prop("disabled", true).html(`
			<div class="rpos-spinner" style="width:15px;height:15px;border-width:2px;"></div> Placing…
		`);

		const restoreBtn = () => $btn.prop("disabled", false).html(`
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="14" height="14">
				<polyline points="20 6 9 17 4 12"/>
			</svg> Place Order
		`);

		frappe.call({
			method: "restaurant_management.restaurant_management.api.create_order",
			args: {
				items:      JSON.stringify(items.map(i => ({ menu_item: i.menu_item, quantity: i.quantity }))),
				order_type: this.order_type,
				table:      this.selected_table || "",
				covers:     this.covers || "",
			},
			callback: (r) => {
				restoreBtn();
				if (r.message) {
					frappe.show_alert({ message: __("Order {0} placed!", [r.message]), indicator: "green" });
					this.clear_order();
					// Reset guest count input
					$("#covers-input").val("");
					this.covers = null;
					this.load_tables();

					frappe.confirm(__("Order placed! Print KOT?"), () => {
						frappe.call({
							method: "restaurant_management.restaurant_management.api.get_kot_data",
							args: { order_name: r.message },
							callback: (res) => {
								if (res.message) {
									const w = window.open();
									w.document.write(res.message);
									w.document.close();
									w.print();
								}
							},
						});
					});
				}
			},
			error: restoreBtn,
		});
	}

	/* ═══════════════════════════════════════
	   TABLES — with occupancy bar
	═══════════════════════════════════════ */
	render_tables(tables) {
		const $grid = $("#tables-grid").empty();

		if (!tables.length) {
			$grid.html(`<p style="color:var(--rp-text-muted);padding:16px">No tables configured.</p>`);
			return;
		}

		tables.forEach((table) => {
			const cls      = (table.status || "Available").toLowerCase().replace(" ", "-");
			const capacity = table.seating_capacity || 0;
			// occupied_seats comes from API (covers if set, else full capacity when occupied)
			const occupied = (table.status === "Available") ? 0 : (table.occupied_seats || capacity);
			const available = Math.max(0, capacity - occupied);
			const pct      = capacity > 0 ? Math.round((occupied / capacity) * 100) : 0;

			let orderInfo = "";
			if (table.current_order && table.order_items?.length) {
				const itemsStr = table.order_items.map(i => `${i.item_name} ×${i.quantity}`).join(", ");
				orderInfo = `
					<div class="rpos-tc-order-info">
						<div class="rpos-tc-order-items">${itemsStr}</div>
						<div class="rpos-tc-order-total">${this.currency_symbol}${parseFloat(table.order_total).toFixed(2)}</div>
					</div>
				`;
			}

			const actions = table.status === "Occupied" ? `
				<div class="rpos-tc-actions">
					<button class="rpos-tc-btn rpos-tc-btn-clear" data-table="${table.name}" data-number="${table.table_number}">✓ Clear</button>
					<button class="rpos-tc-btn rpos-tc-btn-view"  data-order="${table.current_order}">👁 View</button>
				</div>
			` : "";

			$grid.append(`
				<div class="rpos-table-card ${cls}">
					<div class="rpos-tc-head">
						<div class="rpos-tc-number">Table ${table.table_number}</div>
						<span class="rpos-tc-status-pill">${table.status}</span>
					</div>

					<!-- Seat occupancy bar -->
					<div class="rpos-tc-occupancy">
						<div class="rpos-tc-occ-label">
							<span>
								<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="11" height="11" style="vertical-align:middle;margin-right:3px">
									<circle cx="12" cy="7" r="4"/><path d="M5.5 21a9.5 9.5 0 0113 0"/>
								</svg>
								${occupied}/${capacity} seats
							</span>
							<strong>${available} free</strong>
						</div>
						<div class="rpos-tc-occ-bar-track">
							<div class="rpos-tc-occ-bar-fill" style="width:${pct}%"></div>
						</div>
					</div>

					${orderInfo}
					${actions}
				</div>
			`);
		});

		$grid.find(".rpos-tc-btn-clear").on("click", (e) => {
			e.stopPropagation();
			const tname = $(e.currentTarget).data("table");
			const tnum  = $(e.currentTarget).data("number");
			frappe.confirm(__("Clear Table {0} and complete the order?", [tnum]), () => {
				frappe.call({
					method: "restaurant_management.restaurant_management.api.clear_table",
					args: { table_name: tname },
					callback: (r) => {
						if (r.message?.status === "success") {
							frappe.show_alert({ message: r.message.message, indicator: "green" });
							this.load_tables();
						}
					},
				});
			});
		});

		$grid.find(".rpos-tc-btn-view").on("click", (e) => {
			e.stopPropagation();
			frappe.set_route("Form", "Restaurant Order", $(e.currentTarget).data("order"));
		});
	}
}
