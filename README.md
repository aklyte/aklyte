# AKLYTE — Phase 10: Customer Experience & Business Operations

Cumulative package: Phases 1–9 plus customer support tickets, verified-purchase product reviews and coupon discounts.

## Upgrade safely (Windows)

1. Back up `.env`, `db.sqlite3`, `media/`, `private_docs/` and `github_keys/`.
2. Extract this ZIP into a clean project folder, then restore your environment file, database, uploaded files and current GitHub App PEM key.
3. Run:

```cmd
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py makemigrations core
python manage.py migrate
python manage.py test
python manage.py runserver
```

## Customer features

- Customers can create support tickets, optionally linked to their own orders.
- Customers can see only their own tickets and replies.
- Customers can submit one review per paid order item. Reviews are hidden until staff approval.
- Approved reviews appear on the product detail page.
- Customers can apply coupons at checkout. Coupons are validated server-side for active dates, minimum order, usage limit and one redemption per customer. The discounted total is stored in the order before payment is created.

## Manage coupons

Coupons can be created through Django shell for now; a dedicated coupon CRUD screen is a later improvement:

```cmd
python manage.py shell
```

```python
from apps.core.models import Coupon
Coupon.objects.create(code="WELCOME10", discount_type="percent", value=10, usage_limit=100)
Coupon.objects.create(code="SAVE200", discount_type="fixed", value=200, minimum_order=1000)
```

Percentage coupons accept values from 0 to 100. Do not create invalid percentages. A coupon is reserved/redeemed when the pending order is created; cancelled or unpaid orders do not automatically restore coupon usage in this phase.

## Staff operations

- Support Managers and Super Admins can update support tickets at `/management/support/`.
- Product Managers and Super Admins can moderate reviews at `/management/reviews/`.
- Actions are recorded in the existing audit log.

## Important

- This package's tests are syntax-checked and ZIP-checked at build time; run `python manage.py test` locally.
- No live email, Razorpay or GitHub integration is executed by this archive build.
- Review moderation is manual. Coupon management UI, refunds, advanced analytics and customer notification inbox are reserved for later phases.


## Google Sign-In (customer accounts)

See [GOOGLE_SIGN_IN_SETUP.md](GOOGLE_SIGN_IN_SETUP.md) for Google Cloud OAuth client setup, authorized callback URL, `.env` values and local testing. Google Sign-In is separate from the customer's GitHub connection used for private repository delivery.




6523 4005 2922 1787
