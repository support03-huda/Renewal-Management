# Copyright (c) 2026, huda and contributors
# For license information, please see license.txt

"""Daily renewal reminders.

Per open Renewal (Active / Due / Expired), every morning:
  - days_left and status are refreshed;
  - from `reminder_start_date` (expiry - remind_before_days) a reminder goes to the
    CUSTOMER (when a customer email is entered), then repeats every day / week / month
    until the record is marked Renewed or Lost;
  - from `hard_call_date` a ToDo to phone the customer is created once for `assigned_to`;
  - on `bill_date` the bill is flagged.
The internal team gets no per-record emails: one summary of everything due goes to
Renewal Settings > Send Daily Summary To.
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_months, format_date, fmt_money, get_url_to_form, getdate, now, today

from renewal_management.api import ACTIONS, action_url

FOLLOW_UP_DAYS = {"Every Day": 1, "Every Week": 7}

# Email colours: red = expired, yellow = few days left (hard call), green = due soon.
RED, YELLOW, GREEN = "#DC2626", "#CA8A04", "#16A34A"
PALETTE = {
	RED: {"stripe": "#DC2626", "text": "#B91C1C", "tint": "#FEF2F2", "border": "#FECACA", "button": "#DC2626", "button_text": "#FFFFFF"},
	YELLOW: {"stripe": "#EAB308", "text": "#A16207", "tint": "#FEFCE8", "border": "#FDE68A", "button": "#FACC15", "button_text": "#422006"},
	GREEN: {"stripe": "#16A34A", "text": "#15803D", "tint": "#F0FDF4", "border": "#BBF7D0", "button": "#16A34A", "button_text": "#FFFFFF"},
}
OPEN = ["Active", "Due", "Expired"]


def daily():
	events = {}
	for name in frappe.get_all("Renewal", filters={"status": ["in", OPEN]}, pluck="name"):
		run_safely(process_open, name, events)
	try:
		send_summary(events)
	except Exception:
		frappe.log_error(title="Renewal daily summary failed")


def run_safely(fn, name, events):
	# One bad record must not stop the reminders for the rest.
	try:
		frappe.db.savepoint("renewal_reminder")
		fn(frappe.get_doc("Renewal", name), events)
		frappe.db.commit()
	except Exception:
		# Undo only this record, not everything else in the transaction.
		frappe.db.rollback(save_point="renewal_reminder")
		events.pop(name, None)
		frappe.log_error(title=f"Renewal reminder failed: {name}")


def process_open(doc, events):
	today_ = getdate(today())
	notes = []
	doc.refresh_status()

	if not doc.next_reminder_on and today_ >= getdate(doc.reminder_start_date):
		doc.next_reminder_on = today_
	if doc.next_reminder_on and today_ >= getdate(doc.next_reminder_on):
		if send_reminder(doc, "Renewal"):
			notes.append(_("Customer emailed"))
		doc.next_reminder_on = next_follow_up(today_, doc.follow_up_every)

	if not doc.hard_call_todo and doc.hard_call_date and today_ >= getdate(doc.hard_call_date):
		create_hard_call(doc)
		notes.append(_("Hard call ToDo created"))

	if doc.bill_date and not doc.bill_reminder_sent and today_ >= getdate(doc.bill_date):
		log(doc, "Bill Date", [])
		doc.bill_reminder_sent = 1
		notes.append(_("Raise bill today"))

	if notes:
		events[doc.name] = notes

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


def internal_emails():
	return list(dict.fromkeys(split_emails(settings().notify_emails)))


def subject_line(doc):
	return f"{doc.product_name} ({doc.product_type}) - {doc.customer_name or doc.customer}"


def send_reminder(doc, kind):
	"""Email the customer (if an email is entered) and log it on the doc.

	A manual reminder for a record with no customer email goes to the internal team instead.
	Returns the recipients, or [] if nothing was sent.
	"""
	expired = doc.days_left is not None and doc.days_left < 0
	if doc.customer_email and settings().get("email_customers"):
		recipients = [doc.customer_email]
		if expired:
			subject = _("{0} expired on {1}").format(doc.product_name, format_date(doc.expiry_date))
			intro = _("Your {0} expired on {1}. Please reply to this email or call us to renew it.").format(
				doc.product_name, format_date(doc.expiry_date)
			)
		else:
			subject = _("Renewal reminder: {0} expires on {1}").format(doc.product_name, format_date(doc.expiry_date))
			intro = _("Your {0} expires on {1} ({2} days left). Please reply to this email or call us to renew it.").format(
				doc.product_name, format_date(doc.expiry_date), doc.days_left
			)
		message = body(doc, intro, action=None, customer=True)
	elif kind == "Manual":
		recipients = internal_emails()
		if expired:
			subject = _("Expired: {0}").format(subject_line(doc))
			intro = _("This expired on {0} ({1} days ago) and is not renewed yet.").format(
				format_date(doc.expiry_date), -doc.days_left
			)
		else:
			subject = _("Renewal due on {0}: {1}").format(format_date(doc.expiry_date), subject_line(doc))
			intro = _("This is due for renewal on {0} ({1} days left). Contact the customer and renew it.").format(
				format_date(doc.expiry_date), doc.days_left
			)
		message = body(doc, intro, action="renewed")
	else:
		return []

	if not recipients:
		return []
	send(doc, recipients, subject, message)
	log(doc, kind, recipients)
	doc.last_reminder_on = today()
	return recipients


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
	log(doc, "Hard Call", [])


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
	note = ""
	if sent_to and not settings().send_emails:
		note = _("Emails are off in Renewal Settings")
	doc.append(
		"reminder_log",
		{
			"sent_on": now(),
			"reminder_type": kind,
			"sent_to": ", ".join(sent_to) if sent_to else "",
			"note": note,
		},
	)


# ---------------------------------------------------------------- daily summary


def send_summary(events):
	"""One email a day to the internal team: everything whose reminder window has started."""
	recipients = internal_emails()
	if not recipients or not settings().send_emails:
		return
	today_ = getdate(today())
	rows = frappe.get_all(
		"Renewal",
		filters={"status": ["in", OPEN]},
		fields=[
			"name",
			"customer",
			"customer_name",
			"customer_email",
			"mobile",
			"product_name",
			"product_type",
			"expiry_date",
			"days_left",
			"reminder_start_date",
			"hard_call_date",
		],
		order_by="days_left asc, expiry_date asc",
	)
	rows = [r for r in rows if r.name in events or (r.reminder_start_date and getdate(r.reminder_start_date) <= today_)]

	expired = [r for r in rows if (r.days_left or 0) < 0]
	call_now = [
		r for r in rows if (r.days_left or 0) >= 0 and r.hard_call_date and getdate(r.hard_call_date) <= today_
	]
	shown = {r.name for r in expired + call_now}
	groups = [
		(_("Expired"), RED, expired),
		(_("Call Now"), YELLOW, call_now),
		(_("Due Soon"), GREEN, [r for r in rows if r.name not in shown]),
	]

	counts = ", ".join(f"{len(items)} {label.lower()}" for label, _colour, items in groups if items)
	subject = _("Renewal summary {0}: {1}").format(format_date(today_), counts or _("nothing due"))
	frappe.sendmail(
		recipients=recipients,
		sender=settings().sender_email or None,
		subject=subject,
		message=summary_body(groups, events, today_),
	)


def days_text(left):
	if left < 0:
		return _("1 day ago") if left == -1 else _("{0} days ago").format(-left)
	if left == 0:
		return _("Expires today")
	return _("1 day left") if left == 1 else _("{0} days left").format(left)


def summary_card(r, colour, notes):
	"""One renewal in the summary: details on the left, days badge and button on the right."""
	esc = frappe.utils.escape_html
	p = PALETTE[colour]
	contact = [_("Expiry {0}").format(format_date(r.expiry_date))]
	if r.mobile:
		contact.append("&#9742; " + esc(r.mobile))
	contact.append(esc(r.customer_email) if r.customer_email else f'<i style="color:#9CA3AF">{_("no email")}</i>')
	note = ""
	if notes:
		note = "".join(
			f'<span style="display:inline-block;background:#F3F4F6;color:#374151;font-size:11px;font-weight:600;'
			f'padding:3px 8px;border-radius:4px;margin:8px 6px 0 0">{esc(str(n))}</span>'
			for n in notes
		)
	link = action_url(frappe.get_doc("Renewal", r.name), "renewed")
	return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;margin:0 0 10px 0;background:#ffffff;border:1px solid {p["border"]};border-left:5px solid {p["stripe"]};border-radius:8px">
 <tr>
  <td style="padding:14px 16px;vertical-align:top">
   <a href="{get_url_to_form("Renewal", r.name)}" style="font-size:15px;font-weight:700;color:#111827;text-decoration:none">{esc(r.customer_name or r.customer or "")}</a>
   <div style="font-size:13px;color:#4B5563;margin-top:3px">{esc(r.product_name or "")} &middot; {esc(r.product_type or "")}</div>
   <div style="font-size:12px;color:#6B7280;margin-top:6px;line-height:1.6">{" &nbsp;&middot;&nbsp; ".join(contact)}</div>
   {note}
  </td>
  <td style="padding:14px 16px;vertical-align:top;text-align:right;white-space:nowrap;width:150px">
   <div style="display:inline-block;background:{p["tint"]};color:{p["text"]};font-size:12px;font-weight:700;padding:5px 12px;border-radius:999px">{days_text(r.days_left or 0)}</div>
   <div style="margin-top:12px"><a href="{link}" style="display:inline-block;background:{p["button"]};color:{p["button_text"]};font-size:12px;font-weight:700;padding:8px 14px;border-radius:6px;text-decoration:none">{ACTIONS["renewed"]}</a></div>
  </td>
 </tr>
</table>"""


def summary_body(groups, events, today_):
	tiles = ""
	sections = ""
	for label, colour, items in groups:
		p = PALETTE[colour]
		tiles += (
			f'<td width="33%" style="padding:0 5px"><div style="background:{p["tint"]};border:1px solid {p["border"]};'
			f'border-radius:10px;padding:14px 8px;text-align:center">'
			f'<div style="font-size:28px;font-weight:800;color:{p["text"]};line-height:1">{len(items)}</div>'
			f'<div style="font-size:12px;font-weight:600;color:{p["text"]};margin-top:6px;letter-spacing:.5px">{label}</div>'
			f"</div></td>"
		)
		if not items:
			continue
		sections += (
			f'<div style="margin:26px 0 10px 0;font-size:13px;font-weight:800;color:{p["text"]};letter-spacing:.5px">'
			f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{p["stripe"]};margin-right:6px"></span>'
			f"{label} ({len(items)})</div>"
		)
		sections += "".join(summary_card(r, colour, events.get(r.name, [])) for r in items)
	if not sections:
		sections = (
			f'<div style="margin-top:24px;padding:24px;text-align:center;color:#15803D;background:#F0FDF4;border-radius:8px;'
			f'font-size:14px;font-weight:600">{_("Nothing is due for renewal today.")}</div>'
		)
	home = frappe.utils.get_url("/desk/renewal-management")
	return f"""
<div style="background:#F3F4F6;padding:28px 12px;font-family:Segoe UI,Helvetica,Arial,sans-serif">
 <table role="presentation" cellpadding="0" cellspacing="0" style="max-width:680px;width:100%;margin:0 auto;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #E5E7EB">
  <tr><td style="background:#111827;padding:22px 26px">
   <div style="color:#9CA3AF;font-size:11px;font-weight:700;letter-spacing:1.5px">{_("DAILY")}</div>
   <div style="color:#ffffff;font-size:22px;font-weight:700;margin-top:4px">{_("Renewal Summary")}</div>
   <div style="color:#D1D5DB;font-size:13px;margin-top:2px">{format_date(today_)}</div>
  </td></tr>
  <tr><td style="padding:20px 21px 0 21px">
   <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{tiles}</tr></table>
  </td></tr>
  <tr><td style="padding:0 26px 10px 26px">{sections}</td></tr>
  <tr><td style="padding:10px 26px 24px 26px;text-align:center">
   <a href="{home}" style="display:inline-block;color:#374151;font-size:13px;font-weight:600;text-decoration:none;border:1px solid #D1D5DB;border-radius:6px;padding:9px 18px">{_("Open Renewal Management")}</a>
  </td></tr>
 </table>
</div>"""


# ---------------------------------------------------------------- single-record email


def header_style(doc):
	"""(colour, label, big number, caption) for the top of the email."""
	left = doc.days_left or 0
	if left < 0:
		return RED, _("EXPIRED"), str(-left), _("days ago")
	if left <= (doc.hard_call_before_days or 7):
		return YELLOW, _("RENEW NOW"), str(left), _("days left")
	return GREEN, _("RENEWAL DUE"), str(left), _("days left")


def body(doc, intro, action="renewed", customer=False):
	"""Email for one renewal. `customer=True` leaves out internal details and desk links."""
	esc = frappe.utils.escape_html
	colour, label, big, caption = header_style(doc)
	rows = [
		(_("Customer"), doc.customer_name or doc.customer, True),
		(_("Product Type"), doc.product_type, False),
		(_("Quantity"), doc.quantity, False),
		(_("Billing Cycle"), doc.billing_cycle, False),
		(_("Expiry Date"), format_date(doc.expiry_date), False),
		(_("Last Renewed On"), format_date(doc.renewed_on) if doc.renewed_on else None, False),
		(_("Bill Date"), format_date(doc.bill_date) if doc.bill_date else None, True),
		(_("Amount"), fmt_money(doc.amount) if doc.amount else None, True),
		(
			_("Supplier"),
			frappe.db.get_value("Renewal Supplier", doc.supplier, "supplier_name") if doc.supplier else None,
			True,
		),
		(_("Mobile"), doc.mobile, True),
		(_("Customer Email"), doc.customer_email, True),
	]
	cells = "".join(
		f'<tr><td style="padding:9px 0;border-bottom:1px solid #EEF0F2;color:#6B7280;font-size:13px;width:40%">{esc(str(k))}</td>'
		f'<td style="padding:9px 0;border-bottom:1px solid #EEF0F2;color:#111827;font-size:14px;font-weight:600">{esc(str(v))}</td></tr>'
		for k, v, internal in rows
		if v not in (None, "") and not (customer and internal)
	)
	buttons = ""
	if not customer:
		if action:
			buttons += (
				f'<a href="{action_url(doc, action)}" style="display:inline-block;background:{colour};color:#ffffff;'
				f'padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;margin:0 8px 8px 0">'
				f"✔ {ACTIONS[action]}</a>"
			)
		buttons += (
			f'<a href="{get_url_to_form("Renewal", doc.name)}" style="display:inline-block;background:#ffffff;color:#374151;'
			f'padding:11px 20px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;border:1px solid #D1D5DB;margin:0 0 8px 0">'
			f"{_('Open {0}').format(doc.name)}</a>"
			f'<div style="color:#9CA3AF;font-size:12px;margin-top:6px">'
			f'{_("Click once it is renewed: the expiry moves to the next period and these reminders stop.")}</div>'
		)
		buttons = f'<tr><td style="padding:8px 24px 16px 24px">{buttons}</td></tr>'
	footer = esc(settings().sender_email or "") if customer else f'{_("Renewal Management")} &middot; {esc(doc.name)}'
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
  {buttons}
  <tr><td style="background:#F9FAFB;padding:12px 24px;color:#9CA3AF;font-size:11px;border-top:1px solid #EEF0F2">
   {footer}
  </td></tr>
 </table>
</div>"""
