// Copyright (c) 2026, huda and contributors
// For license information, please see license.txt

frappe.listview_settings["Renewal"] = {
	add_fields: ["status", "days_left"],
	get_indicator(doc) {
		const colour = { Active: "blue", Due: "orange", Expired: "red", Lost: "grey" }[doc.status];
		return [__(doc.status), colour, "status,=," + doc.status];
	},
	formatters: {
		days_left(value, df, doc) {
			// Same pill as the status indicator: red expired / today, orange <= 7, yellow <= 30, green later.
			if (doc.status === "Lost" || value === null || value === undefined || value === "") return "";
			const days = cint(value);
			const colour = days <= 0 ? "red" : days <= 7 ? "orange" : days <= 30 ? "yellow" : "green";
			const text = days < 0 ? __("{0} days ago", [-days]) : days === 0 ? __("Today") : __("{0} days", [days]);
			return `<span class="indicator-pill no-indicator-dot whitespace-nowrap ${colour}">${text}</span>`;
		},
	},
};
