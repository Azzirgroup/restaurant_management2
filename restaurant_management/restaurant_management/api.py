# Copyright (c) 2026, Restaurant Management and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import now_datetime, flt, cint, today, getdate, add_days
from datetime import datetime, timedelta
import json


@frappe.whitelist()
def get_menu_items():
	"""Get all available menu items grouped by category."""
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

	return grouped


@frappe.whitelist()
def get_tables():
	"""Get all tables with their current status and occupancy."""
	tables = frappe.get_all(
		"Restaurant Table",
		fields=["name", "table_number", "status", "seating_capacity", "current_order"],
		order_by="table_number asc",
	)

	for table in tables:
		if table.current_order:
			order = frappe.get_doc("Restaurant Order", table.current_order)
			table["order_total"] = order.total_amount
			table["order_items"] = [
				{"item_name": item.item_name, "quantity": item.quantity, "amount": item.amount}
				for item in order.items
			]
			# Occupied seats: use covers field if it exists, else fall back to seating_capacity
			try:
				covers = cint(getattr(order, "covers", None) or 0)
			except Exception:
				covers = 0
			table["occupied_seats"] = covers if covers > 0 else table.seating_capacity
		else:
			table["order_total"] = 0
			table["order_items"] = []
			table["occupied_seats"] = 0

	return tables


@frappe.whitelist()
def create_order(items, order_type, table=None, customer_name=None, notes=None, covers=None):
	"""Create a new restaurant order quickly from the POS page.

	Args:
		items: JSON string — list of {menu_item, quantity}
		order_type: "Dine In" or "Parcel"
		table: Restaurant Table name (for Dine In)
		customer_name: Optional customer name
		notes: Optional special instructions
		covers: Number of guests at the table (Dine In only)
	"""
	if isinstance(items, str):
		items = json.loads(items)

	if not items:
		frappe.throw(_("Please add at least one item to the order"))

	order = frappe.get_doc({
		"doctype": "Restaurant Order",
		"order_type": order_type,
		"table": table if order_type == "Dine In" else None,
		"customer_name": customer_name,
		"notes": notes,
		"order_date": now_datetime(),
	})

	# Store covers (guest count) if the field exists on the doctype
	if covers and order_type == "Dine In":
		try:
			order.covers = cint(covers)
		except Exception:
			pass

	for item in items:
		menu_item = frappe.get_doc("Restaurant Menu Item", item.get("menu_item"))
		order.append("items", {
			"menu_item": menu_item.name,
			"item_name": menu_item.item_name,
			"quantity": cint(item.get("quantity", 1)),
			"rate": menu_item.price,
		})

	order.insert(ignore_permissions=True)
	return order.name


@frappe.whitelist()
def complete_order(order_name):
	"""Mark an order as completed."""
	order = frappe.get_doc("Restaurant Order", order_name)
	order.status = "Completed"
	order.save(ignore_permissions=True)
	return {"status": "success", "message": _("Order {0} completed").format(order_name)}


@frappe.whitelist()
def cancel_order(order_name):
	"""Cancel an order."""
	order = frappe.get_doc("Restaurant Order", order_name)
	order.status = "Cancelled"
	order.save(ignore_permissions=True)
	return {"status": "success", "message": _("Order {0} cancelled").format(order_name)}


@frappe.whitelist()
def update_order_status(order_name, status):
	"""Update order status — used by Kitchen Display and Captain."""
	allowed = ["In Progress", "Preparing", "Ready", "Served", "Completed", "Cancelled"]
	if status not in allowed:
		frappe.throw(_("Invalid status: {0}").format(status))

	order = frappe.get_doc("Restaurant Order", order_name)
	order.status = status
	order.save(ignore_permissions=True)

	status_labels = {
		"Preparing": "🔥 Now preparing",
		"Ready": "✅ Ready to serve",
		"Served": "🍽️ Served",
		"Completed": "✔️ Completed",
		"Cancelled": "❌ Cancelled",
	}
	label = status_labels.get(status, status)
	return {"status": "success", "message": _("{0}: {1}").format(label, order_name)}


@frappe.whitelist()
def collect_payment(order_name, payment_mode="Cash"):
	"""Collect payment for an order — auto-creates Sales Invoice + Payment Entry."""
	order = frappe.get_doc("Restaurant Order", order_name)
	if order.payment_status == "Paid":
		frappe.throw(_("Payment already collected for this order"))

	# 1. Mark order as Paid
	order.payment_status = "Paid"
	order.payment_mode = payment_mode
	order.paid_amount = order.total_amount
	order.save(ignore_permissions=True)

	invoice_name = None
	payment_entry_name = None

	try:
		# 2. Auto-create Sales Invoice
		company = frappe.defaults.get_defaults().get("company")
		if company:
			invoice_name = _create_sales_invoice_for_order(order, company)

			# 3. Auto-create Payment Entry against the invoice
			if invoice_name:
				payment_entry_name = _create_payment_entry(
					invoice_name, order.total_amount, payment_mode, company
				)
	except Exception as e:
		frappe.log_error(
			f"Auto invoice/payment failed for {order_name}: {str(e)}",
			"Restaurant Payment"
		)

	msg = _("Payment of {0} collected via {1}").format(order.total_amount, payment_mode)
	if invoice_name:
		msg += _(" — Invoice {0}").format(invoice_name)
	if payment_entry_name:
		msg += _(" (Paid)")

	return {
		"status": "success",
		"message": msg,
		"invoice": invoice_name,
		"payment_entry": payment_entry_name,
	}


def _create_sales_invoice_for_order(order, company):
	"""Create and submit a Sales Invoice for the order."""
	default_income_account = frappe.get_cached_value(
		"Company", company, "default_income_account"
	)

	# Resolve customer
	customer = _resolve_customer(order.customer_name)
	if not customer:
		return None

	si = frappe.get_doc({
		"doctype": "Sales Invoice",
		"company": company,
		"customer": customer,
		"posting_date": frappe.utils.today(),
		"due_date": frappe.utils.today(),
		"is_pos": 0,
		"update_stock": 0,
	})

	for item in order.items:
		si.append("items", {
			"item_name": item.item_name,
			"description": item.item_name,
			"qty": item.quantity,
			"rate": item.rate,
			"amount": item.amount,
			"income_account": default_income_account,
		})

	si.flags.ignore_mandatory = True
	si.insert(ignore_permissions=True)
	si.submit()

	# Link invoice to order
	order.db_set("sales_invoice", si.name)

	return si.name


def _create_payment_entry(invoice_name, amount, payment_mode, company):
	"""Create and submit a Payment Entry against the Sales Invoice."""
	# Get default accounts
	default_bank = frappe.get_cached_value("Company", company, "default_bank_account")
	default_cash = frappe.get_cached_value("Company", company, "default_cash_account")
	receivable_account = frappe.get_cached_value(
		"Company", company, "default_receivable_account"
	)

	# Choose account based on payment mode
	if payment_mode in ["Card", "UPI"]:
		paid_to = default_bank or default_cash
	else:
		paid_to = default_cash or default_bank

	if not paid_to:
		frappe.log_error("No default bank/cash account set for company", "Restaurant Payment")
		return None

	# Get the invoice to find the customer
	si = frappe.get_doc("Sales Invoice", invoice_name)

	pe = frappe.get_doc({
		"doctype": "Payment Entry",
		"payment_type": "Receive",
		"party_type": "Customer",
		"party": si.customer,
		"company": company,
		"posting_date": frappe.utils.today(),
		"paid_from": receivable_account,
		"paid_to": paid_to,
		"paid_amount": amount,
		"received_amount": amount,
		"reference_no": invoice_name,
		"reference_date": frappe.utils.today(),
		"mode_of_payment": _get_mode_of_payment(payment_mode),
	})

	pe.append("references", {
		"reference_doctype": "Sales Invoice",
		"reference_name": invoice_name,
		"total_amount": amount,
		"outstanding_amount": amount,
		"allocated_amount": amount,
	})

	pe.flags.ignore_mandatory = True
	pe.insert(ignore_permissions=True)
	pe.submit()

	return pe.name


def _get_mode_of_payment(payment_mode):
	"""Map restaurant payment mode to ERPNext Mode of Payment."""
	mode_map = {
		"Cash": "Cash",
		"Card": "Credit Card",
		"UPI": "Bank Draft",
		"Other": "Cash",
	}
	mode = mode_map.get(payment_mode, "Cash")

	# Check if the mode exists, fallback to Cash
	if not frappe.db.exists("Mode of Payment", mode):
		if frappe.db.exists("Mode of Payment", "Cash"):
			return "Cash"
		return None
	return mode


def _resolve_customer(customer_name=None):
	"""Find or create a walk-in customer."""
	if customer_name:
		existing = frappe.db.get_value("Customer", {"customer_name": customer_name})
		if existing:
			return existing

	for walk_in in ["Walk In Customer", "Walk-in Customer", "Guest", "Cash Customer"]:
		if frappe.db.exists("Customer", walk_in):
			return walk_in

	try:
		customer = frappe.get_doc({
			"doctype": "Customer",
			"customer_name": "Walk In Customer",
			"customer_type": "Individual",
			"customer_group": frappe.db.get_single_value("Selling Settings", "customer_group") or "All Customer Groups",
			"territory": frappe.db.get_single_value("Selling Settings", "territory") or "All Territories",
		})
		customer.insert(ignore_permissions=True)
		return customer.name
	except Exception:
		return None



@frappe.whitelist()
def clear_table(table_name):
	"""Clear a table — complete its current order and free it."""
	table = frappe.get_doc("Restaurant Table", table_name)
	table_number = table.table_number

	if table.current_order:
		order = frappe.get_doc("Restaurant Order", table.current_order)
		if order.status == "In Progress":
			# Setting status to Completed triggers on_update → complete_order()
			# which handles freeing the table automatically
			order.status = "Completed"
			order.save(ignore_permissions=True)
		else:
			# Order is already completed/cancelled, just free the table directly
			table.status = "Available"
			table.current_order = None
			table.save(ignore_permissions=True)
	else:
		# No order on table, just ensure it's Available
		table.status = "Available"
		table.save(ignore_permissions=True)

	return {"status": "success", "message": _("Table {0} cleared").format(table_number)}


@frappe.whitelist()
def get_revenue_data(range_type="daily", start_date=None, end_date=None):
	"""Get revenue analytics data.

	Args:
		range_type: "daily", "monthly", "overall", or "custom"
		start_date: Start date for custom range (YYYY-MM-DD)
		end_date: End date for custom range (YYYY-MM-DD)
	"""
	now = now_datetime()

	if range_type == "daily":
		start = getdate(today())
		end = getdate(today())
	elif range_type == "monthly":
		start = getdate(add_days(today(), -30))
		end = getdate(today())
	elif range_type == "overall":
		first_order = frappe.db.get_value(
			"Restaurant Order",
			filters={"status": ["in", ["In Progress", "Completed"]]},
			fieldname="order_date",
			order_by="order_date asc",
		)
		start = getdate(first_order) if first_order else getdate(add_days(today(), -30))
		end = getdate(today())
	elif range_type == "custom" and start_date and end_date:
		start = getdate(start_date)
		end = getdate(end_date)
	else:
		frappe.throw(_("Invalid range type"))

	# Get orders in range
	orders = frappe.get_all(
		"Restaurant Order",
		filters={
			"status": ["in", ["In Progress", "Completed"]],
			"order_date": ["between", [start, add_days(end, 1)]],
		},
		fields=[
			"name", "order_type", "total_amount", "order_date",
			"status", "total_qty"
		],
		order_by="order_date asc",
	)

	total_revenue = sum(flt(o.total_amount) for o in orders)
	total_orders = len(orders)
	avg_order_value = total_revenue / total_orders if total_orders else 0
	dine_in_count = sum(1 for o in orders if o.order_type == "Dine In")
	parcel_count = sum(1 for o in orders if o.order_type == "Parcel")

	# Group revenue by date
	daily_data = {}
	for order in orders:
		date_key = getdate(order.order_date).strftime("%Y-%m-%d")
		if date_key not in daily_data:
			daily_data[date_key] = {"revenue": 0, "orders": 0}
		daily_data[date_key]["revenue"] += flt(order.total_amount)
		daily_data[date_key]["orders"] += 1

	chart_labels = sorted(daily_data.keys())
	chart_data = [daily_data[d]["revenue"] for d in chart_labels]
	peak_revenue = max(chart_data) if chart_data else 0

	revenue_data = []
	for date_key in chart_labels:
		data = daily_data[date_key]
		revenue_data.append({
			"date": date_key,
			"orders": data["orders"],
			"revenue": data["revenue"],
			"avg_value": data["revenue"] / data["orders"] if data["orders"] else 0,
		})

	return {
		"total_revenue": total_revenue,
		"avg_order_value": avg_order_value,
		"total_orders": total_orders,
		"dine_in_count": dine_in_count,
		"parcel_count": parcel_count,
		"peak_revenue": peak_revenue,
		"chart_labels": chart_labels,
		"chart_data": chart_data,
		"revenue_data": revenue_data,
	}


@frappe.whitelist()
def export_revenue_excel(start_date=None, end_date=None):
	"""Export revenue data to Excel file."""
	from frappe.utils.xlsxutils import make_xlsx

	if not start_date:
		start_date = today()
	if not end_date:
		end_date = today()

	orders = frappe.get_all(
		"Restaurant Order",
		filters={
			"status": ["in", ["In Progress", "Completed"]],
			"order_date": ["between", [getdate(start_date), add_days(getdate(end_date), 1)]],
		},
		fields=["name", "order_type", "total_amount", "order_date", "status", "customer_name"],
		order_by="order_date desc",
	)

	data = [["Order ID", "Date", "Time", "Order Type", "Customer", "Amount", "Status"]]
	for order in orders:
		order_dt = order.order_date
		data.append([
			order.name,
			getdate(order_dt).strftime("%Y-%m-%d") if order_dt else "",
			order_dt.strftime("%H:%M:%S") if order_dt else "",
			order.order_type,
			order.customer_name or "Walk In",
			flt(order.total_amount),
			order.status,
		])

	xlsx_file = make_xlsx(data, "Revenue Report")

	frappe.response["filename"] = f"revenue_report_{start_date}_to_{end_date}.xlsx"
	frappe.response["filecontent"] = xlsx_file.getvalue()
	frappe.response["type"] = "binary"


@frappe.whitelist()
def send_whatsapp_report():
	"""Generate a WhatsApp message URL with today's revenue summary."""
	settings = frappe.get_single("Restaurant Settings")
	data = get_revenue_data("daily")

	message = f"""*Daily Revenue Report - {settings.restaurant_name}*
Date: {today()}

💰 Total Revenue: {settings.default_currency_symbol}{data['total_revenue']:,.2f}
📦 Total Orders: {data['total_orders']}
🍽️ Dine-in: {data['dine_in_count']}
📋 Parcel: {data['parcel_count']}
📊 Avg Order Value: {settings.default_currency_symbol}{data['avg_order_value']:,.2f}

Generated by {settings.restaurant_name}"""

	import urllib.parse
	encoded_message = urllib.parse.quote(message)

	phone = settings.whatsapp_number or ""
	if phone:
		whatsapp_url = f"https://wa.me/{phone}?text={encoded_message}"
	else:
		whatsapp_url = f"https://wa.me/?text={encoded_message}"

	return {"success": True, "whatsapp_url": whatsapp_url, "message": message}


@frappe.whitelist()
def create_invoice_for_order(order_name):
	"""Manually create a Sales Invoice for a completed order."""
	order = frappe.get_doc("Restaurant Order", order_name)
	if order.sales_invoice:
		frappe.throw(_("Sales Invoice already exists for this order"))

	order.create_sales_invoice()
	return order.sales_invoice


@frappe.whitelist()
def get_kot_data(order_name):
	"""Generate KOT (Kitchen Order Ticket) HTML for printing."""
	order = frappe.get_doc("Restaurant Order", order_name)
	settings = frappe.get_single("Restaurant Settings")

	table_info = ""
	if order.order_type == "Dine In" and order.table:
		table = frappe.get_doc("Restaurant Table", order.table)
		table_info = f"Table #{table.table_number}"
	else:
		table_info = "PARCEL"

	items_html = ""
	for item in order.items:
		items_html += f"""
		<tr>
			<td style="padding:6px 12px;border-bottom:1px dashed #ccc;font-size:14px;">{item.item_name}</td>
			<td style="padding:6px 12px;border-bottom:1px dashed #ccc;font-size:14px;text-align:center;font-weight:bold;">{item.quantity}</td>
		</tr>"""

	html = f"""<!DOCTYPE html>
<html>
<head>
	<style>
		body {{ font-family: 'Courier New', monospace; margin: 0; padding: 20px; background: #fff; }}
		.kot-container {{ max-width: 300px; margin: 0 auto; border: 2px dashed #333; padding: 15px; }}
		.kot-header {{ text-align: center; border-bottom: 2px solid #333; padding-bottom: 10px; margin-bottom: 10px; }}
		.kot-header h2 {{ margin: 0; font-size: 18px; letter-spacing: 2px; }}
		.kot-header p {{ margin: 5px 0; font-size: 12px; }}
		.table-info {{ text-align: center; font-size: 20px; font-weight: bold; margin: 10px 0; padding: 8px; background: #333; color: #fff; }}
		table {{ width: 100%; border-collapse: collapse; }}
		th {{ padding: 6px 12px; border-bottom: 2px solid #333; font-size: 12px; text-transform: uppercase; }}
		.kot-footer {{ text-align: center; margin-top: 10px; padding-top: 10px; border-top: 2px dashed #333; font-size: 11px; }}
	</style>
</head>
<body>
	<div class="kot-container">
		<div class="kot-header">
			<h2>🍽️ KOT</h2>
			<p>Kitchen Order Ticket</p>
			<p>Order: {order.name}</p>
		</div>
		<div class="table-info">{table_info}</div>
		<table>
			<thead>
				<tr>
					<th style="text-align:left;">Item</th>
					<th style="text-align:center;">Qty</th>
				</tr>
			</thead>
			<tbody>{items_html}</tbody>
		</table>
		{f'<p style="margin-top:10px;font-style:italic;font-size:12px;">Note: {order.notes}</p>' if order.notes else ''}
		<div class="kot-footer">
			<p>{order.order_date}</p>
			<p>{settings.restaurant_name}</p>
		</div>
	</div>
</body>
</html>"""

	return html


@frappe.whitelist()
def get_bill_data(order_name):
	"""Generate Bill/Receipt HTML for printing."""
	order = frappe.get_doc("Restaurant Order", order_name)
	settings = frappe.get_single("Restaurant Settings")

	table_info = ""
	if order.order_type == "Dine In" and order.table:
		table = frappe.get_doc("Restaurant Table", order.table)
		table_info = f"Table #{table.table_number}"
	else:
		table_info = "Parcel Order"

	items_html = ""
	for idx, item in enumerate(order.items, 1):
		items_html += f"""
		<tr>
			<td style="padding:8px 12px;border-bottom:1px solid #eee;">{idx}</td>
			<td style="padding:8px 12px;border-bottom:1px solid #eee;">{item.item_name}</td>
			<td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:center;">{item.quantity}</td>
			<td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">{settings.default_currency_symbol}{flt(item.rate):,.2f}</td>
			<td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">{settings.default_currency_symbol}{flt(item.amount):,.2f}</td>
		</tr>"""

	html = f"""<!DOCTYPE html>
<html>
<head>
	<style>
		body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
		.bill-container {{ max-width: 500px; margin: 0 auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); padding: 30px; }}
		.bill-header {{ text-align: center; margin-bottom: 20px; padding-bottom: 15px; border-bottom: 2px solid #2D3250; }}
		.bill-header h1 {{ margin: 0; color: #2D3250; font-size: 24px; }}
		.bill-header p {{ margin: 4px 0; color: #666; font-size: 13px; }}
		.bill-meta {{ display: flex; justify-content: space-between; margin-bottom: 20px; padding: 12px; background: #f8f9fa; border-radius: 8px; }}
		.bill-meta span {{ font-size: 13px; color: #555; }}
		table {{ width: 100%; border-collapse: collapse; margin-bottom: 15px; }}
		th {{ padding: 10px 12px; background: #2D3250; color: #fff; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }}
		th:first-child {{ border-radius: 6px 0 0 0; }}
		th:last-child {{ border-radius: 0 6px 0 0; }}
		.total-row {{ background: #f8f9fa; font-weight: bold; }}
		.total-row td {{ padding: 12px; font-size: 16px; border-top: 2px solid #2D3250; }}
		.bill-footer {{ text-align: center; margin-top: 20px; padding-top: 15px; border-top: 1px dashed #ccc; }}
		.bill-footer p {{ margin: 3px 0; color: #888; font-size: 12px; }}
		.print-btn {{ display: inline-block; padding: 10px 25px; background: linear-gradient(135deg, #F6B17A, #E8985E); color: #333; border: none; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 14px; margin-top: 15px; }}
		.print-btn:hover {{ transform: translateY(-2px); box-shadow: 0 4px 15px rgba(246,177,122,0.4); }}
		@media print {{ .no-print {{ display: none; }} body {{ background: #fff; padding: 0; }} .bill-container {{ box-shadow: none; }} }}
	</style>
</head>
<body>
	<div class="bill-container">
		<div class="no-print" style="text-align:right;margin-bottom:15px;">
			<button onclick="window.print()" class="print-btn">🖨️ Print Receipt</button>
		</div>
		<div class="bill-header">
			<h1>{settings.restaurant_name}</h1>
			<p>{settings.address or ''}</p>
			{f'<p>{settings.receipt_header}</p>' if settings.receipt_header else ''}
		</div>
		<div class="bill-meta">
			<span><strong>Invoice:</strong> {order.name}</span>
			<span><strong>Type:</strong> {table_info}</span>
			<span><strong>Date:</strong> {order.order_date}</span>
		</div>
		{f'<p style="margin-bottom:15px;color:#555;">Customer: {order.customer_name}</p>' if order.customer_name else ''}
		<table>
			<thead>
				<tr>
					<th style="text-align:left;">#</th>
					<th style="text-align:left;">Item</th>
					<th style="text-align:center;">Qty</th>
					<th style="text-align:right;">Rate</th>
					<th style="text-align:right;">Amount</th>
				</tr>
			</thead>
			<tbody>
				{items_html}
				<tr class="total-row">
					<td colspan="4" style="text-align:right;">Total:</td>
					<td style="text-align:right;">{settings.default_currency_symbol}{flt(order.total_amount):,.2f}</td>
				</tr>
			</tbody>
		</table>
		<div class="bill-footer">
			<p>{settings.receipt_footer or 'Thank you for dining with us!'}</p>
			<p>Powered by {settings.restaurant_name}</p>
		</div>
	</div>
</body>
</html>"""

	return html


@frappe.whitelist()
def get_kitchen_orders():
	"""Get all active (In Progress) orders for the kitchen display."""
	orders = frappe.get_all(
		"Restaurant Order",
		filters={"status": ["in", ["In Progress", "Preparing"]]},
		fields=["name", "order_type", "table", "order_date", "notes", "total_amount", "status"],
		order_by="order_date asc",
	)

	result = []
	for order in orders:
		# Get order items
		items = frappe.get_all(
			"Restaurant Order Item",
			filters={"parent": order.name},
			fields=["name", "item_name", "quantity", "status"],
			order_by="idx asc",
		)

		# Get table number
		table_number = None
		if order.table:
			table_number = frappe.db.get_value("Restaurant Table", order.table, "table_number")

		result.append({
			"name": order.name,
			"order_type": order.order_type,
			"table": order.table,
			"table_number": table_number,
			"order_date": str(order.order_date),
			"notes": order.notes,
			"total_amount": order.total_amount,
			"status": order.status,
			"items": items,
		})

	return result


@frappe.whitelist()
def update_item_status(item_name, status):
	"""Update the status of an individual item in a Restaurant Order."""
	item = frappe.get_doc("Restaurant Order Item", item_name)
	item.status = status
	item.db_update()

	# If all items are prepared, we could optionally update the main order status as well
	return {"status": "success"}
