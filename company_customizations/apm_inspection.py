import frappe


def update_inspection_timestamps(doc, method=None):
    if doc.inspection_status == "In Progress" and not doc.arrival_time:
        doc.arrival_time = frappe.utils.now_datetime()

    if doc.inspection_status == "Submitted to Network" and not doc.departure_time:
        doc.departure_time = frappe.utils.now_datetime()

        if doc.arrival_time:
            delta = doc.departure_time - doc.arrival_time
            doc.time_spent_minutes = int(delta.total_seconds() / 60)

        if not doc.submitted_to_network_at:
            doc.submitted_to_network_at = doc.departure_time
