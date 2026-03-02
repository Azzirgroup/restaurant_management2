# Copyright (c) 2026, Restaurant Management and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, flt, cint


class RestaurantOrder(Document):
	def validate(self):
		self.calculate_totals()
		self.validate_table()

	def calculate_totals(self):
		"""Calculate item amounts and order totals."""
		total_amount = 0
		total_qty = 0

		for item in self.items:
			item.amount = flt(item.rate) * cint(item.quantity)
			total_amount += item.amount
			total_qty += cint(item.quantity)

		self.total_amount = total_amount
		self.total_qty = total_qty

	def validate_table(self):
		"""Validate table availability for dine-in orders."""
		if self.order_type == "Dine In" and self.table:
			table = frappe.get_doc("Restaurant Table", self.table)
			if table.status == "Occupied" and table.current_order and table.current_order != self.name:
				frappe.throw(
					_("Table {0} is already occupied by order {1}").format(
						table.table_number, table.current_order
					)
				)

	def before_save(self):
		"""Set status to In Progress on first save if Draft."""
		if self.status == "Draft" and not self.is_new():
			pass  # Keep draft until explicitly changed

	def after_insert(self):
		"""After creating a new order, occupy the table if dine-in."""
		if self.order_type == "Dine In" and self.table:
			self.occupy_table()
		# Set status to In Progress
		self.db_set("status", "In Progress")

	def on_update(self):
		"""Handle status changes."""
		if self.status == "Completed":
			self.complete_order()
		elif self.status == "Cancelled":
			self.cancel_order()

	def on_trash(self):
		"""Free up table when order is deleted."""
		if self.order_type == "Dine In" and self.table:
			self.free_table()

	def occupy_table(self):
		"""Mark a table as occupied with this order."""
		table = frappe.get_doc("Restaurant Table", self.table)
		table.status = "Occupied"
		table.current_order = self.name
		table.save(ignore_permissions=True)

	def free_table(self):
		"""Free the table associated with this order."""
		try:
			table = frappe.get_doc("Restaurant Table", self.table)
			if table.current_order == self.name:
				table.status = "Available"
				table.current_order = None
				table.save(ignore_permissions=True)
		except frappe.DoesNotExistError:
			pass

	def complete_order(self):
		"""Complete the order — free table and optionally create Sales Invoice."""
		if self.order_type == "Dine In" and self.table:
			self.free_table()

		# Auto-create Sales Invoice if enabled
		settings = frappe.get_single("Restaurant Settings")
		if settings.auto_create_sales_invoice and not self.sales_invoice:
			self.create_sales_invoice()

	def cancel_order(self):
		"""Cancel the order and free the table."""
		if self.order_type == "Dine In" and self.table:
			self.free_table()

	def create_sales_invoice(self):
		"""Create a Sales Invoice from this restaurant order."""
		try:
			company = frappe.defaults.get_defaults().get("company")
			if not company:
				frappe.log_error(
					"Cannot create Sales Invoice: No default company set",
					"Restaurant Order"
				)
				return

			# Get default income account
			default_income_account = frappe.get_cached_value(
				"Company", company, "default_income_account"
			)

			# Resolve customer — use existing or default walk-in customer
			customer = self._get_or_create_customer(company)
			if not customer:
				frappe.log_error(
					"Cannot create Sales Invoice: No customer found",
					"Restaurant Order"
				)
				return

			si = frappe.get_doc({
				"doctype": "Sales Invoice",
				"company": company,
				"customer": customer,
				"posting_date": frappe.utils.today(),
				"due_date": frappe.utils.today(),
				"is_pos": 0,
				"update_stock": 0,
			})

			for item in self.items:
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

			self.db_set("sales_invoice", si.name)
			frappe.msgprint(
				_("Sales Invoice {0} created successfully").format(
					frappe.utils.get_link_to_form("Sales Invoice", si.name)
				),
				alert=True,
			)

		except Exception as e:
			frappe.log_error(
				f"Failed to create Sales Invoice for {self.name}: {str(e)}",
				"Restaurant Order"
			)
			frappe.msgprint(
				_("Could not create Sales Invoice: {0}").format(str(e)),
				alert=True,
				indicator="orange",
			)

	def _get_or_create_customer(self, company):
		"""Get or create a customer for the invoice."""
		# If a customer name was provided, try to find a matching Customer
		if self.customer_name:
			customer = frappe.db.get_value("Customer", {"customer_name": self.customer_name})
			if customer:
				return customer

		# Try common walk-in customer names
		for walk_in_name in ["Walk In Customer", "Walk-in Customer", "Guest", "Cash Customer"]:
			if frappe.db.exists("Customer", walk_in_name):
				return walk_in_name

		# Create a default walk-in customer if none exists
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

