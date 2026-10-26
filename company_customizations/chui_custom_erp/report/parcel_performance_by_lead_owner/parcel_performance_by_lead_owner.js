frappe.query_reports["Parcel Performance by Lead Owner"] = {
    filters: [
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
            default: frappe.datetime.month_start(),
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
            default: frappe.datetime.get_today(),
        },
        {
            fieldname: "lead_owner",
            label: __("Lead Owner"),
            fieldtype: "Link",
            options: "User",
        },
        {
            fieldname: "attribution_source",
            label: __("Attribution Source"),
            fieldtype: "Select",
            options: [
                "",
                "CRM Lead",
                "Customer Portal",
                "Unattributed",
            ].join("\n"),
        },
        {
            fieldname: "parcel_type",
            label: __("Parcel Type"),
            fieldtype: "Select",
            options: [
                "",
                "C2C",
                "B2C",
                "BTI",
            ].join("\n"),
        },
        {
            fieldname: "payment_outcome",
            label: __("Payment Outcome"),
            fieldtype: "Select",
            options: [
                "",
                "PAID",
                "UNPAID",
                "FAILED",
                "No Payment Outcome",
                "Not Applicable",
            ].join("\n"),
        },
    ],

    onload: function (report) {
        report.page.add_inner_button(__("Refresh"), function () {
            report.refresh();
        });
    },
};
