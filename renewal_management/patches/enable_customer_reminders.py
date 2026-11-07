# Copyright (c) 2026, huda and contributors
# For license information, please see license.txt

"""Turn on 'Send Reminders to Customers' on existing sites."""

import frappe


def execute():
	frappe.db.set_single_value("Renewal Settings", "email_customers", 1)
