# Copyright (c) 2026, huda and contributors
# For license information, please see license.txt

"""Renewing now updates the same record. Fold the old one-record-per-period chains
(A --next_renewal--> B) into the latest record, keeping each old period as a
Renewal History line, and drop the payment clearance number card."""

import frappe
from frappe import _


def execute():
	frappe.delete_doc("Number Card", "Payment Pending", force=True, ignore_missing=True, ignore_permissions=True)

	if frappe.db.has_column("Renewal", "next_renewal"):
		# Oldest first, so a chain A -> B -> C ends with everything in C.
		for name, next_name in frappe.db.sql(
			"""select name, next_renewal from `tabRenewal`
			where status = 'Renewed' and ifnull(next_renewal, '') != '' order by expiry_date"""
		):
			if frappe.db.exists("Renewal", name) and frappe.db.exists("Renewal", next_name):
				merge(frappe.get_doc("Renewal", name), frappe.get_doc("Renewal", next_name))

	# Anything still Renewed (no next record) goes back to Active / Due / Expired.
	for name in frappe.get_all("Renewal", filters={"status": "Renewed"}, pluck="name"):
		doc = frappe.get_doc("Renewal", name)
		doc.status = "Active"
		doc.flags.ignore_version = True
		doc.save(ignore_permissions=True)


def merge(old, new):
	renewed_on = old.renewed_on or new.start_date
	history = [row.as_dict() for row in old.renewal_history]
	history.append(
		{
			"renewed_on": renewed_on,
			"old_expiry_date": old.expiry_date,
			"new_expiry_date": new.expiry_date,
			"amount": old.amount,
			"note": _("Was {0}").format(old.name),
		}
	)
	history += [row.as_dict() for row in new.renewal_history]
	new.set("renewal_history", [])
	for row in history:
		new.append("renewal_history", {k: row.get(k) for k in ("renewed_on", "old_expiry_date", "new_expiry_date", "amount", "note")})

	if not new.renewed_on:
		new.renewed_on = renewed_on
	if old.remarks and old.remarks not in (new.remarks or ""):
		new.remarks = (new.remarks or "") + "\n\n" + _("Previous period ({0}):").format(old.name) + "\n" + old.remarks
	new.flags.ignore_version = True
	new.save(ignore_permissions=True)

	old.close_hard_call_todo()
	frappe.delete_doc("Renewal", old.name, force=True, ignore_permissions=True)
