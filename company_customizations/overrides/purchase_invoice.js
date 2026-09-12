frappe.ui.form.on("Purchase Invoice", {
    refresh: function (frm) {
        frm.set_query("expense_account", "items", function () {
            return {
                query: "company_customizations.queries.get_purchase_invoice_expense_account",
                filters: {
                    company: frm.doc.company,
                    disabled: 0,
                },
            };
        });
    },
});
