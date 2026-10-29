# Copyright (c) 2026, huda and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, add_months, date_diff, getdate, today

# Months added to the expiry when the next period's record is created.
CYCLE_MONTHS = {"Monthly": 1, "Quarterly": 3, "Half-Yearly": 6, "Annually": 12}

# Status left alone by the daily job: the period is closed.
CLOSED = ("Renewed", "Lost")


class Renewal(Document):
	def before_insert(self):
		# Blank reminder settings take the defaults from Renewal Settings.
		settings = frappe.get_cached_doc("Renewal Settings")
		for field, default in (
			("remind_before_days", "default_remind_before_days"),
			("follow_up_every", "default_follow_up_every"),
			("hard_call_before_days", "default_hard_call_before_days"),
			("clearance_every_days", "default_clearance_every_days"),
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
	def mark_renewed(self, new_expiry_date=None):
		"""Close this period as Renewed and create the next period's record."""
		if self.status in CLOSED:
			frappe.throw(_("This renewal is already {0}").format(self.status))
		if self.billing_cycle == "Custom" and not new_expiry_date:
			frappe.throw(_("Enter the new expiry date for a Custom billing cycle"))

		next_doc = self.make_next_period(new_expiry_date)
		self.status = "Renewed"
		self.renewed_on = today()
		self.next_renewal = next_doc.name
		self.payment_status = "Pending"
		self.next_clearance_on = add_days(today(), self.clearance_every_days or 3)
		self.close_hard_call_todo()
		self.save()
		return next_doc.name

	def make_next_period(self, new_expiry_date=None):
		months = CYCLE_MONTHS.get(self.billing_cycle)
		new_expiry = getdate(new_expiry_date) if new_expiry_date else getdate(add_months(self.expiry_date, months))
		if new_expiry <= getdate(self.expiry_date):
			frappe.throw(_("New expiry date must be after {0}").format(frappe.format(self.expiry_date, "Date")))

		doc = frappe.copy_doc(self)
		doc.start_date = self.expiry_date
		doc.expiry_date = new_expiry
		if self.bill_date:
			# Keep the bill date the same distance before expiry as this period.
			doc.bill_date = add_days(new_expiry, -date_diff(self.expiry_date, self.bill_date))
		doc.status = "Active"
		doc.previous_renewal = self.name
		doc.insert(ignore_permissions=self.flags.ignore_permissions)
		return doc

	@frappe.whitelist()
	def mark_lost(self, reason=None):
		"""Close as Lost. No record is created for the next period."""
		if self.status in CLOSED:
			frappe.throw(_("This renewal is already {0}").format(self.status))
		self.status = "Lost"
		self.lost_reason = reason
		self.close_hard_call_todo()
		self.save()

	@frappe.whitelist()
	def mark_payment_cleared(self):
		self.payment_status = "Cleared"
		self.payment_cleared_on = today()
		self.next_clearance_on = None
		self.save()

	@frappe.whitelist()
	def send_reminder_now(self):
		from renewal_management.reminders import send_reminder

		kind = "Clearance" if self.payment_status == "Pending" else "Manual"
		sent_to = send_reminder(self, kind)
		self.save()
		return sent_to

	def close_hard_call_todo(self):
		if self.hard_call_todo and frappe.db.get_value("ToDo", self.hard_call_todo, "status") == "Open":
			frappe.db.set_value("ToDo", self.hard_call_todo, "status", "Closed")
