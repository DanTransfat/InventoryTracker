"""Load demo data: 60 items with varied stock, several already below threshold.

Usage:  python -m scripts.seed            (skips if items already exist)
        python -m scripts.seed --force    (adds the items even if some exist; SKUs must be free)

All stock is created through the same service the API uses, so every unit on hand
has a ledger row behind it and alerts are opened by the normal lifecycle rules.
"""
from __future__ import annotations

import argparse
import logging
import random
import sys

from app.config import get_settings
from app.db import Database
from app.schemas import ItemCreate, TransactionCreate
from app.services.inventory import InventoryService
from app.services.notifier import LogNotifier

logging.basicConfig(level="INFO", format="%(levelname)s %(message)s")
log = logging.getLogger("seed")
logging.getLogger("inventory.alerts").setLevel(logging.ERROR)  # keep seed output quiet

CATALOG = [
    # (prefix, unit, names)
    ("BOLT", "box", ["Hex Bolt M6x20", "Hex Bolt M8x30", "Carriage Bolt 3/8in", "Lag Bolt 1/4in", "Eye Bolt M10"]),
    ("NUT", "box", ["Hex Nut M6", "Hex Nut M8", "Lock Nut M10", "Wing Nut 1/4in", "Flange Nut M8"]),
    ("SCR", "box", ["Wood Screw #8 1.5in", "Drywall Screw 2in", "Machine Screw M4", "Deck Screw 3in", "Sheet Metal Screw #10"]),
    ("TAPE", "roll", ["Packing Tape Clear", "Duct Tape Silver", "Masking Tape 1in", "Electrical Tape Black", "Fragile Tape Red"]),
    ("BOX", "each", ["Shipping Box Small", "Shipping Box Medium", "Shipping Box Large", "Pallet Box", "Mailer Box"]),
    ("GLV", "pair", ["Nitrile Gloves M", "Nitrile Gloves L", "Work Gloves Leather", "Cut-Resistant Gloves", "Cold Storage Gloves"]),
    ("LBL", "roll", ["Thermal Labels 4x6", "Barcode Labels 2x1", "Address Labels", "Hazmat Labels", "Pallet Tags"]),
    ("WRAP", "roll", ["Stretch Wrap 18in", "Bubble Wrap 12in", "Kraft Paper Roll", "Foam Wrap", "Shrink Film"]),
    ("BAT", "each", ["AA Battery", "AAA Battery", "9V Battery", "Scanner Battery Pack", "CR2032 Coin Cell"]),
    ("CLN", "each", ["Floor Cleaner 1gal", "Glass Cleaner", "Hand Sanitizer 1L", "Shop Towels Pack", "Degreaser Spray"]),
    ("SAF", "each", ["Safety Glasses", "Hard Hat", "Hi-Vis Vest M", "Hi-Vis Vest L", "Ear Plugs Box"]),
    ("STR", "each", ["Ratchet Strap 2in", "Bungee Cord 24in", "Cargo Net", "Pallet Band Kit", "Corner Protector"]),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    db = Database(get_settings().database_url)
    conn = db.connect()
    service = InventoryService(db, conn, LogNotifier())
    try:
        existing = service.list_items(search=None, low_stock_only=False, include_archived=True,
                                      sort="name", descending=False, page=1, page_size=1)["total"]
        if existing and not args.force:
            log.info("Database already has %d item(s); skipping seed (use --force to add anyway).", existing)
            return 0

        rng = random.Random(42)  # deterministic: the same seed data every time
        people = ["Alex (receiving)", "Sam (shipping)", "Jordan (inventory)", "Priya (returns)"]
        created = low = 0
        for prefix, unit, names in CATALOG:
            for index, name in enumerate(names, start=1):
                threshold = rng.choice([0, 5, 10, 20, 25, 40, 50])
                profile = rng.random()
                # ~25% of items end up below their threshold to exercise alerts.
                if threshold and profile < 0.25:
                    target = rng.randint(0, max(0, threshold - 1))
                else:
                    target = threshold + rng.randint(0, 150)

                item = service.create_item(ItemCreate(
                    sku=f"{prefix}-{index:03d}", name=name, unit=unit, reorder_threshold=threshold,
                    description=f"{name} stocked in aisle {rng.randint(1, 12)}.",
                ))
                # Build history: receive more than needed, then ship / adjust down to the target.
                received = target + rng.randint(5, 60)
                service.record_transaction(item["id"], TransactionCreate(
                    type="received", quantity_change=received, created_by=people[0], note="Initial PO"))
                remaining = received - target
                while remaining > 0:
                    step = min(remaining, rng.randint(1, 25))
                    kind = "shipped" if rng.random() < 0.85 else "adjustment"
                    service.record_transaction(item["id"], TransactionCreate(
                        type=kind, quantity_change=-step,
                        created_by=people[1] if kind == "shipped" else people[2],
                        note=None if kind == "shipped" else "Cycle count correction"))
                    remaining -= step
                if rng.random() < 0.15 and target > 0:
                    service.record_transaction(item["id"], TransactionCreate(
                        type="returned", quantity_change=1, created_by=people[3], note="Customer return"))
                    service.record_transaction(item["id"], TransactionCreate(
                        type="adjustment", quantity_change=-1, created_by=people[2], note="Return damaged, written off"))
                created += 1
                low += int(target < threshold)

        alerts = service.alert_counts()
        log.info("Seeded %d items (%d below threshold); open alerts: %d", created, low, alerts["open"])
        # Acknowledge a couple so the alerts page shows both states.
        page = service.list_alerts(statuses=["open"], page=1, page_size=2)
        for alert in page["data"]:
            service.acknowledge_alert(alert["id"], "Jordan (inventory)")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
