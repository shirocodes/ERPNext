
(function () {
    "use strict";

    const API = "company_customizations.approvals.api";
    const DEBUG = false;

    const LABELS = {
        request: __("Request Deletion Approval"),
        existing: __("View My Approval Request")
    };

    function log(...args) {
        if (DEBUG) {
            console.log("[Approval UI]", ...args);
        }
    }

    function is_current_form(frm, doctype, docname) {
        return (
            window.cur_frm === frm &&
            !frm.is_new() &&
            frm.doctype === doctype &&
            frm.doc.name === docname
        );
    }


	const APPROVAL_STATUS_COLORS = {
		"Draft": ["#F1F3F5", "#495057"],
		"Pending Approval": ["#FFF3CD", "#946200"],
		"Approved": ["#DCEBFF", "#175CD3"],
		"Rejected": ["#FEE4E2", "#B42318"],
		"Completed": ["#DCFCE7", "#166534"]
	};


	function get_approval_header(frm) {
		// The Frappe page header is outside frm.page.wrapper
		// in the current ERPNext layout.
		const $page = $(frm.page.page);

		let $header = $page
			.find(".page-head .page-title")
			.first();

		if (!$header.length) {
			$header = $(".page-head .page-title")
				.first();
		}

		return $header;
	}


	function clear_approval_status(frm) {
		get_approval_header(frm)
			.find(".chui-approval-status")
			.remove();
	}

	function render_approval_status(frm, status) {
		clear_approval_status(frm);

		if (!status || !APPROVAL_STATUS_COLORS[status]) {
			return;
		}

		const $header = get_approval_header(frm);

		if (!$header.length) {
			console.warn(
				"[Approval UI] Header not found:",
				frm.doctype
			);
			return;
		}

		const [background, color] =
			APPROVAL_STATUS_COLORS[status];

		const $badge = $("<span>", {
			class: "chui-approval-status",
			text: __("Approval: {0}", [status]),
			title: __("Approval Request status: {0}", [status])
		}).css({
			display: "inline-flex",
			alignItems: "center",
			verticalAlign: "middle",
			whiteSpace: "nowrap",
			marginLeft: "8px",
			padding: "4px 10px",
			borderRadius: "999px",
			fontSize: "12px",
			fontWeight: "600",
			lineHeight: "1.3",
			backgroundColor: background,
			color
		});

		$header.append($badge);
	}


    async function refresh_approval_actions(frm) {
		clear_approval_status(frm);

		if (frm.is_new()) return;

        const doctype = frm.doctype;
        const docname = frm.doc.name;

        // Invalidate earlier asynchronous lookups.
        const token = (frm.__approval_token || 0) + 1;
        frm.__approval_token = token;

        log("Checking", doctype, docname);

        try {
            const response = await frappe.call({
                method: `${API}.get_document_approval_context`,
                type: "GET",
                args: { doctype, docname }
            });

            if (
                !is_current_form(frm, doctype, docname) ||
                frm.__approval_token !== token
            ) {
                return;
            }

            const context = response.message;

			render_approval_status(
					frm,
				context?.approval_status || null
			);

            if (!context || !context.has_policy) {
                log("No active policy");
                return;
            }

            if (context.current_request) {
                const name = context.current_request.name;

                frm.page.add_action_item(
                    LABELS.existing,
                    () => frappe.set_route(
                        "Form",
                        "Approval Request",
                        name
                    )
                );

                log("Existing request:", name);
                return;
            }

            if (
                context.can_request &&
                context.operation === "Delete Document"
            ) {
                frm.page.add_action_item(
                    LABELS.request,
                    () => show_request_dialog(
                        frm,
                        context,
                        doctype,
                        docname
                    )
                );

                log("Request action added");
            }
        } catch (error) {
            console.error(
                "[Approval UI] Policy lookup failed",
                error
            );
        }
    }

    function show_request_dialog(
        frm,
        context,
        doctype,
        docname
    ) {
        if (!is_current_form(frm, doctype, docname)) {
            frappe.msgprint(
                __("Refresh the document and try again.")
            );
            return;
        }

        const dialog = new frappe.ui.Dialog({
            title: __("Request Deletion Approval"),
            fields: [
                {
                    fieldtype: "HTML",
                    fieldname: "target_details",
                    options:
                        `<p class="text-muted">
                            ${__("Document")}:
                            <strong>${frappe.utils.escape_html(doctype)}</strong>
                            — ${frappe.utils.escape_html(docname)}
                        </p>`
                },
                {
                    fieldtype: "Small Text",
                    fieldname: "reason",
                    label: __("Reason for Deletion"),
                    reqd: context.require_reason ? 1 : 0,
                    description: __(
                        "Explain why this document should be deleted."
                    )
                }
            ],
            primary_action_label: __("Submit Request"),
            primary_action: async (values) => {
                const reason = (values.reason || "").trim();

                if (context.require_reason && !reason) {
                    frappe.msgprint(
                        __("A reason is required.")
                    );
                    return;
                }

                if (!is_current_form(frm, doctype, docname)) {
                    frappe.msgprint(
                        __("The document changed. Please retry.")
                    );
                    return;
                }

                dialog.get_primary_btn().prop(
                    "disabled",
                    true
                );

                let request_name = null;

                try {
                    const created = await frappe.call({
                        method: `${API}.create_request`,
                        type: "POST",
                        args: {
                            policy_name: context.policy_name,
                            reference_name: docname,
                            reason
                        }
                    });

                    const result = created.message;

                    request_name =
                        typeof result === "string"
                            ? result
                            : result?.name || result?.request_name;

                    if (!request_name) {
                        throw new Error(
                            "Approval API returned no request ID."
                        );
                    }

                    await frappe.call({
                        method: `${API}.submit_request`,
                        type: "POST",
                        args: { request_name }
                    });

                    dialog.hide();

                    frappe.show_alert({
                        message: __("Approval request submitted"),
                        indicator: "green"
                    });

                    frappe.set_route(
                        "Form",
                        "Approval Request",
                        request_name
                    );
                } catch (error) {
                    console.error(
                        "[Approval UI] Request failed",
                        error
                    );

                    if (request_name) {
                        dialog.hide();

                        frappe.msgprint({
                            title: __("Request not submitted"),
                            indicator: "orange",
                            message: __(
                                "Approval Request {0} was created but submission failed. Open it to review or retry.",
                                [frappe.utils.escape_html(request_name)]
                            )
                        });
                    } else {
                        frappe.msgprint({
                            title: __("Unable to create request"),
                            indicator: "red",
                            message: __(
                                "The request could not be created. Check the server error."
                            )
                        });
                    }
                } finally {
                    dialog.get_primary_btn().prop(
                        "disabled",
                        false
                    );
                }
            }
        });

        dialog.show();
    }

    // Global form refresh handler.
	// Works across DocTypes without individual doctype_js registrations.
	$(document)
		.off("form-refresh.chui-approvals")
		.on("form-refresh.chui-approvals", function (event, frm) {
			if (!frm || !frm.doc || !frm.page) {
				return;
			}

			console.log(
				"[Approval UI] Form refresh:",
				frm.doctype,
				frm.doc.name
			);

			refresh_approval_actions(frm);
		});

    window.chuiApprovalUI = {
        version: "4B",
        refresh: refresh_approval_actions
    };

    log("Universal approval UI registered");
})();
