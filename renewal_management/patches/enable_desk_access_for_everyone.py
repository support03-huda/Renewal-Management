# Copyright (c) 2026, huda and contributors
# For license information, please see license.txt

"""Turn on 'Give Desk Access to Every User' on existing sites and fix users who
are already stuck as Website Users (e.g. invited from a Contact)."""

import frappe

from renewal_management.install import give_existing_users_access


def execute():
	frappe.db.set_single_value("Renewal Settings", "desk_access_for_everyone", 1)
	give_existing_users_access()
