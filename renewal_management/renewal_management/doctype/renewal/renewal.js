// Copyright (c) 2026, huda and contributors
// For license information, please see license.txt

frappe.ui.form.on("Renewal", {
	refresh(frm) {
		if (frm.is_new()) {
			if (!frm.doc.expiry_date) set_expiry(frm);
			return;
		}
		const open = ["Active", "Due", "Expired"].includes(frm.doc.status);

		if (open) {
			frm.add_custom_button(__("Renewed"), () => mark_renewed(frm), __("Mark As"));
			frm.add_custom_button(__("Lost"), () => mark_lost(frm), __("Mark As"));
		}
		if (frm.doc.payment_status === "Pending") {
			frm.add_custom_button(__("Payment Cleared"), () =>
				frm.call("mark_payment_cleared").then(() => frm.reload_doc())
			, __("Mark As"));
		}
		if (open || frm.doc.payment_status === "Pending") {
			frm.add_custom_button(__("Send Reminder Now"), () =>
				frm.call("send_reminder_now").then((r) => {
					frappe.show_alert({ message: __("Reminder sent to {0}", [(r.message || []).join(", ")]), indicator: "green" });
					frm.reload_doc();
				})
			);
		}
		if (frm.doc.next_renewal) {
			frm.add_custom_button(__("Next Period"), () => frappe.set_route("Form", "Renewal", frm.doc.next_renewal));
		}

		const colour = { Active: "blue", Due: "orange", Expired: "red", Renewed: "green", Lost: "grey" }[frm.doc.status];
		if (open) {
			const left = frm.doc.days_left;
			frm.dashboard.set_headline(left < 0
				? __("Expired {0} days ago", [-left])
				: __("{0} days left until expiry", [left]), colour);
		}
	},

	product_type(frm) {
		// Product name is normally the same as the type; keep a name the user typed.
		if (!frm.doc.product_name || frm.doc.product_name === frm._last_product_type) {
			frm.set_value("product_name", frm.doc.product_type);
		}
		frm._last_product_type = frm.doc.product_type;
	},

	start_date(frm) {
		set_expiry(frm);
	},

	billing_cycle(frm) {
		set_expiry(frm);
	},

	customer(frm) {
		// fetch_if_empty keeps old values; a new customer should replace them.
		if (!frm.doc.customer) return;
		frappe.db.get_value("Renewal Customer", frm.doc.customer, ["email", "mobile"]).then(({ message: c }) => {
			frm.set_value({ customer_email: c.email, mobile: c.mobile });
		});
	},
});

const CYCLE_MONTHS = { Monthly: 1, Quarterly: 3, "Half-Yearly": 6, Annually: 12 };

function set_expiry(frm) {
	// Renewal Date + billing cycle, e.g. 29-10-2026 Annually -> 29-10-2027. Custom: user enters it.
	const months = CYCLE_MONTHS[frm.doc.billing_cycle];
	if (frm.doc.start_date && months) {
		frm.set_value("expiry_date", frappe.datetime.add_months(frm.doc.start_date, months));
	}
}

function mark_renewed(frm) {
	const custom = frm.doc.billing_cycle === "Custom";
	const run = (values) =>
		frm.call("mark_renewed", { new_expiry_date: values && values.new_expiry_date }).then((r) => {
			frappe.show_alert({ message: __("Next period created: {0}", [r.message]), indicator: "green" });
			frm.reload_doc();
		});

	if (custom) {
		frappe.prompt(
			[{ fieldname: "new_expiry_date", fieldtype: "Date", label: __("New Expiry Date"), reqd: 1 }],
			run, __("Mark Renewed"), __("Renew")
		);
	} else {
		frappe.confirm(
			__("Mark as Renewed and create the next {0} record?", [frm.doc.billing_cycle.toLowerCase()]),
			() => run()
		);
	}
}

function mark_lost(frm) {
	frappe.prompt(
		[{ fieldname: "reason", fieldtype: "Small Text", label: __("Lost Reason") }],
		(values) => frm.call("mark_lost", { reason: values.reason }).then(() => frm.reload_doc()),
		__("Mark Lost"), __("Mark Lost")
	);
}
