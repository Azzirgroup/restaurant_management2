# Copyright (c) 2026, Restaurant Management and contributors
# Guest-facing APIs — no login required for QR code self-ordering

import frappe
from frappe import _
from frappe.utils import now_datetime, flt, cint
import json


@frappe.whitelist(allow_guest=True)
def get_guest_menu(table=None):
	"""Get menu items for guest ordering page. No login required."""
	settings = frappe.get_single("Restaurant Settings")

	items = frappe.get_all(
		"Restaurant Menu Item",
		filters={"is_available": 1},
		fields=["name", "item_name", "item_group", "price", "description", "image"],
		order_by="item_group asc, item_name asc",
	)

	grouped = {}
	for item in items:
		group = item.get("item_group", "Uncategorized")
		if group not in grouped:
			grouped[group] = []
		grouped[group].append(item)

	# Validate table if provided
	table_info = None
	if table:
		table_doc = frappe.db.get_value(
			"Restaurant Table", table,
			["name", "table_number", "status", "seating_capacity"],
			as_dict=True,
		)
		if table_doc:
			table_info = table_doc

	return {
		"restaurant_name": settings.restaurant_name,
		"currency_symbol": settings.default_currency_symbol or "₹",
		"address": settings.address,
		"menu": grouped,
		"table": table_info,
	}


@frappe.whitelist(allow_guest=True)
def place_guest_order(items, table=None, customer_name=None, notes=None):
	"""Place an order from the guest QR code page. No login required."""
	if isinstance(items, str):
		items = json.loads(items)

	if not items:
		frappe.throw(_("Please add at least one item"))

	order_type = "Dine In" if table else "Parcel"

	order = frappe.get_doc({
		"doctype": "Restaurant Order",
		"order_type": order_type,
		"table": table if order_type == "Dine In" else None,
		"customer_name": customer_name,
		"notes": notes,
		"order_date": now_datetime(),
	})

	for item in items:
		menu_item = frappe.get_doc("Restaurant Menu Item", item.get("menu_item"))
		order.append("items", {
			"menu_item": menu_item.name,
			"item_name": menu_item.item_name,
			"quantity": cint(item.get("quantity", 1)),
			"rate": menu_item.price,
		})

	order.insert(ignore_permissions=True)

	return {
		"order_name": order.name,
		"total_amount": order.total_amount,
		"status": "In Progress",
	}


@frappe.whitelist(allow_guest=True)
def get_order_status(order_name):
	"""Get live order status for guest tracking page. No login required."""
	order = frappe.db.get_value(
		"Restaurant Order", order_name,
		["name", "status", "order_type", "table", "total_amount",
		 "total_qty", "order_date", "customer_name", "payment_status"],
		as_dict=True,
	)

	if not order:
		frappe.throw(_("Order not found"))

	# Get items
	items = frappe.get_all(
		"Restaurant Order Item",
		filters={"parent": order_name},
		fields=["item_name", "quantity", "rate", "amount"],
		order_by="idx asc",
	)

	# Get table number
	table_number = None
	if order.table:
		table_number = frappe.db.get_value("Restaurant Table", order.table, "table_number")

	# Get settings for currency
	currency = frappe.db.get_single_value("Restaurant Settings", "default_currency_symbol") or "₹"
	restaurant_name = frappe.db.get_single_value("Restaurant Settings", "restaurant_name") or "Restaurant"

	# Status timeline
	status_flow = ["In Progress", "Preparing", "Ready", "Served", "Completed"]
	current_idx = status_flow.index(order.status) if order.status in status_flow else -1

	timeline = []
	for idx, s in enumerate(status_flow):
		state = "completed" if idx < current_idx else ("active" if idx == current_idx else "pending")
		timeline.append({"status": s, "state": state})

	return {
		"order": {
			"name": order.name,
			"status": order.status,
			"order_type": order.order_type,
			"table_number": table_number,
			"total_amount": order.total_amount,
			"total_qty": order.total_qty,
			"order_date": str(order.order_date),
			"customer_name": order.customer_name,
			"payment_status": order.payment_status,
		},
		"items": items,
		"timeline": timeline,
		"currency_symbol": currency,
		"restaurant_name": restaurant_name,
	}


@frappe.whitelist(allow_guest=True)
def get_table_qr_data():
	"""Get all tables with their QR code URLs for printing."""
	tables = frappe.get_all(
		"Restaurant Table",
		fields=["name", "table_number"],
		order_by="table_number asc",
	)

	site_url = frappe.utils.get_url()
	result = []
	for table in tables:
		order_url = f"{site_url}/restaurant/order?table={table.name}"
		result.append({
			"name": table.name,
			"table_number": table.table_number,
			"order_url": order_url,
		})

	return result
