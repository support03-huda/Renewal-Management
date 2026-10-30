# Copyright (c) 2026, huda and contributors
# For license information, please see license.txt

"""Daily renewal reminders.

Per open Renewal (Active / Due / Expired), every morning:
  - days_left and status are refreshed;
  - from `reminder_start_date` (expiry - remind_before_days) a reminder goes to the
    customer and the internal team, then repeats every day / week / month until the
    record is marked Renewed or Lost;
  - from `hard_call_date` (expiry - hard_call_before_days) a ToDo to phone the
    customer is created once for `assigned_to`;
  - on `bill_date` the internal team is told to raise the bill.
Per Renewed record with payment Pending, a clearance reminder goes out every
`clearance_every_days` until payment is marked Cleared.
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_months, format_date, fmt_money, get_url_to_form, getdate, now, today

from renewal_management.api import ACTIONS, action_url

FOLLOW_UP_DAYS = {"Every Day": 1, "Every Week": 7}


def daily():
	for name in frappe.get_all("Renewal", filters={"status": ["in", ["Active", "Due", "Expired"]]}, pluck="name"):
		run_safely(process_open, name)
	for name in frappe.get_all("Renewal", filters={"status": "Renewed", "payment_status": "Pending"}, pluck="name"):
		run_safely(process_clearance, name)


def run_safely(fn, name):
	# One bad record must not stop the reminders for the rest.
	try:
		fn(frappe.get_doc("Renewal", name))
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title=f"Renewal reminder failed: {name}")


def process_open(doc):
	today_ = getdate(today())
	doc.refresh_status()

	if not doc.next_reminder_on and today_ >= getdate(doc.reminder_start_date):
		doc.next_reminder_on = today_
	if doc.next_reminder_on and today_ >= getdate(doc.next_reminder_on):
		send_reminder(doc, "Renewal")
		doc.next_reminder_on = next_follow_up(today_, doc.follow_up_every)

	if not doc.hard_call_todo and doc.hard_call_date and today_ >= getdate(doc.hard_call_date):
		create_hard_call(doc)

	if doc.bill_date and not doc.bill_reminder_sent and today_ >= getdate(doc.bill_date):
		send_internal(doc, "Bill Date", _("Raise bill: {0}").format(subject_line(doc)), _("The bill date for this renewal is today."))
		doc.bill_reminder_sent = 1

	# save() also refreshes days_left and status.
	doc.flags.ignore_permissions = True
	doc.flags.ignore_version = True  # days_left changes daily; no Version noise
	doc.save()


def process_clearance(doc):
	if doc.next_clearance_on and getdate(today()) >= getdate(doc.next_clearance_on):
		send_reminder(doc, "Clearance")
		doc.next_clearance_on = add_days(today(), doc.clearance_every_days or 3)
		doc.flags.ignore_permissions = True
		doc.flags.ignore_version = True
		doc.save()


def next_follow_up(from_date, every):
	if every == "Every Month":
		return add_months(from_date, 1)
	return add_days(from_date, FOLLOW_UP_DAYS.get(every, 7))


# ---------------------------------------------------------------- email


def settings():
	return frappe.get_cached_doc("Renewal Settings")


def split_emails(text):
	return [e.strip() for e in (text or "").replace(";", ",").replace("\n", ",").split(",") if e.strip()]


def internal_emails(doc):
	emails = split_emails(settings().notify_emails)
	if doc.assigned_to:
		user_email = frappe.db.get_value("User", doc.assigned_to, "email")
		if user_email:
			emails.append(user_email)
	return list(dict.fromkeys(emails))


def subject_line(doc):
	return f"{doc.product_name} ({doc.product_type}) - {doc.customer_name or doc.customer}"


def send_reminder(doc, kind):
	"""Email the internal team (never the customer) and log it on the doc."""
	if kind == "Clearance":
		subject = _("Payment pending: {0}").format(subject_line(doc))
		intro = _("{0} was renewed on {1} but the payment is not cleared yet. Follow up with the customer.").format(
			doc.customer_name or doc.customer, format_date(doc.renewed_on) if doc.renewed_on else "-"
		)
	elif doc.days_left is not None and doc.days_left < 0:
		subject = _("Expired: {0}").format(subject_line(doc))
		intro = _("This expired on {0} ({1} days ago) and is not renewed yet.").format(format_date(doc.expiry_date), -doc.days_left)
	else:
		subject = _("Renewal due on {0}: {1}").format(format_date(doc.expiry_date), subject_line(doc))
		intro = _("This is due for renewal on {0} ({1} days left). Contact the customer and renew it.").format(
			format_date(doc.expiry_date), doc.days_left
		)

	recipients = internal_emails(doc)
	action = "payment_cleared" if kind == "Clearance" else "renewed"
	send(doc, recipients, subject, body(doc, intro, action=action))
	log(doc, kind, recipients)
	doc.last_reminder_on = today()
	return recipients


def send_internal(doc, kind, subject, intro):
	recipients = internal_emails(doc)
	send(doc, recipients, subject, body(doc, intro))
	log(doc, kind, recipients)


def create_hard_call(doc):
	user = doc.assigned_to or doc.owner
	todo = frappe.get_doc(
		{
			"doctype": "ToDo",
			"allocated_to": user,
			"date": doc.expiry_date,
			"priority": "High",
			"reference_type": "Renewal",
			"reference_name": doc.name,
			"description": _("Hard call: phone {0} ({1}) about renewal of {2}, expiring {3}").format(
				doc.customer_name or doc.customer, doc.mobile or "-", doc.product_name, format_date(doc.expiry_date)
			),
		}
	).insert(ignore_permissions=True)
	doc.hard_call_todo = todo.name
	send_internal(
		doc,
		"Hard Call",
		_("Hard call needed: {0}").format(subject_line(doc)),
		_("Please phone the customer today. The renewal expires on {0} and is not yet confirmed.").format(format_date(doc.expiry_date)),
	)


def send(doc, recipients, subject, message):
	if not recipients or not settings().send_emails:
		return
	frappe.sendmail(
		recipients=recipients,
		sender=settings().sender_email or None,
		subject=subject,
		message=message,
		reference_doctype="Renewal",
		reference_name=doc.name,
	)


def log(doc, kind, sent_to):
	doc.append(
		"reminder_log",
		{
			"sent_on": now(),
			"reminder_type": kind,
			"sent_to": ", ".join(sent_to) if sent_to else "",
			"note": "" if settings().send_emails else _("Emails are off in Renewal Settings"),
		},
	)


def body(doc, intro, action="renewed"):
	rows = [
		(_("Customer"), doc.customer_name or doc.customer),
		(_("Product Type"), doc.product_type),
		(_("Product"), doc.product_name),
		(_("Supplier"), doc.supplier or "-"),
		(_("Quantity"), doc.quantity),
		(_("Billing Cycle"), doc.billing_cycle),
		(_("Expiry Date"), format_date(doc.expiry_date)),
		(_("Days Left"), doc.days_left),
	]
	if doc.amount:
		rows.append((_("Amount"), fmt_money(doc.amount)))
	rows.append((_("Bill Date"), format_date(doc.bill_date) if doc.bill_date else "-"))
	rows.append((_("Mobile"), doc.mobile or "-"))
	rows.append((_("Customer Email"), doc.customer_email or "-"))
	cells = "".join(
		f'<tr><td style="padding:4px 12px 4px 0;color:#666">{frappe.utils.escape_html(str(k))}</td>'
		f"<td style=\"padding:4px 0\"><b>{frappe.utils.escape_html(str(v if v is not None else ''))}</b></td></tr>"
		for k, v in rows
	)
	link = f'<p><a href="{get_url_to_form("Renewal", doc.name)}">{_("Open {0}").format(doc.name)}</a></p>'
	button = ""
	if action:
		button = (
			f'<p style="margin:20px 0"><a href="{action_url(doc, action)}" style="background:#2490EF;color:#fff;'
			f'padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:bold">{ACTIONS[action]}</a></p>'
			f'<p style="color:#888;font-size:12px">{_("Click once renewed / paid to stop these reminders.")}</p>'
		)
	return f"<p>{intro}</p><table>{cells}</table>{button}{link}<p style=\"color:#888;font-size:12px\">{_('Renewal Management')}</p>"
