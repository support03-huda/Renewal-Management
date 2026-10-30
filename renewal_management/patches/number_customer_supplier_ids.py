# Copyright (c) 2026, huda and contributors
# For license information, please see license.txt

"""Customer / Supplier IDs were the name itself; give the old records numbered IDs
(CUST-00001, SUP-00001, ...) in creation order. rename_doc also updates the
Renewal links that point at them."""

import frappe
from frappe.model.naming import make_autoname

SERIES = {"Renewal Customer": "CUST-", "Renewal Supplier": "SUP-"}


def execute():
	for doctype, prefix in SERIES.items():
		for name in frappe.get_all(doctype, filters={"name": ["not like", prefix + "%"]}, order_by="creation asc", pluck="name"):
			# make_autoname moves the series counter, so new records continue after these.
			frappe.rename_doc(doctype, name, make_autoname(prefix + ".#####"), force=True, show_alert=False)

	# New fetched field on Renewal: fill it for existing records.
	frappe.db.sql(
		"""update `tabRenewal` r join `tabRenewal Customer` c on c.name = r.customer
		set r.customer_name = c.customer_name"""
	)
