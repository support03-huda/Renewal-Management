# Copyright (c) 2026, huda and contributors
# For license information, please see license.txt

"""Daily renewal reminders.

Per open Renewal (Active / Due / Expired), every morning:
  - days_left and status are refreshed;
  - from `reminder_start_date` (expiry - remind_before_days) a reminder goes to the
    internal team, then repeats every day / week / month until the record is marked
    Renewed (the expiry moves ahead and it all starts again) or Lost;
  - from `hard_call_date` (expiry - hard_call_before_days) a ToDo to phone the
    customer is created once for `assigned_to`;
  - on `bill_date` the internal team is told to raise the bill.
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_months, format_date, fmt_money, get_url_to_form, getdate, now, today

from renewal_management.api import ACTIONS, action_url

FOLLOW_UP_DAYS = {"Every Day": 1, "Every Week": 7}


def daily():
	for name in frappe.get_all("Renewal", filters={"status": ["in", ["Active", "Due", "Expired"]]}, pluck="name"):
		run_safely(process_open, name)


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
	if doc.days_left is not None and doc.days_left < 0:
		subject = _("Expired: {0}").format(subject_line(doc))
		intro = _("This expired on {0} ({1} days ago) and is not renewed yet.").format(format_date(doc.expiry_date), -doc.days_left)
	else:
		subject = _("Renewal due on {0}: {1}").format(format_date(doc.expiry_date), subject_line(doc))
		intro = _("This is due for renewal on {0} ({1} days left). Contact the customer and renew it.").format(
			format_date(doc.expiry_date), doc.days_left
		)

	recipients = internal_emails(doc)
	send(doc, recipients, subject, body(doc, intro, action="renewed"))
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


def header_style(doc):
	"""(colour, label, big number, caption) for the top of the email."""
	left = doc.days_left or 0
	if left < 0:
		return "#DC2626", _("EXPIRED"), str(-left), _("days ago")
	if left <= 7:
		return "#EA580C", _("RENEW NOW"), str(left), _("days left")
	return "#0F766E", _("RENEWAL DUE"), str(left), _("days left")


def body(doc, intro, action="renewed"):
	esc = frappe.utils.escape_html
	colour, label, big, caption = header_style(doc)
	rows = [
		(_("Customer"), doc.customer_name or doc.customer),
		(_("Product Type"), doc.product_type),
		(_("Quantity"), doc.quantity),
		(_("Billing Cycle"), doc.billing_cycle),
		(_("Expiry Date"), format_date(doc.expiry_date)),
		(_("Last Renewed On"), format_date(doc.renewed_on) if doc.renewed_on else None),
		(_("Bill Date"), format_date(doc.bill_date) if doc.bill_date else None),
		(_("Amount"), fmt_money(doc.amount) if doc.amount else None),
		(_("Supplier"), frappe.db.get_value("Renewal Supplier", doc.supplier, "supplier_name") if doc.supplier else None),
		(_("Mobile"), doc.mobile),
		(_("Customer Email"), doc.customer_email),
	]
	cells = "".join(
		f'<tr><td style="padding:9px 0;border-bottom:1px solid #EEF0F2;color:#6B7280;font-size:13px;width:40%">{esc(str(k))}</td>'
		f'<td style="padding:9px 0;border-bottom:1px solid #EEF0F2;color:#111827;font-size:14px;font-weight:600">{esc(str(v))}</td></tr>'
		for k, v in rows
		if v not in (None, "")
	)
	button = ""
	if action:
		button = (
			f'<a href="{action_url(doc, action)}" style="display:inline-block;background:{colour};color:#ffffff;'
			f'padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;margin:0 8px 8px 0">'
			f"✔ {ACTIONS[action]}</a>"
		)
	open_btn = (
		f'<a href="{get_url_to_form("Renewal", doc.name)}" style="display:inline-block;background:#ffffff;color:#374151;'
		f'padding:11px 20px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;border:1px solid #D1D5DB;margin:0 0 8px 0">'
		f"{_('Open {0}').format(doc.name)}</a>"
	)
	return f"""
<div style="background:#F3F4F6;padding:24px 12px;font-family:Segoe UI,Arial,sans-serif">
 <table role="presentation" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #E5E7EB">
  <tr><td style="background:{colour};padding:22px 24px;color:#ffffff">
   <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
    <td style="vertical-align:middle">
     <div style="color:#ffffff;font-size:11px;letter-spacing:1.5px;font-weight:700;opacity:.85">{label}</div>
     <div style="color:#ffffff;font-size:20px;font-weight:700;margin-top:6px;line-height:1.3">{esc(doc.product_name or "")}</div>
     <div style="color:#ffffff;font-size:13px;opacity:.9;margin-top:2px">{esc(doc.customer_name or doc.customer or "")}</div>
    </td>
    <td style="vertical-align:middle;text-align:right;white-space:nowrap">
     <div style="color:#ffffff;font-size:34px;font-weight:800;line-height:1">{big}</div>
     <div style="color:#ffffff;font-size:11px;opacity:.85;margin-top:4px">{caption}</div>
    </td>
   </tr></table>
  </td></tr>
  <tr><td style="padding:20px 24px 4px 24px;color:#374151;font-size:14px;line-height:1.5">{intro}</td></tr>
  <tr><td style="padding:4px 24px 12px 24px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{cells}</table></td></tr>
  <tr><td style="padding:8px 24px 16px 24px">{button}{open_btn}
   <div style="color:#9CA3AF;font-size:12px;margin-top:6px">{_("Click once it is renewed: the expiry moves to the next period and these reminders stop.")}</div>
  </td></tr>
  <tr><td style="background:#F9FAFB;padding:12px 24px;color:#9CA3AF;font-size:11px;border-top:1px solid #EEF0F2">
   {_("Renewal Management")} &middot; {esc(doc.name)}
  </td></tr>
 </table>
</div>"""
