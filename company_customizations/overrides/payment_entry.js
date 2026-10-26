/*
 * Payment Entry currency conversion backport
 *
 * Backports the fix for:
 * "convert amounts when payment account currency changes"
 *
 * ERPNext core remains unchanged.
 */

console.log("[company_customizations] Payment Entry currency fix loaded");


/*
 * Remove ERPNext's existing handlers for ONLY the functions
 * we are replacing.
 *
 * Frappe v15 supports frappe.ui.form.off(), which clears the
 * existing handler before our corrected handler is registered.
 */
frappe.ui.form.off("Payment Entry", "set_account_currency_and_balance");
frappe.ui.form.off("Payment Entry", "source_exchange_rate");
frappe.ui.form.off("Payment Entry", "target_exchange_rate");


frappe.ui.form.on("Payment Entry", {

	set_account_currency_and_balance: function (
		frm,
		account,
		currency_field,
		balance_field,
		callback_function
	) {
		var company_currency = frappe.get_doc(":Company", frm.doc.company).default_currency;

		/*
		 * Amounts already entered belong to the account currency
		 * that was on the form BEFORE the account changed.
		 *
		 * If no account currency exists yet, assume company currency.
		 */
		var previous_account_currency = frm.doc[currency_field] || company_currency;

		if (frm.doc.posting_date && account) {
			frappe.call({
				method: "erpnext.accounts.doctype.payment_entry.payment_entry.get_account_details",
				args: {
					account: account,
					date: frm.doc.posting_date,
					cost_center: frm.doc.cost_center,
				},
				callback: function (r, rt) {
					if (r.message) {
						frappe.run_serially([
							() =>
								frm.set_value(
									currency_field,
									r.message["account_currency"]
								),

							() => {
								frm.set_value(
									balance_field,
									r.message["account_balance"]
								);

								let account_currency_changed =
									r.message["account_currency"] !=
									previous_account_currency;


								/*
								 * RECEIVE
								 *
								 * Paid To account currency changed.
								 *
								 * received_amount belongs to the OLD
								 * account currency, so clear it and
								 * rebuild it from paid_amount.
								 */
								if (
									frm.doc.payment_type == "Receive" &&
									currency_field == "paid_to_account_currency"
								) {
									frm.toggle_reqd(
										["reference_no", "reference_date"],
										r.message["account_type"] == "Bank"
											? 1
											: 0
									);

									if (
										account_currency_changed &&
										frm.doc.received_amount &&
										frm.doc.paid_amount
									) {
										frm.set_value(
											"target_exchange_rate",
											0
										);

										frm.set_value(
											"received_amount",
											0
										);
									}

									if (
										!frm.doc.received_amount &&
										frm.doc.paid_amount
									) {
										frm.events.paid_amount(frm);
									}


								/*
								 * PAY
								 *
								 * Paid From account currency changed.
								 *
								 * paid_amount belongs to the OLD
								 * account currency, so clear it and
								 * rebuild it from received_amount.
								 */
								} else if (
									frm.doc.payment_type == "Pay" &&
									currency_field == "paid_from_account_currency"
								) {
									frm.toggle_reqd(
										["reference_no", "reference_date"],
										r.message["account_type"] == "Bank"
											? 1
											: 0
									);

									if (
										account_currency_changed &&
										frm.doc.paid_amount &&
										frm.doc.received_amount
									) {
										frm.set_value(
											"source_exchange_rate",
											0
										);

										frm.set_value(
											"paid_amount",
											0
										);
									}

									if (
										!frm.doc.paid_amount &&
										frm.doc.received_amount
									) {
										frm.events.received_amount(frm);
									}


									/*
									 * Preserve standard ERPNext
									 * same-currency behaviour.
									 */
									if (
										frm.doc.paid_from_account_currency ==
											frm.doc.paid_to_account_currency &&
										frm.doc.paid_amount !=
											frm.doc.received_amount
									) {
										if (
											company_currency !=
												frm.doc
													.paid_from_account_currency &&
											frm.doc.payment_type == "Pay"
										) {
											frm.doc.paid_amount =
												frm.doc.received_amount;
										}
									}
								}
							},

							() => {
								if (callback_function) {
									callback_function(frm);
								}

								frm.events.hide_unhide_fields(frm);
								frm.events.set_dynamic_labels(frm);
							},
						]);
					}
				},
			});
		}
	},


	/*
	 * Source Exchange Rate
	 *
	 * Used primarily for Paid From.
	 *
	 * If paid_amount was cleared because the account changed
	 * currency, derive the new paid_amount from received_amount.
	 */
	source_exchange_rate: function (frm) {
		let company_currency =
			frappe.get_doc(":Company", frm.doc.company).default_currency;


		/*
		 * Standard ERPNext calculation.
		 */
		if (frm.doc.paid_amount) {
			frm.set_value(
				"base_paid_amount",
				flt(frm.doc.paid_amount) *
					flt(frm.doc.source_exchange_rate)
			);


			/*
			 * Target exchange rate should be same as source
			 * when both accounts use the same currency.
			 */
			if (
				frm.doc.paid_from_account_currency ==
				frm.doc.paid_to_account_currency
			) {
				frm.set_value(
					"target_exchange_rate",
					frm.doc.source_exchange_rate
				);

				frm.set_value(
					"base_received_amount",
					frm.doc.base_paid_amount
				);

			} else if (
				company_currency ==
				frm.doc.paid_to_account_currency
			) {
				frm.set_value(
					"received_amount",
					frm.doc.base_paid_amount
				);

				frm.set_value(
					"base_received_amount",
					frm.doc.base_paid_amount
				);
			}


			frm.events.set_total_allocated_amount(frm);


		/*
		 * BACKPORT FIX
		 *
		 * paid_amount was cleared because Paid From changed
		 * currency.
		 *
		 * received_amount is still valid.
		 *
		 * Example:
		 *
		 * received_amount = KES 12,000
		 * source rate     = 160
		 *
		 * paid_amount:
		 * 12,000 / 160 = EUR 75
		 */
		} else if (
			frm.doc.received_amount &&
			frm.doc.source_exchange_rate &&
			frm.doc.paid_from_account_currency !=
				frm.doc.paid_to_account_currency
		) {
			const target_rate =
				flt(frm.doc.target_exchange_rate) ||
				(
					company_currency ==
					frm.doc.paid_to_account_currency
						? 1
						: 0
				);

			if (target_rate) {
				frm.set_value(
					"base_received_amount",
					flt(frm.doc.received_amount) *
						target_rate
				);

				frm.set_value(
					"base_paid_amount",
					frm.doc.base_received_amount
				);

				frm.set_value(
					"paid_amount",
					flt(frm.doc.base_paid_amount) /
						flt(frm.doc.source_exchange_rate)
				);

				frm.events.set_total_allocated_amount(frm);
			}
		}


		/*
		 * Make rate read-only if Accounts Settings
		 * does not allow stale rates.
		 */
		frm.set_df_property(
			"source_exchange_rate",
			"read_only",
			erpnext.stale_rate_allowed() ? 0 : 1
		);
	},


	/*
	 * Target Exchange Rate
	 *
	 * Mirror operation for Paid To.
	 */
	target_exchange_rate: function (frm) {
		frm.set_paid_amount_based_on_received_amount = true;

		let company_currency =
			frappe.get_doc(":Company", frm.doc.company).default_currency;


		/*
		 * Standard ERPNext calculation.
		 */
		if (frm.doc.received_amount) {
			frm.set_value(
				"base_received_amount",
				flt(frm.doc.received_amount) *
					flt(frm.doc.target_exchange_rate)
			);


			if (
				!frm.doc.source_exchange_rate &&
				frm.doc.paid_from_account_currency ==
					frm.doc.paid_to_account_currency
			) {
				frm.set_value(
					"source_exchange_rate",
					frm.doc.target_exchange_rate
				);

				frm.set_value(
					"base_paid_amount",
					frm.doc.base_received_amount
				);

			} else if (
				company_currency ==
				frm.doc.paid_from_account_currency
			) {
				frm.set_value(
					"paid_amount",
					frm.doc.base_received_amount
				);

				frm.set_value(
					"base_paid_amount",
					frm.doc.base_received_amount
				);
			}


			frm.events.set_total_allocated_amount(frm);


		/*
		 * BACKPORT FIX
		 *
		 * received_amount was cleared because Paid To changed
		 * currency.
		 *
		 * paid_amount remains valid and becomes the source
		 * of truth.
		 */
		} else if (
			frm.doc.paid_amount &&
			frm.doc.target_exchange_rate &&
			frm.doc.paid_from_account_currency !=
				frm.doc.paid_to_account_currency
		) {
			const source_rate =
				flt(frm.doc.source_exchange_rate) ||
				(
					company_currency ==
					frm.doc.paid_from_account_currency
						? 1
						: 0
				);

			if (source_rate) {
				frm.set_value(
					"base_paid_amount",
					flt(frm.doc.paid_amount) *
						source_rate
				);

				frm.set_value(
					"base_received_amount",
					frm.doc.base_paid_amount
				);

				frm.set_value(
					"received_amount",
					flt(frm.doc.base_received_amount) /
						flt(frm.doc.target_exchange_rate)
				);

				frm.events.set_total_allocated_amount(frm);
			}
		}


		frm.set_paid_amount_based_on_received_amount = false;


		/*
		 * Make rate read-only if Accounts Settings
		 * does not allow stale rates.
		 */
		frm.set_df_property(
			"target_exchange_rate",
			"read_only",
			erpnext.stale_rate_allowed() ? 0 : 1
		);
	},
});
