import frappe


def execute(filters=None):
    filters = frappe._dict(filters or {})

    columns = get_columns()
    data = get_data(filters)

    return columns, data


def get_columns():
    return [
        {
            "label": "Attribution Source",
            "fieldname": "attribution_source",
            "fieldtype": "Data",
            "width": 150,
        },
        {
            "label": "Lead Owner",
            "fieldname": "lead_owner",
            "fieldtype": "Link",
            "options": "User",
            "width": 220,
        },
        {
            "label": "Parcel Type",
            "fieldname": "parcel_type",
            "fieldtype": "Data",
            "width": 110,
        },
        {
            "label": "Total Parcels",
            "fieldname": "total_parcels",
            "fieldtype": "Int",
            "width": 110,
        },
        {
            "label": "Paid",
            "fieldname": "paid",
            "fieldtype": "Int",
            "width": 90,
        },
        {
            "label": "Unpaid",
            "fieldname": "unpaid",
            "fieldtype": "Int",
            "width": 90,
        },
        {
            "label": "Failed",
            "fieldname": "failed",
            "fieldtype": "Int",
            "width": 90,
        },
        {
            "label": "No Payment Outcome",
            "fieldname": "no_payment_outcome",
            "fieldtype": "Int",
            "width": 150,
        },
        {
            "label": "Not Applicable",
            "fieldname": "not_applicable",
            "fieldtype": "Int",
            "width": 120,
        },
        {
            "label": "Payment Success %",
            "fieldname": "payment_success_percentage",
            "fieldtype": "Percent",
            "width": 130,
        },
    ]


def get_data(filters):
    conditions = []
    values = {}

    # ------------------------------------------------------------
    # Reporting date
    # ------------------------------------------------------------
    if filters.get("from_date"):
        conditions.append("p.creation >= %(from_date)s")
        values["from_date"] = filters.get("from_date")

    if filters.get("to_date"):
        conditions.append("p.creation < DATE_ADD(%(to_date)s, INTERVAL 1 DAY)")
        values["to_date"] = filters.get("to_date")

    # ------------------------------------------------------------
    # Build base parcel dataset
    #
    # Important:
    # We deliberately DO NOT JOIN Parcel Payments directly.
    # A parcel can have multiple Parcel Payments rows.
    # Directly joining them would duplicate parcels.
    # ------------------------------------------------------------
    where_clause = ""

    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    query = f"""
        SELECT
            p.name AS parcel_name,
            p.parcel_type,
            p.payment_entry_status,

            CASE
                WHEN c.email_id IS NOT NULL
                     AND l.lead_owner IS NOT NULL
                    THEN 'CRM Lead'

                WHEN c.email_id IS NOT NULL
                    THEN 'Customer Portal'

                ELSE 'Unattributed'
            END AS attribution_source,

            CASE
                WHEN c.email_id IS NOT NULL
                     AND l.lead_owner IS NOT NULL
                    THEN l.lead_owner

                ELSE NULL
            END AS lead_owner,

            CASE
                WHEN p.parcel_type = 'BTI'
                    THEN 'Not Applicable'

                WHEN p.payment_entry_status = 'PAID'
                    THEN 'PAID'

                WHEN EXISTS (
                    SELECT 1
                    FROM `tabParcel Payments` pp_failed
                    WHERE pp_failed.parent = p.name
                      AND pp_failed.status = 'FAILED'
                )
                    THEN 'FAILED'

                WHEN EXISTS (
                    SELECT 1
                    FROM `tabParcel Payments` pp_unpaid
                    WHERE pp_unpaid.parent = p.name
                      AND pp_unpaid.status = 'UNPAID'
                )
                    THEN 'UNPAID'

                ELSE 'No Payment Outcome'
            END AS payment_outcome

        FROM `tabChui Parcels` p

        LEFT JOIN (
            SELECT
                LOWER(TRIM(email_id)) AS normalized_email,
                MAX(email_id) AS email_id
            FROM `tabCustomer`
            WHERE IFNULL(email_id, '') != ''
            GROUP BY LOWER(TRIM(email_id))
        ) c
            ON LOWER(TRIM(p.sender_email)) = c.normalized_email

        LEFT JOIN (
            SELECT
                LOWER(TRIM(email_id)) AS normalized_email,
                MAX(lead_owner) AS lead_owner
            FROM `tabLead`
            WHERE IFNULL(email_id, '') != ''
              AND IFNULL(lead_owner, '') != ''
            GROUP BY LOWER(TRIM(email_id))
        ) l
            ON c.normalized_email = l.normalized_email

        {where_clause}
    """

    parcels = frappe.db.sql(
        query,
        values,
        as_dict=True,
    )

    # ------------------------------------------------------------
    # Apply row-level filters that depend on derived classifications
    # ------------------------------------------------------------
    if filters.get("lead_owner"):
        parcels = [
            row
            for row in parcels
            if row.lead_owner == filters.get("lead_owner")
        ]

    if filters.get("attribution_source"):
        parcels = [
            row
            for row in parcels
            if row.attribution_source == filters.get("attribution_source")
        ]

    if filters.get("parcel_type"):
        parcels = [
            row
            for row in parcels
            if row.parcel_type == filters.get("parcel_type")
        ]

    if filters.get("payment_outcome"):
        parcels = [
            row
            for row in parcels
            if row.payment_outcome == filters.get("payment_outcome")
        ]

    # ------------------------------------------------------------
    # Aggregate:
    #
    # One parcel = one performance record.
    # ------------------------------------------------------------
    grouped = {}

    for row in parcels:
        key = (
            row.attribution_source,
            row.lead_owner or "",
            row.parcel_type or "",
        )

        if key not in grouped:
            grouped[key] = {
                "attribution_source": row.attribution_source,
                "lead_owner": row.lead_owner,
                "parcel_type": row.parcel_type,
                "total_parcels": 0,
                "paid": 0,
                "unpaid": 0,
                "failed": 0,
                "no_payment_outcome": 0,
                "not_applicable": 0,
            }

        result = grouped[key]

        result["total_parcels"] += 1

        if row.payment_outcome == "PAID":
            result["paid"] += 1

        elif row.payment_outcome == "UNPAID":
            result["unpaid"] += 1

        elif row.payment_outcome == "FAILED":
            result["failed"] += 1

        elif row.payment_outcome == "Not Applicable":
            result["not_applicable"] += 1

        else:
            result["no_payment_outcome"] += 1

    # ------------------------------------------------------------
    # Payment success percentage
    #
    # BTI is excluded because it is not payment-applicable.
    #
    # Denominator:
    # PAID + UNPAID + FAILED
    #
    # "No Payment Outcome" is NOT included in denominator.
    # ------------------------------------------------------------
    data = []

    for result in grouped.values():
        payment_applicable = (
            result["paid"]
            + result["unpaid"]
            + result["failed"]
        )

        if payment_applicable:
            result["payment_success_percentage"] = round(
                (result["paid"] / payment_applicable) * 100,
                2,
            )
        else:
            result["payment_success_percentage"] = 0

        data.append(result)

    # ------------------------------------------------------------
    # Sort:
    # CRM Lead first, then Customer Portal, then Unattributed.
    # Within each source, sort by Lead Owner and Parcel Type.
    # ------------------------------------------------------------
    source_order = {
        "CRM Lead": 1,
        "Customer Portal": 2,
        "Unattributed": 3,
    }

    data.sort(
        key=lambda row: (
            source_order.get(row["attribution_source"], 99),
            row["lead_owner"] or "",
            row["parcel_type"] or "",
        )
    )

    return data
