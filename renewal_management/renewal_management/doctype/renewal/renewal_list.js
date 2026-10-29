// Copyright (c) 2026, huda and contributors
// For license information, please see license.txt

frappe.listview_settings["Renewal"] = {
	add_fields: ["status", "days_left", "payment_status"],
	get_indicator(doc) {
		if (doc.status === "Renewed" && doc.payment_status === "Pending") {
			return [__("Payment Pending"), "purple", "payment_status,=,Pending"];
		}
		const colour = { Active: "blue", Due: "orange", Expired: "red", Renewed: "green", Lost: "grey" }[doc.status];
		return [__(doc.status), colour, "status,=," + doc.status];
	},
	formatters: {
		days_left(value, df, doc) {
			if (!["Active", "Due", "Expired"].includes(doc.status)) return "";
			const colour = value < 0 ? "red" : value <= 7 ? "orange" : "inherit";
			return `<span style="color:var(--${colour}-500, ${colour})">${value}</span>`;
		},
	},
};
