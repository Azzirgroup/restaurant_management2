# Copyright (c) 2026, Restaurant Management and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class RestaurantTable(Document):
	def validate(self):
		if self.status == "Available":
			self.current_order = None

	def clear_table(self):
		"""Clear the table and mark it as available."""
		if self.current_order:
			order = frappe.get_doc("Restaurant Order", self.current_order)
			if order.status == "In Progress":
				order.status = "Completed"
				order.save(ignore_permissions=True)

		self.status = "Available"
		self.current_order = None
		self.save(ignore_permissions=True)
