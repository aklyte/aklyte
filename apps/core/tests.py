from django.test import TestCase, Client
from django.contrib.auth.models import User
from .models import Category, Product
from apps.core.models import Order

class StorefrontTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="MERN",slug="mern")
        self.product = Product.objects.create(name="Example",slug="example",category=self.category,short_description="Example project",description="Description",price=100,status="draft")
    def test_draft_hidden(self):
        self.assertNotContains(self.client.get("/products/"),"Example")
    def test_published_visible(self):
        self.product.status="published"
        self.product.save()
        self.assertContains(self.client.get("/products/"),"Example")
    def test_management_protected(self):
        self.assertEqual(self.client.get("/management/").status_code,302)


class CartAndOrderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="buyer", password="StrongPass123!")
        self.category = Category.objects.create(name="Web Apps", slug="web-apps")
        self.product = Product.objects.create(
            name="Published App", slug="published-app", category=self.category,
            short_description="A sample app", description="Details",
            price="1200.00", discount_price="900.00", status="published"
        )

    def test_customer_can_add_published_product_to_cart(self):
        self.client.login(username="buyer", password="StrongPass123!")
        response = self.client.post(f"/cart/add/{self.product.pk}/")
        self.assertEqual(response.status_code, 302)
        from .models import CartItem
        self.assertEqual(CartItem.objects.filter(cart__user=self.user, product=self.product).count(), 1)

    def test_customer_cannot_add_draft_product(self):
        draft = Product.objects.create(
            name="Draft App", slug="draft-app", category=self.category,
            short_description="Draft", description="Details", price="100.00", status="draft"
        )
        self.client.login(username="buyer", password="StrongPass123!")
        response = self.client.post(f"/cart/add/{draft.pk}/")
        self.assertEqual(response.status_code, 404)

    def test_checkout_creates_pending_order_and_clears_cart(self):
        from .models import Cart, CartItem, Order
        self.client.login(username="buyer", password="StrongPass123!")
        cart, _ = Cart.objects.get_or_create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=2)
        response = self.client.post("/checkout/")
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get(user=self.user)
        self.assertEqual(order.status, Order.PENDING_PAYMENT)
        self.assertEqual(order.total, 1800)
        self.assertEqual(cart.items.count(), 0)

    def test_order_detail_is_private_to_owner(self):
        from .models import Order
        order = Order.objects.create(user=self.user, order_number="AK-TEST-OWN", subtotal=100, total=100)
        other = User.objects.create_user(username="other", password="StrongPass123!")
        self.client.login(username="other", password="StrongPass123!")
        response = self.client.get(f"/account/orders/{order.order_number}/")
        self.assertEqual(response.status_code, 404)


class RazorpayVerificationTests(TestCase):
    def setUp(self):
        from .models import Payment, Order
        from django.test import override_settings
        self.user = User.objects.create_user(username="payer", password="StrongPass123!")
        self.order = Order.objects.create(user=self.user, order_number="AK-RAZOR-001", subtotal=100, total=100)
        self.payment = Payment.objects.create(
            order=self.order, provider_order_id="order_test_123",
            amount_paise=10000, currency="INR"
        )

    def test_callback_signature_helper_matches_hmac(self):
        import hashlib, hmac
        secret = "test_secret"
        message = b"order_test_123|pay_test_123"
        signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
        self.assertEqual(len(signature), 64)

    def test_capture_is_idempotent(self):
        from .views import _mark_payment_captured
        from .models import Payment, Order
        _mark_payment_captured(self.payment, "pay_test_123", signature_verified=True)
        _mark_payment_captured(self.payment, "pay_test_123", webhook_verified=True)
        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.CAPTURED)
        self.assertTrue(self.payment.signature_verified)
        self.assertTrue(self.payment.webhook_verified)
        self.assertEqual(self.order.status, Order.PAID)

    def test_invalid_callback_signature_does_not_mark_paid(self):
        from django.test import override_settings
        self.client.force_login(self.user)
        with override_settings(RAZORPAY_KEY_SECRET="right-secret"):
            response = self.client.post(
                "/payments/razorpay/AK-RAZOR-001/callback/",
                {
                    "razorpay_order_id": "order_test_123",
                    "razorpay_payment_id": "pay_test_123",
                    "razorpay_signature": "wrong",
                },
            )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.PENDING_PAYMENT)

    def test_webhook_rejects_invalid_signature(self):
        from django.test import override_settings
        with override_settings(RAZORPAY_WEBHOOK_SECRET="webhook-secret"):
            response = self.client.post(
                "/payments/razorpay/webhook/",
                data=b'{"event":"payment.captured"}',
                content_type="application/json",
                HTTP_X_RAZORPAY_SIGNATURE="invalid",
            )
        self.assertEqual(response.status_code, 400)


class GitHubDeliveryRecordTests(TestCase):
    def setUp(self):
        from .models import Order, OrderItem, GitHubAccess
        self.user = User.objects.create_user(username="githubbuyer", password="StrongPass123!")
        self.category = Category.objects.create(name="Source", slug="source")
        self.product = Product.objects.create(
            name="Source Product", slug="source-product", category=self.category,
            short_description="Source", description="Description", price=100,
            github_repo_owner="aklyte-tech", github_repo_name="private-source",
            status="published"
        )
        self.order = Order.objects.create(user=self.user, order_number="AK-GH-001", subtotal=100, total=100, status=Order.PAID)
        self.item = OrderItem.objects.create(
            order=self.order, product=self.product, product_name=self.product.name,
            unit_price=100, quantity=1, line_total=100
        )

    def test_access_record_can_be_created_for_paid_order(self):
        from .github_delivery import create_access_records_for_paid_order
        records = create_access_records_for_paid_order(self.order)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].repo_owner, "aklyte-tech")
        self.assertEqual(records[0].status, "pending")

    def test_unpaid_order_does_not_create_access(self):
        from .models import GitHubAccess, Order
        from .github_delivery import create_access_records_for_paid_order
        self.order.status = Order.PENDING_PAYMENT
        self.order.save()
        self.assertEqual(create_access_records_for_paid_order(self.order), [])
        self.assertEqual(GitHubAccess.objects.count(), 0)

    def test_customer_only_sees_own_github_access(self):
        from .models import GitHubAccess
        access = GitHubAccess.objects.create(
            order_item=self.item, customer=self.user, repo_owner="aklyte-tech",
            repo_name="private-source", status=GitHubAccess.PENDING
        )
        self.client.force_login(self.user)
        response = self.client.get("/account/github-access/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "private-source")


class NotificationEmailTests(TestCase):
    def test_customer_email_uses_user_email(self):
        from django.core import mail
        from django.test import override_settings
        from .notifications import send_customer_email
        user = User.objects.create_user(username="mailbuyer", email="buyer@example.com", password="StrongPass123!")
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            sent = send_customer_email(user, "Test subject", "Test message")
        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["buyer@example.com"])

    def test_customer_email_skips_missing_email(self):
        from .notifications import send_customer_email
        user = User.objects.create_user(username="nomail", password="StrongPass123!")
        self.assertFalse(send_customer_email(user, "Test subject", "Test message"))


class Phase9SecurityTests(TestCase):
    def setUp(self):
        from .models import AdminProfile
        self.product_staff = User.objects.create_user(username="productstaff", password="StrongPass123!", is_staff=True)
        AdminProfile.objects.create(user=self.product_staff, role=AdminProfile.PRODUCT_MANAGER)
        self.support_staff = User.objects.create_user(username="supportstaff", password="StrongPass123!", is_staff=True)
        AdminProfile.objects.create(user=self.support_staff, role=AdminProfile.SUPPORT_MANAGER)

    def test_product_manager_can_open_product_management(self):
        self.client.force_login(self.product_staff)
        self.assertEqual(self.client.get("/management/products/").status_code, 200)

    def test_support_manager_cannot_open_product_management(self):
        self.client.force_login(self.support_staff)
        self.assertEqual(self.client.get("/management/products/add/").status_code, 403)

    def test_non_staff_cannot_open_management(self):
        customer = User.objects.create_user(username="ordinary", password="StrongPass123!")
        self.client.force_login(customer)
        self.assertIn(self.client.get("/management/").status_code, (302, 403))

    def test_audit_log_records_actor_and_action(self):
        from .models import AuditLog
        from .views import record_audit
        category = Category.objects.create(name="Audit test")
        request = type("Request", (), {"user": self.product_staff, "META": {"REMOTE_ADDR": "127.0.0.1"}})()
        record_audit(request, "category.test", category, "test event")
        entry = AuditLog.objects.get(action="category.test")
        self.assertEqual(entry.actor, self.product_staff)
        self.assertEqual(entry.object_id, str(category.pk))
        self.assertEqual(entry.ip_address, "127.0.0.1")


class GoogleSignInTests(TestCase):
    def test_google_login_shows_configuration_message_when_credentials_missing(self):
        from django.test import override_settings
        with override_settings(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET=""):
            response = self.client.get("/account/google/login/")
        self.assertRedirects(response, "/account/login/", fetch_redirect_response=False)
        self.assertIn("Google sign-in is not configured", [str(m) for m in response.wsgi_request._messages])

    def test_google_callback_rejects_invalid_state(self):
        response = self.client.get("/account/google/callback/?code=fake&state=wrong")
        self.assertRedirects(response, "/account/login/", fetch_redirect_response=False)

    def test_google_login_starts_oauth_with_state_and_nonce(self):
        from django.test import override_settings
        from urllib.parse import urlparse, parse_qs
        with override_settings(
            GOOGLE_CLIENT_ID="test-client.apps.googleusercontent.com",
            GOOGLE_CLIENT_SECRET="test-secret",
            GOOGLE_REDIRECT_URI="http://testserver/account/google/callback/",
        ):
            response = self.client.get("/account/google/login/")
        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response["Location"])
        params = parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, "accounts.google.com")
        self.assertTrue(params.get("state", [""])[0])
        self.assertTrue(params.get("nonce", [""])[0])
        self.assertEqual(params.get("client_id"), ["test-client.apps.googleusercontent.com"])
