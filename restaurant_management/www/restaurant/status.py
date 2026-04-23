import frappe

no_cache = 1

def get_context(context):
	order = frappe.form_dict.get("order")
	context.order_name = order or ""
	context.no_cache = 1
