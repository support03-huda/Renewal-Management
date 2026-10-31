# Copyright (c) 2026, huda and contributors
# For license information, please see license.txt

import frappe

ROLES = ("Renewal Manager", "Renewal User")
PRODUCT_TYPES = ("Domain", "Antivirus", "Microsoft 365", "Google Workspace")
SENDER = "support@softworld.co.in"


def create_roles():
	# Before migrate: the DocType permissions need these roles to exist.
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


def after_install():
	create_roles()
	setup_defaults()


def setup_defaults():
	for name in PRODUCT_TYPES:
		if not frappe.db.exists("Renewal Product Type", name):
			frappe.get_doc({"doctype": "Renewal Product Type", "product_type_name": name}).insert(ignore_permissions=True)

	settings = frappe.get_single("Renewal Settings")
	if not settings.sender_email:
		settings.sender_email = SENDER
		settings.notify_emails = SENDER
		settings.send_emails = 1
		settings.default_remind_before_days = 30
		settings.default_follow_up_every = "Every Week"
		settings.default_hard_call_before_days = 7
		settings.save(ignore_permissions=True)

	setup_email_account()
	setup_desktop_icon()
	frappe.db.commit()


def has_app_permission():
	return bool({"System Manager", *ROLES} & set(frappe.get_roles()))


def open_for_everyone():
	return frappe.db.get_single_value("Renewal Settings", "open_dashboard_for_everyone")


def give_renewal_access(user, method=None):
	"""With 'Open This Dashboard on Login for Everyone' on, a user without a Renewal role gets
	Renewal User, so a new user with no roles is a System User and can open the dashboard."""
	if user.name in ("Administrator", "Guest") or not open_for_everyone():
		return
	if not {"System Manager", *ROLES} & {row.role for row in user.roles}:
		user.append("roles", {"role": "Renewal User"})


def give_existing_users_access():
	for name in frappe.get_all("User", filters={"enabled": 1, "name": ["not in", ["Administrator", "Guest"]]}, pluck="name"):
		user = frappe.get_doc("User", name)
		if not {"System Manager", *ROLES} & {row.role for row in user.roles}:
			user.flags.ignore_permissions = True
			user.save()  # give_renewal_access adds the role


def get_home_page(user):
	# Guests and website users keep Frappe's default home page.
	if user != "Guest" and frappe.db.get_value("User", user, "user_type") == "System User" and has_app_permission():
		return "desk/renewal-management"


def setup_desktop_icon():
	try:
		from frappe.desk.doctype.desktop_icon.desktop_icon import create_desktop_icons_from_installed_apps

		create_desktop_icons_from_installed_apps()
	except Exception:
		frappe.log_error(title="Renewal Management: could not create the Desk app icon")


def setup_email_account():
	"""Outgoing Gmail account for support@softworld.co.in.

	The app password is read from the site's site_config.json key
	`renewal_smtp_password`, so it never lives in the app's code.
	"""
	if frappe.db.exists("Email Account", {"email_id": SENDER}):
		return
	password = frappe.conf.get("renewal_smtp_password")
	if not password:
		return
	try:
		frappe.get_doc(
			{
				"doctype": "Email Account",
				"email_account_name": "SoftWorld Support",
				"email_id": SENDER,
				"service": "GMail",
				"smtp_server": "smtp.gmail.com",
				"smtp_port": "587",
				"use_tls": 1,
				"password": password.replace(" ", ""),
				"enable_outgoing": 1,
				"default_outgoing": 1,
				"enable_incoming": 0,
				"always_use_account_email_id_as_sender": 1,
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="Renewal Management: could not create the support@softworld.co.in Email Account")
