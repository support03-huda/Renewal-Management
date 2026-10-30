# Copyright (c) 2026, huda and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, add_months, date_diff, getdate, today

# Months added to the expiry when the record is renewed.
CYCLE_MONTHS = {"Monthly": 1, "Quarterly": 3, "Half-Yearly": 6, "Annually": 12}

# Status left alone by the daily job: the record is closed.
CLOSED = ("Lost",)


class Renewal(Document):
	def before_insert(self):
		# Blank reminder settings take the defaults from Renewal Settings.
		settings = frappe.get_cached_doc("Renewal Settings")
		for field, default in (
			("remind_before_days", "default_remind_before_days"),
			("follow_up_every", "default_follow_up_every"),
			("hard_call_before_days", "default_hard_call_before_days"),
		):
			if self.get(field) in (None, "") and settings.get(default) not in (None, ""):
				self.set(field, settings.get(default))
		if not self.assigned_to and frappe.session.user not in ("Administrator", "Guest"):
			self.assigned_to = frappe.session.user

	def validate(self):
		if not self.product_name:
			self.product_name = self.product_type
		if not self.expiry_date and self.start_date and CYCLE_MONTHS.get(self.billing_cycle):
			self.expiry_date = add_months(self.start_date, CYCLE_MONTHS[self.billing_cycle])
		if not self.expiry_date:
			frappe.throw(_("Enter the Expiry Date (or a Renewal Date to calculate it)"))
		if self.start_date and getdate(self.start_date) > getdate(self.expiry_date):
			frappe.throw(_("Renewal Date cannot be after Expiry Date"))
		self.reminder_start_date = add_days(self.expiry_date, -(self.remind_before_days or 0))
		self.hard_call_date = add_days(self.expiry_date, -(self.hard_call_before_days or 0))
		# A changed expiry restarts the reminder schedule.
		if self.has_value_changed("expiry_date") or self.has_value_changed("remind_before_days"):
			self.next_reminder_on = None
		self.refresh_status()

	def refresh_status(self):
		"""Set days_left and the open status (Active / Due / Expired) from today's date."""
		self.days_left = date_diff(self.expiry_date, today())
		if self.status in CLOSED:
			return
		if self.days_left < 0:
			self.status = "Expired"
		elif getdate(today()) >= getdate(self.reminder_start_date):
			self.status = "Due"
		else:
			self.status = "Active"

	@frappe.whitelist()
	def mark_renewed(self, new_expiry_date=None, renewed_on=None):
		"""Renew this same record: move the expiry one billing cycle ahead and log it in Renewal History."""
		if self.status in CLOSED:
			frappe.throw(_("This renewal is {0}").format(self.status))
		if self.billing_cycle == "Custom" and not new_expiry_date:
			frappe.throw(_("Enter the new expiry date for a Custom billing cycle"))

		old_expiry = getdate(self.expiry_date)
		new_expiry = getdate(new_expiry_date) if new_expiry_date else getdate(add_months(old_expiry, CYCLE_MONTHS[self.billing_cycle]))
		if new_expiry <= old_expiry:
			frappe.throw(_("New expiry date must be after {0}").format(frappe.format(old_expiry, "Date")))

		self.renewed_on = renewed_on or today()
		self.append(
			"renewal_history",
			{"renewed_on": self.renewed_on, "old_expiry_date": old_expiry, "new_expiry_date": new_expiry, "amount": self.amount},
		)
		if self.bill_date:
			# Keep the bill date the same distance before expiry as last time.
			self.bill_date = add_days(new_expiry, -date_diff(old_expiry, self.bill_date))
		self.start_date = old_expiry
		self.expiry_date = new_expiry

		# Reminders start over for the new expiry.
		self.close_hard_call_todo()
		self.hard_call_todo = None
		self.bill_reminder_sent = 0
		self.last_reminder_on = None
		self.next_reminder_on = None
		self.action_key = None  # links in old reminder emails stop working
		self.save()
		return self.expiry_date

	@frappe.whitelist()
	def mark_lost(self, reason=None):
		"""Close as Lost. Reminders stop."""
		if self.status in CLOSED:
			frappe.throw(_("This renewal is already {0}").format(self.status))
		self.status = "Lost"
		self.lost_reason = reason
		self.close_hard_call_todo()
		self.save()

	@frappe.whitelist()
	def send_reminder_now(self):
		from renewal_management.reminders import send_reminder

		sent_to = send_reminder(self, "Manual")
		self.save()
		return sent_to

	def close_hard_call_todo(self):
		if self.hard_call_todo and frappe.db.get_value("ToDo", self.hard_call_todo, "status") == "Open":
			frappe.db.set_value("ToDo", self.hard_call_todo, "status", "Closed")
