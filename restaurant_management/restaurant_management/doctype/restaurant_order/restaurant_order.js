// Copyright (c) 2026, Restaurant Management and contributors
// For license information, please see license.txt

frappe.ui.form.on("Restaurant Order", {
    refresh: function (frm) {
        // Status indicators
        frm.set_indicator_formatter("status", function (doc) {
            let colors = {
                Draft: "blue",
                "In Progress": "orange",
                Preparing: "yellow",
                Ready: "purple",
                Served: "cyan",
                Completed: "green",
                Cancelled: "red",
            };
            return colors[doc.status] || "grey";
        });

        // === Status-based action buttons ===

        // In Progress → Preparing (Kitchen acknowledges)
        if (frm.doc.status === "In Progress") {
            frm.add_custom_button(__("Start Preparing"), function () {
                frm.set_value("status", "Preparing");
                frm.save();
            }, __("Actions")).addClass("btn-warning");
        }

        // Preparing → Ready (Kitchen done cooking)
        if (frm.doc.status === "Preparing") {
            frm.add_custom_button(__("Mark Ready"), function () {
                frm.set_value("status", "Ready");
                frm.save();
            }, __("Actions")).addClass("btn-info");
        }

        // Ready → Served (Captain served to table)
        if (frm.doc.status === "Ready") {
            frm.add_custom_button(__("Mark Served"), function () {
                frm.set_value("status", "Served");
                frm.save();
            }, __("Actions")).addClass("btn-primary");
        }

        // Served → Collect Payment → Complete
        if (frm.doc.status === "Served" && frm.doc.payment_status === "Unpaid") {
            frm.add_custom_button(__("Collect Payment"), function () {
                show_payment_dialog(frm);
            }, __("Actions")).addClass("btn-success");
        }

        // Served + Paid → Complete
        if (frm.doc.status === "Served" && frm.doc.payment_status === "Paid") {
            frm.add_custom_button(__("Complete Order"), function () {
                frm.set_value("status", "Completed");
                frm.save();
            }, __("Actions")).addClass("btn-success");
        }

        // Cancel (available for In Progress/Preparing/Ready)
        if (["In Progress", "Preparing", "Ready"].includes(frm.doc.status)) {
            frm.add_custom_button(__("Cancel Order"), function () {
                frappe.confirm(
                    __("Are you sure you want to cancel this order?"),
                    function () {
                        frm.set_value("status", "Cancelled");
                        frm.save();
                    }
                );
            }, __("Actions")).addClass("btn-danger");
        }

        // Print buttons
        if (!frm.is_new() && frm.doc.status !== "Cancelled") {
            frm.add_custom_button(__("Print KOT"), function () {
                frappe.call({
                    method: "restaurant_management.restaurant_management.api.get_kot_data",
                    args: { order_name: frm.doc.name },
                    callback: function (r) {
                        if (r.message) {
                            let w = window.open();
                            w.document.write(r.message);
                            w.document.close();
                            w.print();
                        }
                    },
                });
            }, __("Print"));

            frm.add_custom_button(__("Print Bill"), function () {
                frappe.call({
                    method: "restaurant_management.restaurant_management.api.get_bill_data",
                    args: { order_name: frm.doc.name },
                    callback: function (r) {
                        if (r.message) {
                            let w = window.open();
                            w.document.write(r.message);
                            w.document.close();
                            w.print();
                        }
                    },
                });
            }, __("Print"));
        }

        // Create Sales Invoice manually
        if (
            frm.doc.status === "Completed" &&
            !frm.doc.sales_invoice &&
            frm.doc.payment_status === "Paid"
        ) {
            frm.add_custom_button(__("Create Sales Invoice"), function () {
                frappe.call({
                    method: "restaurant_management.restaurant_management.api.create_invoice_for_order",
                    args: { order_name: frm.doc.name },
                    callback: function (r) {
                        if (r.message) {
                            frappe.show_alert({
                                message: __("Sales Invoice {0} created", [r.message]),
                                indicator: "green",
                            });
                            frm.reload_doc();
                        }
                    },
                });
            });
        }
    },

    // Auto-calculate on item changes
    items_add: function (frm) {
        calculate_totals(frm);
    },
    items_remove: function (frm) {
        calculate_totals(frm);
    },
});

frappe.ui.form.on("Restaurant Order Item", {
    menu_item: function (frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.menu_item) {
            frappe.call({
                method: "frappe.client.get",
                args: {
                    doctype: "Restaurant Menu Item",
                    name: row.menu_item,
                },
                callback: function (r) {
                    if (r.message) {
                        frappe.model.set_value(cdt, cdn, "item_name", r.message.item_name);
                        frappe.model.set_value(cdt, cdn, "rate", r.message.price);
                        frappe.model.set_value(cdt, cdn, "quantity", row.quantity || 1);
                        calculate_totals(frm);
                    }
                },
            });
        }
    },
    quantity: function (frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        frappe.model.set_value(cdt, cdn, "amount", row.rate * row.quantity);
        calculate_totals(frm);
    },
    rate: function (frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        frappe.model.set_value(cdt, cdn, "amount", row.rate * row.quantity);
        calculate_totals(frm);
    },
});

function calculate_totals(frm) {
    let total_amount = 0;
    let total_qty = 0;

    (frm.doc.items || []).forEach(function (item) {
        item.amount = (item.rate || 0) * (item.quantity || 0);
        total_amount += item.amount;
        total_qty += item.quantity || 0;
    });

    frm.set_value("total_amount", total_amount);
    frm.set_value("total_qty", total_qty);
    frm.refresh_fields();
}

function show_payment_dialog(frm) {
    let d = new frappe.ui.Dialog({
        title: __("Collect Payment"),
        fields: [
            {
                label: __("Total Amount"),
                fieldname: "total_amount",
                fieldtype: "Currency",
                default: frm.doc.total_amount,
                read_only: 1,
            },
            {
                fieldtype: "Column Break",
            },
            {
                label: __("Payment Mode"),
                fieldname: "payment_mode",
                fieldtype: "Select",
                options: "Cash\nCard\nUPI\nOther",
                default: "Cash",
                reqd: 1,
            },
        ],
        primary_action_label: __("Confirm Payment"),
        primary_action: function (values) {
            frappe.call({
                method: "restaurant_management.restaurant_management.api.collect_payment",
                args: {
                    order_name: frm.doc.name,
                    payment_mode: values.payment_mode,
                },
                callback: function (r) {
                    if (r.message && r.message.status === "success") {
                        frappe.show_alert({
                            message: r.message.message,
                            indicator: "green",
                        });
                        d.hide();
                        frm.reload_doc();
                    }
                },
            });
        },
    });
    d.show();
}
