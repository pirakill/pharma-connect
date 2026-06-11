"""PharmaConnect — distributor consignment platform with live stock visibility."""
from pharmaconnect import create_app, db
from pharmaconnect.seed import seed_if_empty

app = create_app()


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        seed_if_empty()
    app.run(host="0.0.0.0", port=5000, debug=True)