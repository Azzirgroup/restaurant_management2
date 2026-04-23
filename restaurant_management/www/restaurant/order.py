import frappe

no_cache = 1

def get_context(context):
	table = frappe.form_dict.get("table")
	order = frappe.form_dict.get("order")
	context.table = table or ""
	context.existing_order = order or ""
	context.no_cache = 1

