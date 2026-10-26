frappe.ui.form.on("APM Inspection", {
    refresh(frm) {
        frm.add_custom_button("Open Inspection Wizard", () => {
            open_apm_inspection_wizard(frm);
        });
    }
});


function open_apm_inspection_wizard(frm) {

    let current_step = 1;

    const dialog = new frappe.ui.Dialog({
        title: "APM Inspection",
        size: "large",

        fields: [

            // STEP 1
            {
                fieldtype: "Section Break",
                label: "Step 1 — Site Information"
            },

            {
                fieldname: "site_name",
                label: "Site / Location",
                fieldtype: "Data",
                reqd: 1,
                default: frm.doc.site_name
            },

            {
                fieldname: "latitude",
                label: "Latitude",
                fieldtype: "Data",
                default: frm.doc.latitude
            },

            {
                fieldname: "longitude",
                label: "Longitude",
                fieldtype: "Data",
                default: frm.doc.longitude
            },

            {
                fieldname: "space_dimensions",
                label: "Space Dimensions",
                fieldtype: "Data",
                default: frm.doc.space_dimensions
            },

            {
                fieldtype: "Section Break",
                label: "Step 2 — Inspection Findings"
            },

            {
                fieldname: "result",
                label: "Inspection Findings Status",
                fieldtype: "Select",
                options: [
                    "",
                    "Pass",
                    "Pass with Issues",
                    "fail"
                ],
                default: frm.doc.result
            },

            {
                fieldname: "findings",
                label: "Findings",
                fieldtype: "Small Text",
                default: frm.doc.findings
            },

            {
                fieldname: "follow_up_required",
                label: "Follow-up Required",
                fieldtype: "Select",
                options: [
                    "",
                    "Space allocation",
                    "Power Connection",
                    "Security",
                    "Visibility"
                ],
                default: frm.doc.follow_up_required
            },

            {
                fieldname: "follow_up_notes",
                label: "Follow-up Notes",
                fieldtype: "Small Text",
                default: frm.doc.follow_up_notes
            },

            {
                fieldname: "installation_consumables_needed",
                label: "Installation Consumables Needed",
                fieldtype: "Data",
                default: frm.doc.installation_consumables_needed
            }
        ],

        primary_action_label: "Save",

        primary_action(values) {

            frm.set_value("site_name", values.site_name);
            frm.set_value("latitude", values.latitude);
            frm.set_value("longitude", values.longitude);
            frm.set_value("space_dimensions", values.space_dimensions);

            frm.set_value("result", values.result);
            frm.set_value("findings", values.findings);
            frm.set_value(
                "follow_up_required",
                values.follow_up_required
            );
            frm.set_value(
                "follow_up_notes",
                values.follow_up_notes
            );
            frm.set_value(
                "installation_consumables_needed",
                values.installation_consumables_needed
            );

            dialog.hide();

            frm.save().then(() => {
                frappe.show_alert({
                    message: "Inspection saved",
                    indicator: "green"
                });
            });
        }
    });

    dialog.show();
}
