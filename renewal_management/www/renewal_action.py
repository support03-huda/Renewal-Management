# Copyright (c) 2026, huda and contributors
# For license information, please see license.txt

import frappe
from frappe.sessions import get_csrf_token

from renewal_management.api import ACTIONS, get_verified_doc

no_cache = 1


def get_context(context):
	args = frappe.form_dict
	context.no_breadcrumbs = True
	context.doc = get_verified_doc(args.get("name"), args.get("key"))
	context.action = args.get("action") if args.get("action") in ACTIONS else None
	context.action_label = ACTIONS.get(context.action)
	context.key = args.get("key")
	context.csrf = get_csrf_token() if frappe.session.user != "Guest" else ""
	context.closed = bool(
		context.doc
		and (
			(context.action == "renewed" and context.doc.status in ("Renewed", "Lost"))
			or (context.action == "payment_cleared" and context.doc.payment_status != "Pending")
		)
	)
	context.title = context.action_label or "Renewal"
