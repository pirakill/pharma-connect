from pharmaconnect import create_app, db
from pharmaconnect.models import Item
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services import items as item_service


def test_import_csv_creates_and_updates(app=None):
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        before = Item.query.count()
        csv_text = """code,name,barcode,mrp,ptr,gst_rate
NEW001,New Medicine Alpha,8909990001,50,40,12
PCM500,Paracetamol 500mg Updated,890101001001,36,29,12
"""
        result = item_service.import_csv(csv_text)
        db.session.commit()
        assert result["created"] == 1
        assert result["updated"] == 1
        assert Item.query.count() == before + 1
        updated = Item.query.filter_by(code="PCM500").first()
        assert "Updated" in updated.name
        assert float(updated.mrp) == 36


def test_import_csv_missing_columns():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        try:
            item_service.import_csv("name only\nFoo")
            assert False, "should raise"
        except ValueError as e:
            assert "code" in str(e)