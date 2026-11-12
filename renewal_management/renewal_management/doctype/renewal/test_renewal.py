# Copyright (c) 2026, huda and contributors
# For license information, please see license.txt

"""Tests for the daily reminders: customer emails, the team's daily summary, hard calls, bill dates.

Nothing is really emailed (frappe.sendmail is captured) and the job's per-record commits are
disabled, so all test data is rolled back.

Run:  bench --site <site> run-tests --app renewal_management
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, change_settings
from frappe.utils import add_days, add_months, getdate, today

from renewal_management import reminders
from renewal_management.install import setting

IGNORE_TEST_RECORD_DEPENDENCIES = ["Renewal Customer", "Renewal Supplier", "Renewal Product Type", "User"]

TEAM = ["team1@example.com", "team2@example.com"]
CUSTOMER_EMAIL = "customer@example.com"


def settings(**overrides):
	values = {"send_emails": 1, "email_customers": 1, "notify_emails": ", ".join(TEAM)}
	values.update(overrides)
	return change_settings("Renewal Settings", values)


def make_renewal(days_left, email=None, **extra):
	"""An open renewal expiring `days_left` days from today (reminders start 30 days before, hard call 7)."""
	customer = frappe.get_doc(
		{
			"doctype": "Renewal Customer",
			"customer_name": "_Test Customer " + frappe.generate_hash(length=8),
			"email": email,
		}
	).insert()
	expiry = add_days(today(), days_left)
	return frappe.get_doc(
		{
			"doctype": "Renewal",
			"customer": customer.name,
			"customer_email": email,
			"product_type": "Domain",
			"product_name": "_test-" + frappe.generate_hash(length=8) + ".com",
			"billing_cycle": "Annually",
			"start_date": add_months(expiry, -12),  # default is today, which is after a past expiry
			"expiry_date": expiry,
			"remind_before_days": 30,
			"hard_call_before_days": 7,
			"follow_up_every": "Every Week",
			**extra,
		}
	).insert()


class TestRenewalReminders(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Renewal Product Type", "Domain"):
			frappe.get_doc({"doctype": "Renewal Product Type", "product_type_name": "Domain"}).insert()

	def setUp(self):
		self.sent = []
		mail = patch("frappe.sendmail", side_effect=lambda **kwargs: self.sent.append(kwargs))
		# daily() commits after each record; keep everything inside the test transaction.
		commit = patch.object(frappe.db, "commit")
		for p in (mail, commit):
			p.start()
			self.addCleanup(p.stop)

	# ------------------------------------------------------------ helpers

	def mails_for(self, doc):
		return [m for m in self.sent if m.get("reference_name") == doc.name]

	def summaries(self):
		return [m for m in self.sent if not m.get("reference_doctype")]

	def summary(self):
		found = self.summaries()
		self.assertEqual(len(found), 1, "exactly one summary email per run")
		return found[0]

	# ------------------------------------------------------------ customer emails

	def test_customer_with_email_gets_reminder(self):
		with settings():
			doc = make_renewal(20, email=CUSTOMER_EMAIL)
			reminders.daily()

		mails = self.mails_for(doc)
		self.assertEqual(len(mails), 1)
		self.assertEqual(mails[0]["recipients"], [CUSTOMER_EMAIL])
		self.assertIn("Renewal reminder", mails[0]["subject"])

		doc.reload()
		self.assertEqual(doc.reminder_log[-1].sent_to, CUSTOMER_EMAIL)
		self.assertEqual(getdate(doc.next_reminder_on), getdate(add_days(today(), 7)))

	def test_customer_email_hides_internal_details(self):
		with settings():
			doc = make_renewal(20, email=CUSTOMER_EMAIL, amount=999, bill_date=add_days(today(), 10))
			reminders.daily()

		message = self.mails_for(doc)[0]["message"]
		for internal in ("Supplier", "Amount", "Bill Date", "Mark as Renewed", "renewal_action", doc.name):
			self.assertNotIn(internal, message)

	def test_expired_customer_email_says_expired(self):
		with settings():
			doc = make_renewal(-3, email=CUSTOMER_EMAIL)
			reminders.daily()

		self.assertIn("expired", self.mails_for(doc)[0]["subject"])

	def test_no_customer_email_means_no_record_email(self):
		with settings():
			doc = make_renewal(20)
			reminders.daily()

		self.assertEqual(self.mails_for(doc), [])
		message = self.summary()["message"]
		self.assertIn(doc.customer_name, message)
		self.assertIn("no email", message)

	def test_customer_emails_switched_off(self):
		with settings(email_customers=0):
			doc = make_renewal(20, email=CUSTOMER_EMAIL)
			reminders.daily()

		self.assertEqual(self.mails_for(doc), [])
		self.assertIn(doc.customer_name, self.summary()["message"])

	def test_reminder_not_repeated_on_same_day(self):
		with settings():
			doc = make_renewal(20, email=CUSTOMER_EMAIL)
			reminders.daily()
			reminders.daily()

		self.assertEqual(len(self.mails_for(doc)), 1)

	def test_not_due_yet_sends_nothing(self):
		with settings():
			doc = make_renewal(200, email=CUSTOMER_EMAIL)
			reminders.daily()

		self.assertEqual(self.mails_for(doc), [])
		self.assertNotIn(doc.customer_name, self.summary()["message"])

	def test_all_emails_switched_off(self):
		with settings(send_emails=0):
			doc = make_renewal(20, email=CUSTOMER_EMAIL)
			reminders.daily()

		self.assertEqual(self.sent, [])
		doc.reload()
		self.assertEqual(doc.reminder_log[-1].note, "Emails are off in Renewal Settings")

	# ------------------------------------------------------------ daily summary

	def test_one_summary_to_the_team(self):
		with settings():
			make_renewal(-3)
			make_renewal(3, email=CUSTOMER_EMAIL)
			make_renewal(20)
			reminders.daily()

		summary = self.summary()
		self.assertEqual(summary["recipients"], TEAM)
		self.assertTrue(summary["subject"].startswith("Renewal summary"))

	def test_summary_groups(self):
		with settings():
			expired = make_renewal(-3)
			call_now = make_renewal(3)
			due_soon = make_renewal(20)
			far = make_renewal(200)
			lost = make_renewal(-5)
			lost.mark_lost("test")
			reminders.daily()

		message = self.summary()["message"]
		# Green, then yellow, then red.
		order = [
			message.index("Due Soon ("),
			message.index(due_soon.customer_name),
			message.index("Call Now ("),
			message.index(call_now.customer_name),
			message.index("Expired ("),
			message.index(expired.customer_name),
		]
		self.assertEqual(order, sorted(order))
		self.assertNotIn(far.customer_name, message)
		self.assertNotIn(lost.customer_name, message)

	def test_summary_has_renewed_link(self):
		with settings():
			doc = make_renewal(20)
			reminders.daily()

		doc.reload()
		self.assertTrue(doc.action_key)
		self.assertIn(doc.action_key, self.summary()["message"])

	def test_summary_notes_customer_emailed(self):
		with settings():
			doc = make_renewal(20, email=CUSTOMER_EMAIL)
			reminders.daily()

		message = self.summary()["message"]
		self.assertIn("Customer emailed", message)
		self.assertIn(doc.customer_name, message)

	def test_empty_summary_text(self):
		groups = [("Due Soon", reminders.GREEN, []), ("Call Now", reminders.YELLOW, []), ("Expired", reminders.RED, [])]
		self.assertIn("Nothing is due", reminders.summary_body(groups, {}, getdate()))

	def test_no_summary_without_team_emails(self):
		with settings(notify_emails=""):
			make_renewal(20)
			reminders.daily()

		self.assertEqual(self.summaries(), [])

	# ------------------------------------------------------------ hard call and bill date

	def test_hard_call_creates_todo_without_email(self):
		with settings():
			doc = make_renewal(3)
			reminders.daily()

		doc.reload()
		self.assertTrue(doc.hard_call_todo)
		self.assertEqual(frappe.db.get_value("ToDo", doc.hard_call_todo, "reference_name"), doc.name)
		self.assertEqual(self.mails_for(doc), [])
		self.assertIn("Hard call ToDo created", self.summary()["message"])

	def test_bill_date_flagged_in_summary(self):
		with settings():
			doc = make_renewal(20, bill_date=today())
			reminders.daily()

		doc.reload()
		self.assertTrue(doc.bill_reminder_sent)
		self.assertEqual(self.mails_for(doc), [])
		self.assertIn("Raise bill today", self.summary()["message"])

	# ------------------------------------------------------------ Send Reminder Now

	def test_manual_reminder_goes_to_customer(self):
		with settings():
			doc = make_renewal(20, email=CUSTOMER_EMAIL)
			sent_to = doc.send_reminder_now()

		self.assertEqual(sent_to, [CUSTOMER_EMAIL])

	def test_manual_reminder_without_customer_email_goes_to_team(self):
		with settings():
			doc = make_renewal(20)
			sent_to = doc.send_reminder_now()

		self.assertEqual(sent_to, TEAM)
		self.assertIn("Mark as Renewed", self.mails_for(doc)[0]["message"])

	# ------------------------------------------------------------ login safety

	def test_setting_with_missing_field_does_not_break_login(self):
		self.assertIsNone(setting("field_that_does_not_exist"))
		setting("open_dashboard_on_login")  # must not raise
