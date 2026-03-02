import frappe

no_cache = 1

def get_context(context):
	table = frappe.form_dict.get("table")
	context.table = table or ""
	context.no_cache = 1
