app_name = "renewal_management"
app_title = "Renewal Management"
app_publisher = "huda"
app_description = "reminders for renew"
app_email = "support03@softworld.co.in"
app_license = "mit"

# Renewal reminders for Domain / Antivirus / Microsoft 365 / Google Workspace etc.

before_migrate = ["renewal_management.install.create_roles"]
after_install = "renewal_management.install.after_install"
after_migrate = ["renewal_management.install.setup_defaults"]

scheduler_events = {
	"cron": {
		# Every morning at 09:00: renewal, hard call and bill date reminders.
		"0 9 * * *": ["renewal_management.reminders.daily"],
	},
}

app_logo_url = "/assets/renewal_management/images/renewal-logo.svg"
app_home = "/desk/renewal-management"
app_color = "#0F766E"

# App icon on the Desk.
add_to_apps_screen = [
	{
		"name": "renewal_management",
		"logo": app_logo_url,
		"title": "Renewal Management",
		"route": app_home,
		"has_permission": "renewal_management.install.has_app_permission",
	}
]

# Desk users land on the Renewal Management workspace after login.
get_website_user_home_page = "renewal_management.install.get_home_page"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "renewal_management",
# 		"logo": "/assets/renewal_management/logo.png",
# 		"title": "Renewal Management",
# 		"route": "/renewal_management",
# 		"has_permission": "renewal_management.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/renewal_management/css/renewal_management.css"
# app_include_js = "/assets/renewal_management/js/renewal_management.js"

# include js, css files in header of web template
# web_include_css = "/assets/renewal_management/css/renewal_management.css"
# web_include_js = "/assets/renewal_management/js/renewal_management.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "renewal_management/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "renewal_management/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "renewal_management.utils.jinja_methods",
# 	"filters": "renewal_management.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "renewal_management.install.before_install"
# after_install = "renewal_management.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "renewal_management.uninstall.before_uninstall"
# after_uninstall = "renewal_management.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "renewal_management.utils.before_app_install"
# after_app_install = "renewal_management.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "renewal_management.utils.before_app_uninstall"
# after_app_uninstall = "renewal_management.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "renewal_management.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "renewal_management.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["renewal_management.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	# before_validate: Frappe sets user_type from the roles in User.validate.
	"User": {"before_validate": "renewal_management.install.give_renewal_access"},
}

on_login = "renewal_management.install.give_desk_access_on_login"

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"renewal_management.tasks.all"
# 	],
# 	"daily": [
# 		"renewal_management.tasks.daily"
# 	],
# 	"hourly": [
# 		"renewal_management.tasks.hourly"
# 	],
# 	"weekly": [
# 		"renewal_management.tasks.weekly"
# 	],
# 	"monthly": [
# 		"renewal_management.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "renewal_management.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "renewal_management.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "renewal_management.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "renewal_management.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["renewal_management.utils.before_request"]
# after_request = ["renewal_management.utils.after_request"]

# Job Events
# ----------
# before_job = ["renewal_management.utils.before_job"]
# after_job = ["renewal_management.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"renewal_management.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

