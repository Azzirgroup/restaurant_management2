frappe.pages["kitchen-display"].on_page_load = function (wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "Kitchen Display",
        single_column: true,
    });

    $(frappe.render_template("kitchen_display")).appendTo(page.body);
    new KitchenDisplay(page);
};

class KitchenDisplay {
    constructor(page) {
        this.page = page;
        this.refresh_interval = null;
        this.orders = [];

        this.setup_clock();
        this.setup_events();
        this.load_orders();
        this.start_auto_refresh();
    }

    setup_clock() {
        this.update_clock();
        setInterval(() => this.update_clock(), 1000);
    }

    update_clock() {
        let now = new Date();
        let time = now.toLocaleTimeString("en-IN", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
        });
        $("#kds-clock").text(time);
    }

    setup_events() {
        // Fullscreen toggle
        $("#kds-fullscreen").on("click", () => {
            let el = document.documentElement;
            if (!document.fullscreenElement) {
                el.requestFullscreen().catch(() => { });
            } else {
                document.exitFullscreen();
            }
        });
    }

    start_auto_refresh() {
        this.refresh_interval = setInterval(() => {
            this.load_orders();
        }, 10000);
    }

    load_orders() {
        frappe.call({
            method: "restaurant_management.restaurant_management.api.get_kitchen_orders",
            callback: (r) => {
                if (r.message) {
                    this.orders = r.message;
                    this.render_orders();
                }
            },
        });
    }

    render_orders() {
        let $container = $("#kds-orders");
        $container.empty();

        if (this.orders.length === 0) {
            $container.html(`
				<div class="kds-empty">
					<i class="fa fa-check-circle fa-4x"></i>
					<h3>All Clear!</h3>
					<p>No pending orders</p>
				</div>
			`);
            $("#kds-order-count").text("0 active");
            return;
        }

        $("#kds-order-count").text(`${this.orders.length} active`);

        this.orders.forEach((order) => {
            let elapsed = this.get_elapsed_time(order.order_date);
            let urgency_class = this.get_urgency_class(elapsed.minutes);

            (order.items || []).forEach((item) => {
                let is_prepared = item.status === "Prepared";
                items_html += `
					<div class="kds-item ${is_prepared ? 'is-prepared' : ''}" 
                         data-item-name="${item.name}" 
                         data-order="${order.name}">
						<span class="kds-item-qty">${item.quantity}×</span>
						<span class="kds-item-name">${item.item_name}</span>
                        <div class="kds-item-status">
                            <i class="fa ${is_prepared ? 'fa-check-circle' : 'fa-circle-o'}"></i>
                        </div>
					</div>
				`;
            });

            let table_badge = "";
            if (order.order_type === "Dine In" && order.table_number) {
                table_badge = `<span class="kds-table-badge dine-in">🪑 Table ${order.table_number}</span>`;
            } else {
                table_badge = `<span class="kds-table-badge parcel">📦 PARCEL</span>`;
            }

            // Status badge
            let status_badge = "";
            if (order.status === "In Progress") {
                status_badge = `<span class="kds-status-badge status-new">🆕 NEW</span>`;
            } else if (order.status === "Preparing") {
                status_badge = `<span class="kds-status-badge status-preparing">🔥 PREPARING</span>`;
            }

            // Action buttons based on status
            let action_buttons = "";
            if (order.status === "In Progress") {
                action_buttons = `
					<button class="btn btn-kds-start" data-order="${order.name}">
						<i class="fa fa-fire"></i> Start Preparing
					</button>
				`;
            } else if (order.status === "Preparing") {
                action_buttons = `
					<button class="btn btn-kds-done" data-order="${order.name}">
						<i class="fa fa-check"></i> Ready to Serve
					</button>
				`;
            }

            $container.append(`
				<div class="kds-order-card ${urgency_class} ${order.status === 'Preparing' ? 'is-preparing' : ''}" data-order="${order.name}">
					<div class="kds-order-header">
						<div class="kds-order-id">${order.name}</div>
						${table_badge}
					</div>
					<div class="kds-order-meta">
						${status_badge}
						<div class="kds-order-timer">
							<i class="fa fa-clock"></i> ${elapsed.display}
						</div>
					</div>
					<div class="kds-order-items">
						${items_html}
					</div>
					${order.notes ? `<div class="kds-order-notes"><i class="fa fa-sticky-note"></i> ${order.notes}</div>` : ""}
					<div class="kds-order-actions">
						${action_buttons}
					</div>
				</div>
			`);
        });

        // Bind "Start Preparing" buttons
        $container.find(".btn-kds-start").on("click", (e) => {
            e.stopPropagation();
            let order_name = $(e.currentTarget).data("order");
            this.start_preparing(order_name);
        });

        // Bind "Ready to Serve" buttons
        $container.find(".btn-kds-done").on("click", (e) => {
            e.stopPropagation();
            let order_name = $(e.currentTarget).data("order");
            this.mark_ready(order_name);
        });

        // Bind item status toggle
        $container.find(".kds-item").on("click", (e) => {
            e.stopPropagation();
            let $item = $(e.currentTarget);
            let item_name = $item.data("item-name");
            let is_prepared = $item.hasClass("is-prepared");
            let new_status = is_prepared ? "Pending" : "Prepared";

            this.toggle_item_status(item_name, new_status);
        });
    }

    toggle_item_status(item_name, status) {
        frappe.call({
            method: "restaurant_management.restaurant_management.api.update_item_status",
            args: { item_name: item_name, status: status },
            callback: (r) => {
                if (r.message && r.message.status === "success") {
                    this.load_orders();
                }
            },
        });
    }

    get_elapsed_time(order_date) {
        let now = new Date();
        let order_time = new Date(order_date);
        let diff_ms = now - order_time;
        let minutes = Math.floor(diff_ms / 60000);
        let seconds = Math.floor((diff_ms % 60000) / 1000);

        let display = "";
        if (minutes >= 60) {
            let hours = Math.floor(minutes / 60);
            let mins = minutes % 60;
            display = `${hours}h ${mins}m`;
        } else {
            display = `${minutes}m ${seconds}s`;
        }

        return { minutes, seconds, display };
    }

    get_urgency_class(minutes) {
        if (minutes >= 20) return "urgency-critical";
        if (minutes >= 10) return "urgency-warning";
        return "urgency-normal";
    }

    start_preparing(order_name) {
        frappe.call({
            method: "restaurant_management.restaurant_management.api.update_order_status",
            args: { order_name: order_name, status: "Preparing" },
            callback: (r) => {
                if (r.message && r.message.status === "success") {
                    frappe.show_alert({
                        message: __("Now preparing {0}", [order_name]),
                        indicator: "yellow",
                    });
                    this.load_orders();
                }
            },
        });
    }

    mark_ready(order_name) {
        frappe.call({
            method: "restaurant_management.restaurant_management.api.update_order_status",
            args: { order_name: order_name, status: "Ready" },
            callback: (r) => {
                if (r.message && r.message.status === "success") {
                    $(`.kds-order-card[data-order="${order_name}"]`)
                        .addClass("kds-done-animation")
                        .fadeOut(500, () => {
                            this.load_orders();
                        });

                    frappe.show_alert({
                        message: __("Order {0} is ready to serve! 🔔", [order_name]),
                        indicator: "green",
                    });
                }
            },
        });
    }
}
