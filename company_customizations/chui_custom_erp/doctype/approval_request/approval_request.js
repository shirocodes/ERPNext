// Copyright (c) 2026, Sammy and contributors
// For license information, please see license.txt

frappe.ui.form.on("Approval Request", {
    refresh(frm) {
        if (frm.is_new()) return;

        // Use server-stored request information.
        // Final authorization is always performed in Python.
        const doc = frm.doc;
        const user = frappe.session.user;

        const is_manager =
            doc.assigned_approver === user;

        const is_requester =
            doc.requested_by === user;

        // Display the current request status.
        const colors = {
            "Draft": "blue",
            "Pending Approval": "orange",
            "Approved": "green",
            "Rejected": "red",
            "Completed": "green"
        };

        frm.dashboard.set_headline_alert(
            __("Approval Status: {0}", [doc.workflow_state]),
            colors[doc.workflow_state] || "blue"
        );

        // MANAGER ACTIONS
        if (is_manager && doc.workflow_state === "Pending Approval") {
            frm.add_custom_button(
                __("Approve"),
                () => approve_request(frm),
                __("Approval Actions")
            );

            frm.add_custom_button(
                __("Reject"),
                () => reject_request(frm),
                __("Approval Actions")
            );
        }

        if (
            is_manager &&
            doc.workflow_state === "Approved" &&
            doc.execution_status !== "Completed"
        ) {
            frm.add_custom_button(
                __("Execute Approved Deletion"),
                () => execute_deletion(frm),
                __("Approval Actions")
            );
        }

        // REQUESTER ACTIONS
        if (is_requester && doc.workflow_state === "Draft") {
            frm.add_custom_button(
                __("Submit for Approval"),
                () => submit_request(frm)
            );
        }

        if (is_requester && doc.workflow_state === "Rejected") {
            frm.add_custom_button(
                __("Revise Request"),
                () => revise_request(frm)
            );
        }

        // Target document link.
        // Hide after deletion because the record no longer exists.
        if (doc.workflow_state !== "Completed" && doc.reference_doctype && doc.reference_name) {
            frm.add_custom_button(
                __("View Target Document"),
                () => {
                    frappe.set_route(
                        "Form",
                        doc.reference_doctype,
                        doc.reference_name
                    );
                }
            );
        }
    }
});


function approval_call(method, args, frm) {
    return frappe.call({
        method:
            "company_customizations.approvals.api." + method,
        args: args,
        freeze: true,
        freeze_message: __("Processing approval request...")
    }).then(() => {
        return frm.reload_doc();
    });
}


function submit_request(frm) {
    frappe.confirm(
        __("Submit this deletion request to your assigned manager?"),
        () => {
            approval_call(
                "submit_request",
                {request_name: frm.doc.name},
                frm
            );
        }
    );
}


function approve_request(frm) {
    frappe.prompt(
        [{
            fieldname: "comments",
            label: __("Approval Comments"),
            fieldtype: "Small Text"
        }],
        (values) => {
            approval_call(
                "approve_request",
                {
                    request_name: frm.doc.name,
                    comments: values.comments || ""
                },
                frm
            );
        },
        __("Approve Deletion Request"),
        __("Approve")
    );
}


function reject_request(frm) {
    frappe.prompt(
        [{
            fieldname: "comments",
            label: __("Reason for Rejection"),
            fieldtype: "Small Text",
            reqd: 1
        }],
        (values) => {
            approval_call(
                "reject_request",
                {
                    request_name: frm.doc.name,
                    comments: values.comments
                },
                frm
            );
        },
        __("Reject Deletion Request"),
        __("Reject")
    );
}


function revise_request(frm) {
    frappe.prompt(
        [{
            fieldname: "new_reason",
            label: __("Revised Justification"),
            fieldtype: "Small Text",
            reqd: 1,
            default: frm.doc.reason
        }],
        (values) => {
            approval_call(
                "revise_request",
                {
                    request_name: frm.doc.name,
                    new_reason: values.new_reason
                },
                frm
            );
        },
        __("Revise Deletion Request"),
        __("Save Revision")
    );
}


function execute_deletion(frm) {
    const doc = frm.doc;

    frappe.confirm(
        __(
            "Permanently delete {0}: {1}? This action cannot be undone through the approval workflow.",
            [doc.reference_doctype, doc.reference_name]
        ),
        () => {
            approval_call(
                "execute_approved_deletion",
                {request_name: doc.name},
                frm
            );
        }
    );
}

