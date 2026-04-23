import frappe


def after_install():
	"""Create default Restaurant Tables and Settings after app installation."""
	create_default_tables()
	create_default_settings()
	frappe.db.commit()


def create_default_tables():
	"""Create 10 default restaurant tables."""
	for i in range(1, 11):
		table_name = f"TABLE-{i:03d}"
		if not frappe.db.exists("Restaurant Table", table_name):
			doc = frappe.new_doc("Restaurant Table")
			doc.table_number = i
			doc.status = "Available"
			doc.seating_capacity = 4
			doc.insert(ignore_permissions=True)


def create_default_settings():
	"""Create default Restaurant Settings if not exists."""
	if not frappe.db.exists("Restaurant Settings", "Restaurant Settings"):
		doc = frappe.new_doc("Restaurant Settings")
		doc.restaurant_name = "My Restaurant"
		doc.address = "Enter your restaurant address here"
		doc.default_currency_symbol = "KES"
		doc.enable_kot_printing = 1
		doc.auto_create_sales_invoice = 1
		doc.insert(ignore_permissions=True)
