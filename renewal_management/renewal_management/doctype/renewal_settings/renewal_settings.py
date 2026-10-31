# Copyright (c) 2026, huda and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class RenewalSettings(Document):
	def on_update(self):
		if self.open_dashboard_for_everyone and self.has_value_changed("open_dashboard_for_everyone"):
			from renewal_management.install import give_existing_users_access

			give_existing_users_access()
