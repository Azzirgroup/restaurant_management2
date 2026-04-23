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

	# Get settings for currency and UPI
	settings = frappe.get_single("Restaurant Settings")
	currency = settings.default_currency_symbol or "₹"
	restaurant_name = settings.restaurant_name or "Restaurant"

	# UPI payment info — only when order is Served and unpaid
	upi_info = None
	if order.status == "Served" and order.payment_status != "Paid" and settings.upi_id:
		upi_link = "upi://pay?pa={upi_id}&pn={name}&am={amount}&cu=INR&tn={note}".format(
			upi_id=settings.upi_id,
			name=(settings.upi_merchant_name or restaurant_name).replace(" ", "%20"),
			amount=order.total_amount,
			note="Order%20{0}".format(order.name),
		)
		upi_info = {
			"upi_id": settings.upi_id,
			"merchant_name": settings.upi_merchant_name or restaurant_name,
			"upi_link": upi_link,
			"amount": order.total_amount,
		}

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
			"table": order.table,
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
		"upi": upi_info,
	}


@frappe.whitelist(allow_guest=True)
def confirm_guest_payment(order_name):
	"""Guest confirms UPI payment — auto-creates Sales Invoice + Payment Entry."""
	order = frappe.get_doc("Restaurant Order", order_name)

	if order.payment_status == "Paid":
		return {"status": "already_paid", "message": _("Payment already recorded")}

	# Import the helper from api.py to reuse auto invoice + payment entry logic
	from restaurant_management.restaurant_management.api import collect_payment
	result = collect_payment(order_name, payment_mode="UPI")

	return result


@frappe.whitelist(allow_guest=True)
def add_items_to_order(order_name, items):
	"""Add more items to an existing order. No login required."""
	if isinstance(items, str):
		items = json.loads(items)

	if not items:
		frappe.throw(_("Please add at least one item"))

	order = frappe.get_doc("Restaurant Order", order_name)

	# Only allow adding items if order is still active
	if order.status in ["Completed", "Cancelled"]:
		frappe.throw(_("Cannot add items — order is already {0}").format(order.status))

	for item in items:
		menu_item = frappe.get_doc("Restaurant Menu Item", item.get("menu_item"))
		order.append("items", {
			"menu_item": menu_item.name,
			"item_name": menu_item.item_name,
			"quantity": cint(item.get("quantity", 1)),
			"rate": menu_item.price,
		})

	# Recalculate totals
	order.calculate_totals()

	# Reset to In Progress so kitchen sees the new items
	if order.status in ["Preparing", "Ready"]:
		order.status = "In Progress"

	order.save(ignore_permissions=True)

	return {
		"status": "success",
		"message": _("Items added to {0}").format(order_name),
		"total_amount": order.total_amount,
		"order_status": order.status,
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


# ===========================================================
# TABLE RESERVATION APIs
# ===========================================================

@frappe.whitelist(allow_guest=True)
def get_available_slots(date, guests=2):
	"""Get available time slots for a given date and guest count."""
	guests = cint(guests) or 2

	if str(date) < str(frappe.utils.today()):
		frappe.throw(_("Cannot check availability for past dates"))

	settings = frappe.get_single("Restaurant Settings")

	# All time slots
	all_slots = [
		"11:00 AM - 12:00 PM",
		"12:00 PM - 01:00 PM",
		"01:00 PM - 02:00 PM",
		"02:00 PM - 03:00 PM",
		"03:00 PM - 04:00 PM",
		"05:00 PM - 06:00 PM",
		"06:00 PM - 07:00 PM",
		"07:00 PM - 08:00 PM",
		"08:00 PM - 09:00 PM",
		"09:00 PM - 10:00 PM",
	]

	# Get all tables that fit the guest count
	tables = frappe.get_all(
		"Restaurant Table",
		filters={"seating_capacity": [">=", guests]},
		fields=["name", "table_number", "seating_capacity"],
		order_by="seating_capacity asc, table_number asc",
	)

	if not tables:
		return {
			"restaurant_name": settings.restaurant_name,
			"date": date,
			"guests": guests,
			"slots": [],
			"message": _("No tables available for {0} guests").format(guests),
		}

	table_names = [t.name for t in tables]

	# Get existing reservations for the date
	existing = frappe.get_all(
		"Table Reservation",
		filters={
			"reservation_date": date,
			"status": ["in", ["Confirmed", "Seated"]],
			"table": ["in", table_names],
		},
		fields=["table", "time_slot"],
	)

	# Map: slot → set of booked tables
	booked = {}
	for res in existing:
		booked.setdefault(res.time_slot, set()).add(res.table)

	# Build slots with availability
	result_slots = []
	for slot in all_slots:
		booked_tables = booked.get(slot, set())
		available_tables = [t for t in tables if t.name not in booked_tables]
		if available_tables:
			result_slots.append({
				"time_slot": slot,
				"available_tables": len(available_tables),
				"total_tables": len(tables),
			})

	return {
		"restaurant_name": settings.restaurant_name,
		"date": date,
		"guests": guests,
		"slots": result_slots,
	}


@frappe.whitelist(allow_guest=True)
def book_table(date, time_slot, guests, customer_name, phone, email=None, notes=None):
	"""Book a table — auto-assigns the best-fit available table."""
	guests = cint(guests) or 2

	if str(date) < str(frappe.utils.today()):
		frappe.throw(_("Cannot book for past dates"))

	# Find available tables for this slot
	tables = frappe.get_all(
		"Restaurant Table",
		filters={"seating_capacity": [">=", guests]},
		fields=["name", "table_number", "seating_capacity"],
		order_by="seating_capacity asc, table_number asc",
	)

	# Filter out already-booked tables for this slot
	existing = frappe.get_all(
		"Table Reservation",
		filters={
			"reservation_date": date,
			"time_slot": time_slot,
			"status": ["in", ["Confirmed", "Seated"]],
		},
		pluck="table",
	)

	available = [t for t in tables if t.name not in existing]
	if not available:
		frappe.throw(_("No tables available for {0} guests at {1} on {2}").format(
			guests, time_slot, date
		))

	# Pick the smallest available table (best fit)
	chosen = available[0]

	res = frappe.get_doc({
		"doctype": "Table Reservation",
		"customer_name": customer_name,
		"phone": phone,
		"email": email,
		"guests": guests,
		"reservation_date": date,
		"time_slot": time_slot,
		"table": chosen.name,
		"notes": notes,
		"status": "Confirmed",
	})
	res.insert(ignore_permissions=True)

	settings = frappe.get_single("Restaurant Settings")

	return {
		"status": "success",
		"reservation_id": res.name,
		"table_number": chosen.table_number,
		"seating_capacity": chosen.seating_capacity,
		"date": date,
		"time_slot": time_slot,
		"guests": guests,
		"restaurant_name": settings.restaurant_name,
	}


@frappe.whitelist(allow_guest=True)
def get_reservation_status(reservation_id):
	"""Get reservation details for guest tracking."""
	res = frappe.db.get_value(
		"Table Reservation", reservation_id,
		["name", "customer_name", "phone", "guests", "reservation_date",
		 "time_slot", "table", "table_number", "status", "notes"],
		as_dict=True,
	)

	if not res:
		frappe.throw(_("Reservation not found"))

	settings = frappe.get_single("Restaurant Settings")

	return {
		"reservation": {
			"id": res.name,
			"customer_name": res.customer_name,
			"guests": res.guests,
			"date": str(res.reservation_date),
			"time_slot": res.time_slot,
			"table_number": res.table_number,
			"status": res.status,
			"notes": res.notes,
		},
		"restaurant_name": settings.restaurant_name,
		"address": settings.address,
	}

