from __future__ import annotations

from .. import db
from ..models import Bill, ConsignmentShipment, WarehouseTransfer


def next_bill_number(facility_id: int) -> str:
    count = Bill.query.filter_by(facility_id=facility_id).count()
    return f"B{facility_id:03d}-{count + 1:06d}"


def next_shipment_number(distributor_id: int) -> str:
    count = ConsignmentShipment.query.filter_by(distributor_id=distributor_id).count()
    return f"CS{distributor_id:03d}-{count + 1:06d}"


def next_transfer_number(distributor_id: int) -> str:
    count = WarehouseTransfer.query.filter_by(distributor_id=distributor_id).count()
    return f"WT{distributor_id:03d}-{count + 1:06d}"