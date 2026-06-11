from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from . import db
from datetime import date as dt

from .models import CustomerFavourite, CustomerRegularMed, Item, Organization, PartyLedger, Patient, RetailCustomer, Role, Scheme, Supplier, TaxSlab, User
from .services import billing as billing_service
from .services import inventory as inventory_service
from .services import purchase as purchase_service

DISTRIBUTOR_NAME = "Infivita Pharmaceuticals"
DISTRIBUTOR_GSTIN = "36AHEPD1696A4Z0"
STATE_CODE = "36"


def seed_if_empty(force: bool = False) -> None:
    if not force and Organization.query.first():
        return

    if force:
        db.drop_all()
        db.create_all()

    roles = {
        "DISTRIBUTOR_ADMIN": Role(code="DISTRIBUTOR_ADMIN", name="Distributor Admin"),
        "FACILITY_ADMIN": Role(code="FACILITY_ADMIN", name="Facility Admin"),
        "CASHIER": Role(code="CASHIER", name="Cashier"),
    }
    for r in roles.values():
        db.session.add(r)
    db.session.flush()

    dist = Organization(
        code="INFIVITA",
        name=DISTRIBUTOR_NAME,
        kind="DISTRIBUTOR",
        gstin=DISTRIBUTOR_GSTIN,
        drug_license="DL-TG-2024-INFIVITA",
        address="Hyderabad, Telangana",
        state_code=STATE_CODE,
        phone="9876500000",
    )
    db.session.add(dist)
    db.session.flush()

    facilities = [
        Organization(
            code="RTL01",
            name="Infivita Retail Pharmacy — Secunderabad",
            kind="RETAIL",
            gstin="36RETAIL001A1Z5",
            drug_license="DL-RTL-TG-001",
            address="Secunderabad, Telangana",
            state_code=STATE_CODE,
            phone="9876501001",
            parent_id=dist.id,
        ),
        Organization(
            code="HSP01",
            name="Infivita Hospital Pharmacy — Gachibowli",
            kind="HOSPITAL",
            gstin="36HOSP001B1Z5",
            drug_license="DL-HSP-TG-001",
            address="Gachibowli, Hyderabad, Telangana",
            state_code=STATE_CODE,
            phone="9876501002",
            parent_id=dist.id,
        ),
    ]
    for f in facilities:
        db.session.add(f)
    db.session.flush()

    tax_12 = TaxSlab(name="GST 12%", rate=Decimal("12"), hsn="3004")
    tax_5 = TaxSlab(name="GST 5%", rate=Decimal("5"), hsn="3006")
    db.session.add_all([tax_12, tax_5])
    db.session.flush()

    items = [
        Item(code="PCM500", barcode="890101001001", name="Paracetamol 500mg", manufacturer="Cipla", pack="1x15",
             mrp=Decimal("35"), ptr=Decimal("28"), hsn="3004", tax_slab_id=tax_12.id),
        Item(code="AMX500", barcode="890101001002", name="Amoxicillin 500mg", manufacturer="Sun Pharma", pack="1x10",
             mrp=Decimal("120"), ptr=Decimal("95"), hsn="3004", tax_slab_id=tax_12.id, schedule="H"),
        Item(code="ORS01", barcode="890101001003", name="ORS Sachet", manufacturer="FDC", pack="1x1",
             mrp=Decimal("25"), ptr=Decimal("18"), hsn="3006", tax_slab_id=tax_5.id),
        Item(code="MET500", barcode="890101001004", name="Metformin 500mg", manufacturer="USV", pack="1x20",
             mrp=Decimal("55"), ptr=Decimal("42"), hsn="3004", tax_slab_id=tax_12.id),
        Item(code="CET10", barcode="890101001005", name="Cetirizine 10mg", manufacturer="Dr Reddy", pack="1x10",
             mrp=Decimal("45"), ptr=Decimal("32"), hsn="3004", tax_slab_id=tax_12.id),
    ]
    db.session.add_all(items)
    db.session.flush()

    users = [
        User(username="distributor", full_name="Infivita Admin", role_id=roles["DISTRIBUTOR_ADMIN"].id, org_id=dist.id),
        User(username="retail_admin", full_name="Secunderabad Manager", role_id=roles["FACILITY_ADMIN"].id, org_id=facilities[0].id),
        User(username="retail1", full_name="Secunderabad Cashier", role_id=roles["CASHIER"].id, org_id=facilities[0].id),
        User(username="hospital1", full_name="Gachibowli Pharmacist", role_id=roles["FACILITY_ADMIN"].id, org_id=facilities[1].id),
    ]
    for u in users:
        u.set_password("admin")
        db.session.add(u)

    db.session.add(Patient(facility_id=facilities[1].id, name="Ravi Kumar", uhid="UHID-1001", ward="ICU-3"))
    db.session.add(Patient(facility_id=facilities[1].id, name="Priya Sharma", uhid="UHID-1002", ward="OPD"))

    # Per-facility min/max limits (retail vs hospital use different levels)
    retail_limits = {"PCM500": (50, 150), "AMX500": (30, 120), "ORS01": (40, 100),
                     "MET500": (40, 120), "CET10": (30, 100)}
    hospital_limits = {"PCM500": (100, 300), "AMX500": (80, 250), "ORS01": (60, 200),
                       "MET500": (70, 200), "CET10": (50, 150)}
    for fac, limits_map in [(facilities[0], retail_limits), (facilities[1], hospital_limits)]:
        for item in items:
            min_q, max_q = limits_map.get(item.code, (20, 100))
            inventory_service.upsert_stock_limit(fac.id, item.id, Decimal(min_q), Decimal(max_q))

    expiry = date.today() + timedelta(days=365)
    for fac in facilities:
        lines = []
        for item in items:
            lines.append({
                "item_id": item.id,
                "batch_no": f"B{item.code}",
                "expiry": expiry,
                "mrp": item.mrp,
                "ptr": item.ptr,
                "cost_rate": (item.ptr * Decimal("0.85")).quantize(Decimal("0.01")),
                "qty": Decimal("200"),
            })
        inventory_service.receive_consignment(dist, fac, lines, note="Opening consignment from Infivita")

    rc = RetailCustomer(
        facility_id=facilities[0].id,
        name="Ramesh Kumar",
        phone="9876543210",
        credit_limit=Decimal("5000"),
        credit_days=30,
    )
    db.session.add(rc)
    db.session.flush()
    db.session.add_all([
        PartyLedger(
            org_id=facilities[0].id,
            party_name="Telangana State Medical Corp",
            party_gstin="36INST001C1Z5",
            credit_days=45,
            credit_limit=Decimal("250000"),
        ),
        PartyLedger(
            org_id=facilities[0].id,
            party_name="Apollo Clinics — Hyderabad",
            party_gstin="36INST002D1Z5",
            credit_days=30,
        ),
    ])
    db.session.add(CustomerRegularMed(customer_id=rc.id, item_id=items[3].id, typical_qty=Decimal("2")))
    db.session.add(CustomerRegularMed(customer_id=rc.id, item_id=items[0].id, typical_qty=Decimal("1")))
    db.session.add(CustomerFavourite(facility_id=facilities[0].id, item_id=items[0].id, sort_order=1))
    db.session.add(CustomerFavourite(facility_id=facilities[0].id, item_id=items[4].id, sort_order=2))
    db.session.add(Scheme(org_id=facilities[0].id, name="Monsoon 5% Off", kind="PERCENT", value=Decimal("5"), item_id=items[0].id))
    supplier = Supplier(org_id=dist.id, code="SUP01", name="Telangana Pharma Wholesale", gstin="36SUP001A1Z5")
    db.session.add(supplier)
    db.session.flush()

    warehouse = inventory_service.get_or_create_warehouse(dist.id)
    cold_chain = inventory_service.create_warehouse(
        dist.id,
        code="WH02",
        name="Infivita Cold Chain — Gachibowli",
        address="Gachibowli, Hyderabad",
    )
    purchase_service.create_purchase(
        dist,
        supplier,
        [
            {
                "item_id": item.id,
                "batch_no": f"WH-{item.code}",
                "expiry": expiry,
                "qty": Decimal("500"),
                "rate": (item.ptr * Decimal("0.85")).quantize(Decimal("0.01")),
                "mrp": item.mrp,
            }
            for item in items
        ],
        invoice_no="OPENING-WH",
        warehouse_id=warehouse.id,
    )
    purchase_service.create_purchase(
        dist,
        supplier,
        [
            {
                "item_id": items[1].id,
                "batch_no": f"COLD-{items[1].code}",
                "expiry": expiry,
                "qty": Decimal("200"),
                "rate": (items[1].ptr * Decimal("0.85")).quantize(Decimal("0.01")),
                "mrp": items[1].mrp,
            },
            {
                "item_id": items[3].id,
                "batch_no": f"COLD-{items[3].code}",
                "expiry": expiry,
                "qty": Decimal("150"),
                "rate": (items[3].ptr * Decimal("0.85")).quantize(Decimal("0.01")),
                "mrp": items[3].mrp,
            },
        ],
        invoice_no="OPENING-COLD",
        warehouse_id=cold_chain.id,
    )

    billing_service.create_bill(
        facilities[0], "RETAIL",
        [{"item_id": items[0].id, "qty": Decimal("155"), "rate": items[0].mrp}],
        customer_name="Ramesh Kumar", retail_customer_id=rc.id, payment_mode="CASH",
    )
    billing_service.create_bill(
        facilities[1], "HOSPITAL",
        [{"item_id": items[1].id, "qty": Decimal("1"), "rate": items[1].mrp}],
        customer_name="Ravi Kumar", doctor_name="Dr. Mehta",
        patient_id=1, payment_mode="CASH",
    )
    billing_service.create_bill(
        facilities[0], "INSTITUTIONAL",
        [{"item_id": items[2].id, "qty": Decimal("50"), "rate": items[2].mrp}],
        customer_name="Telangana State Medical Corp",
        customer_gstin="36INST001C1Z5",
        payment_mode="CREDIT",
        order_ref="PO-TGMC-2026-0142",
    )

    db.session.commit()