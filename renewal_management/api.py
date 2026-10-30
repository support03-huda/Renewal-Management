# Copyright (c) 2026, huda and contributors
# For license information, please see license.txt

"""Email link that marks a Renewal as renewed without logging in.

The email button opens /renewal_action (a confirm page, so mail scanners that
open links don't trigger anything); its form POSTs here. The per-record
`action_key` in the link is the permission.
"""

import secrets

import frappe
from frappe import _
from frappe.utils import get_url

ACTIONS = {"renewed": _("Mark as Renewed")}


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
	if doc.status == "Lost":
		return page(_("Already closed"), _("{0} is marked Lost.").format(doc.name), "orange")
	try:
		new_expiry = doc.mark_renewed(new_expiry_date)
		doc.add_comment("Info", _("Marked Renewed from the email link"))
		msg = _("{0} - {1} is renewed. New expiry date: {2}. Reminders will start again before it.").format(
			doc.name, doc.product_name, frappe.format(new_expiry, "Date")
		)
		frappe.db.commit()
	except frappe.ValidationError as e:
		frappe.db.rollback()
		return page(_("Could not update"), str(e), "red")
	return page(_("Done"), msg, "green")


def page(title, message, indicator):
	frappe.respond_as_web_page(title, message, indicator_color=indicator, http_status_code=200)
