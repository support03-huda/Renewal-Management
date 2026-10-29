# Copyright (c) 2026, huda and contributors
# For license information, please see license.txt

"""Email links that close a Renewal without logging in.

The email button opens /renewal_action (a confirm page, so mail scanners that
open links don't trigger anything); its form POSTs here. The per-record
`action_key` in the link is the permission.
"""

import secrets

import frappe
from frappe import _
from frappe.utils import get_url

ACTIONS = {"renewed": _("Mark as Renewed"), "payment_cleared": _("Mark Payment Cleared")}


def action_url(doc, action):
	"""Link for the email button. Creates the record's key on first use."""
	if not doc.action_key:
		doc.action_key = secrets.token_urlsafe(24)
		if not doc.is_new():
			doc.db_set("action_key", doc.action_key, update_modified=False)
	return get_url(f"/renewal_action?name={doc.name}&action={action}&key={doc.action_key}")


def get_verified_doc(name, key):
	stored = frappe.db.get_value("Renewal", name, "action_key") if name else None
	if not stored or not key or not secrets.compare_digest(stored, key):
		return None
	return frappe.get_doc("Renewal", name)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def renewal_action(name=None, key=None, action=None, new_expiry_date=None):
	doc = get_verified_doc(name, key)
	if not doc or action not in ACTIONS:
		return page(_("Link not valid"), _("This link is invalid or has expired."), "red")

	doc.flags.ignore_permissions = True  # the key was checked above
	try:
		if action == "renewed":
			if doc.status in ("Renewed", "Lost"):
				return page(_("Already closed"), _("{0} is already {1}.").format(doc.name, doc.status), "orange")
			next_name = doc.mark_renewed(new_expiry_date)
			doc.add_comment("Info", _("Marked Renewed from the email link"))
			msg = _("{0} - {1} is marked Renewed. Reminders have stopped. The next period is {2}.").format(
				doc.name, doc.product_name, next_name
			)
		else:
			if doc.payment_status != "Pending":
				return page(_("Already closed"), _("Payment for {0} is already {1}.").format(doc.name, doc.payment_status or "-"), "orange")
			doc.mark_payment_cleared()
			doc.add_comment("Info", _("Payment marked Cleared from the email link"))
			msg = _("Payment for {0} - {1} is marked Cleared. Clearance reminders have stopped.").format(doc.name, doc.product_name)
		frappe.db.commit()
	except frappe.ValidationError as e:
		frappe.db.rollback()
		return page(_("Could not update"), str(e), "red")
	return page(_("Done"), msg, "green")


def page(title, message, indicator):
	frappe.respond_as_web_page(title, message, indicator_color=indicator, http_status_code=200)
