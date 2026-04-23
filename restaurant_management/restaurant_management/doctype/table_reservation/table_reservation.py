# Copyright (c) 2026, Restaurant Management and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _


class TableReservation(Document):
	def validate(self):
		self.validate_date()
		self.validate_slot_availability()

	def validate_date(self):
		"""Ensure reservation date is today or in the future."""
		if self.reservation_date and str(self.reservation_date) < str(frappe.utils.today()):
			frappe.throw(_("Reservation date cannot be in the past"))

	def validate_slot_availability(self):
		"""Ensure no double-booking for the same table, date, and time slot."""
		if self.status in ["Cancelled", "No Show", "Completed"]:
			return

		existing = frappe.db.get_value(
			"Table Reservation",
			{
				"table": self.table,
				"reservation_date": self.reservation_date,
				"time_slot": self.time_slot,
				"status": ["in", ["Confirmed", "Seated"]],
				"name": ["!=", self.name],
			},
		)

		if existing:
			frappe.throw(
				_("Table {0} is already reserved for {1} on {2}").format(
					self.table_number or self.table, self.time_slot, self.reservation_date
				)
			)

	def on_update(self):
		"""Update table status when reservation is confirmed or seated."""
		today = str(frappe.utils.today())
		if self.reservation_date == today and self.status == "Confirmed":
			frappe.db.set_value("Restaurant Table", self.table, "status", "Reserved")
		elif self.status == "Seated":
			frappe.db.set_value("Restaurant Table", self.table, "status", "Occupied")
		elif self.status in ["Cancelled", "No Show", "Completed"]:
			# Free the table if no other active reservation for today
			other = frappe.db.exists(
				"Table Reservation",
				{
					"table": self.table,
					"reservation_date": today,
					"status": ["in", ["Confirmed", "Seated"]],
					"name": ["!=", self.name],
				},
			)
			if not other:
				frappe.db.set_value("Restaurant Table", self.table, "status", "Available")
