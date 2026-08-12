from app import app, db, Ad, build_ad_slug


with app.app_context():

    ads = Ad.query.order_by(Ad.id.asc()).all()

    total = 0

    for ad in ads:

        new_slug = build_ad_slug(ad)

        if ad.slug != new_slug:
            ad.slug = new_slug
            total += 1

            print(
                f"ID {ad.id}: {ad.slug}"
            )

    db.session.commit()

    print()
    print(
        f"{total} anúncios atualizados com slug."
    )