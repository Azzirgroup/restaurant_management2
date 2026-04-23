# Copyright (c) 2026, Restaurant Management and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, flt, add_days


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	chart = get_chart(data)
	report_summary = get_report_summary(data)

	return columns, data, None, chart, report_summary


def get_columns():
	return [
		{
			"label": _("Date"),
			"fieldname": "date",
			"fieldtype": "Date",
			"width": 120,
		},
		{
			"label": _("Total Orders"),
			"fieldname": "total_orders",
			"fieldtype": "Int",
			"width": 120,
		},
		{
			"label": _("Dine In"),
			"fieldname": "dine_in_count",
			"fieldtype": "Int",
			"width": 100,
		},
		{
			"label": _("Parcel"),
			"fieldname": "parcel_count",
			"fieldtype": "Int",
			"width": 100,
		},
		{
			"label": _("Revenue"),
			"fieldname": "revenue",
			"fieldtype": "Currency",
			"width": 150,
		},
		{
			"label": _("Avg Order Value"),
			"fieldname": "avg_order_value",
			"fieldtype": "Currency",
			"width": 150,
		},
	]


def get_data(filters):
	conditions = get_conditions(filters)

	orders = frappe.db.sql(
		"""
		SELECT
			DATE(order_date) as date,
			COUNT(*) as total_orders,
			SUM(CASE WHEN order_type = 'Dine In' THEN 1 ELSE 0 END) as dine_in_count,
			SUM(CASE WHEN order_type = 'Parcel' THEN 1 ELSE 0 END) as parcel_count,
			SUM(total_amount) as revenue,
			AVG(total_amount) as avg_order_value
		FROM `tabRestaurant Order`
		WHERE status IN ('In Progress', 'Completed')
		{conditions}
		GROUP BY DATE(order_date)
		ORDER BY DATE(order_date) DESC
		""".format(conditions=conditions),
		filters,
		as_dict=1,
	)

	return orders


def get_conditions(filters):
	conditions = ""
	if filters:
		if filters.get("from_date"):
			conditions += " AND DATE(order_date) >= %(from_date)s"
		if filters.get("to_date"):
			conditions += " AND DATE(order_date) <= %(to_date)s"
		if filters.get("order_type"):
			conditions += " AND order_type = %(order_type)s"
	return conditions


def get_chart(data):
	if not data:
		return None

	labels = [str(row.date) for row in data]
	revenue = [flt(row.revenue) for row in data]
	orders = [row.total_orders for row in data]

	# Reverse for chronological order
	labels.reverse()
	revenue.reverse()
	orders.reverse()

	return {
		"data": {
			"labels": labels,
			"datasets": [
				{"name": _("Revenue"), "values": revenue},
				{"name": _("Orders"), "values": orders},
			],
		},
		"type": "bar",
		"colors": ["#F6B17A", "#2D3250"],
		"barOptions": {"stacked": 0},
	}


def get_report_summary(data):
	if not data:
		return []

	total_revenue = sum(flt(row.revenue) for row in data)
	total_orders = sum(row.total_orders for row in data)
	total_dine_in = sum(row.dine_in_count for row in data)
	total_parcel = sum(row.parcel_count for row in data)
	avg_order = total_revenue / total_orders if total_orders else 0

	return [
		{
			"value": total_revenue,
			"indicator": "Green",
			"label": _("Total Revenue"),
			"datatype": "Currency",
		},
		{
			"value": total_orders,
			"indicator": "Blue",
			"label": _("Total Orders"),
			"datatype": "Int",
		},
		{
			"value": total_dine_in,
			"indicator": "Orange",
			"label": _("Dine In"),
			"datatype": "Int",
		},
		{
			"value": total_parcel,
			"indicator": "Blue",
			"label": _("Parcel"),
			"datatype": "Int",
		},
		{
			"value": avg_order,
			"indicator": "Green",
			"label": _("Avg Order Value"),
			"datatype": "Currency",
		},
	]
