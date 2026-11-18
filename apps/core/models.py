from django.db import models
from django.utils.text import slugify
from django.urls import reverse
from django.utils import timezone

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    icon_class = models.CharField(max_length=80, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "categories"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class Product(models.Model):
    DRAFT = "draft"
    PUBLISHED = "published"
    STATUS_CHOICES = [(DRAFT, "Draft"), (PUBLISHED, "Published")]
    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    additional_categories = models.ManyToManyField(
    Category,
    blank=True,
    related_name="additional_products"
    )
    short_description = models.CharField(max_length=260)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    thumbnail = models.ImageField(upload_to="products/thumbnails/", blank=True, null=True)
    github_repo_owner = models.CharField(max_length=100, blank=True)
    github_repo_name = models.CharField(max_length=150, blank=True)
    languages = models.CharField(max_length=250, blank=True)
    frameworks = models.CharField(max_length=250, blank=True)
    database = models.CharField(max_length=150, blank=True)
    skill_level = models.CharField(max_length=50, blank=True)
    version = models.CharField(max_length=30, default="1.0.0")
    installation_instructions = models.TextField(blank=True)
    documentation_url = models.URLField(blank=True)
    features = models.TextField(blank=True)
    whats_included = models.TextField(blank=True)
    support_details = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    is_featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_featured", "-created_at"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def display_price(self):
        return self.discount_price if self.discount_price is not None else self.price

    @property
    def has_discount(self):
        return self.discount_price is not None and self.discount_price < self.price

    def get_absolute_url(self):
        return reverse("product_detail", kwargs={"slug": self.slug})

    def __str__(self):
        return self.name


class ProductScreenshot(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="screenshots")
    image = models.ImageField(upload_to="products/screenshots/")
    caption = models.CharField(max_length=150, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    class Meta:
        ordering = ["sort_order", "pk"]

from django.core.files.storage import FileSystemStorage
from django.conf import settings
private_document_storage = FileSystemStorage(location=settings.BASE_DIR / "private_docs")

class ProductDocument(models.Model):
    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name="document")
    pdf = models.FileField(upload_to="products/private_docs/", storage=private_document_storage)
    uploaded_at = models.DateTimeField(auto_now=True)

class CustomerProfile(models.Model):
    user = models.OneToOneField("auth.User", on_delete=models.CASCADE, related_name="customer_profile")
    email_verified = models.BooleanField(default=False)
    github_user_id = models.BigIntegerField(unique=True, null=True, blank=True)
    github_username = models.CharField(max_length=100, blank=True)
    github_connected_at = models.DateTimeField(null=True, blank=True)
    def __str__(self):
        return self.user.username


class Cart(models.Model):
    user = models.OneToOneField("auth.User", on_delete=models.CASCADE, related_name="cart")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart: {self.user.username}"

    @property
    def subtotal(self):
        return sum((item.line_total for item in self.items.select_related("product")), start=0)

    @property
    def item_count(self):
        return sum(item.quantity for item in self.items.all())


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="cart_items")
    quantity = models.PositiveSmallIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["cart", "product"], name="unique_product_per_cart")
        ]

    @property
    def line_total(self):
        return self.product.display_price * self.quantity


class Order(models.Model):
    PENDING_PAYMENT = "pending_payment"
    PAID = "paid"
    PAYMENT_FAILED = "payment_failed"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (PENDING_PAYMENT, "Pending payment"),
        (PAID, "Paid"),
        (PAYMENT_FAILED, "Payment failed"),
        (CANCELLED, "Cancelled"),
    ]
    user = models.ForeignKey("auth.User", on_delete=models.PROTECT, related_name="orders")
    order_number = models.CharField(max_length=24, unique=True)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=PENDING_PAYMENT)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="INR")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.order_number


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    product_name = models.CharField(max_length=180)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveSmallIntegerField(default=1)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.product_name} × {self.quantity}"


class Payment(models.Model):
    CREATED = "created"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    FAILED = "failed"
    STATUS_CHOICES = [
        (CREATED, "Created"),
        (AUTHORIZED, "Authorized"),
        (CAPTURED, "Captured"),
        (FAILED, "Failed"),
    ]
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")
    provider = models.CharField(max_length=30, default="razorpay")
    provider_order_id = models.CharField(max_length=100, unique=True)
    provider_payment_id = models.CharField(max_length=100, blank=True, db_index=True)
    amount_paise = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, default="INR")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=CREATED)
    failure_reason = models.CharField(max_length=500, blank=True)
    signature_verified = models.BooleanField(default=False)
    webhook_verified = models.BooleanField(default=False)
    raw_event = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.provider_order_id} — {self.status}"


class GitHubAccess(models.Model):
    NOT_CONNECTED = "not_connected"
    PENDING = "pending"
    INVITATION_SENT = "invitation_sent"
    ACTIVE = "active"
    FAILED = "failed"
    REVOKED = "revoked"
    STATUS_CHOICES = [
        (NOT_CONNECTED, "GitHub not connected"),
        (PENDING, "Pending"),
        (INVITATION_SENT, "Invitation sent"),
        (ACTIVE, "Active"),
        (FAILED, "Failed"),
        (REVOKED, "Revoked"),
    ]
    order_item = models.OneToOneField(OrderItem, on_delete=models.PROTECT, related_name="github_access")
    customer = models.ForeignKey("auth.User", on_delete=models.PROTECT, related_name="github_access_grants")
    repo_owner = models.CharField(max_length=100)
    repo_name = models.CharField(max_length=150)
    github_username = models.CharField(max_length=100, blank=True)
    github_user_id = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=PENDING)
    invitation_id = models.PositiveBigIntegerField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    invited_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.customer.username}: {self.repo_owner}/{self.repo_name} ({self.status})"


class AdminProfile(models.Model):
    SUPER_ADMIN = "super_admin"
    PRODUCT_MANAGER = "product_manager"
    ORDER_MANAGER = "order_manager"
    SUPPORT_MANAGER = "support_manager"
    ROLE_CHOICES = [
        (SUPER_ADMIN, "Super administrator"),
        (PRODUCT_MANAGER, "Product manager"),
        (ORDER_MANAGER, "Order manager"),
        (SUPPORT_MANAGER, "Support manager"),
    ]
    user = models.OneToOneField("auth.User", on_delete=models.CASCADE, related_name="aklyte_admin_profile")
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default=PRODUCT_MANAGER)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} — {self.get_role_display()}"


class AuditLog(models.Model):
    actor = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="aklyte_audit_events")
    action = models.CharField(max_length=80)
    object_type = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=80, blank=True)
    message = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} — {self.created_at:%Y-%m-%d %H:%M}"


class Coupon(models.Model):
    PERCENT = "percent"
    FIXED = "fixed"
    DISCOUNT_TYPES = [(PERCENT, "Percentage"), (FIXED, "Fixed amount")]
    code = models.CharField(max_length=40, unique=True)
    discount_type = models.CharField(max_length=10, choices=DISCOUNT_TYPES, default=PERCENT)
    value = models.DecimalField(max_digits=10, decimal_places=2)
    active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    usage_limit = models.PositiveIntegerField(null=True, blank=True)
    usage_count = models.PositiveIntegerField(default=0)
    minimum_order = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.code

    def is_valid_for(self, user, subtotal):
        now = timezone.now()
        if not self.active or (self.starts_at and now < self.starts_at) or (self.expires_at and now > self.expires_at):
            return False
        if self.usage_limit is not None and self.usage_count >= self.usage_limit:
            return False
        if subtotal < self.minimum_order:
            return False
        if CouponRedemption.objects.filter(coupon=self, user=user).exists():
            return False
        return True


class CouponRedemption(models.Model):
    coupon = models.ForeignKey(Coupon, on_delete=models.PROTECT, related_name="redemptions")
    user = models.ForeignKey("auth.User", on_delete=models.PROTECT, related_name="coupon_redemptions")
    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name="coupon_redemption")
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2)
    redeemed_at = models.DateTimeField(auto_now_add=True)



class ProductReview(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="reviews"
    )

    # Optional: retained for compatibility with existing customer reviews.
    user = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="product_reviews"
    )

    # Optional: admin-created reviews do not need an order.
    order_item = models.OneToOneField(
        OrderItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="review"
    )

    reviewer_name = models.CharField(max_length=100, blank=True, default="")
    rating = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=120, blank=True)
    body = models.TextField(max_length=2000)
    approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=1, rating__lte=5),
                name="review_rating_1_to_5"
            )
        ]

    def __str__(self):
        return f"{self.product.name} — {self.rating}/5"


class SupportTicket(models.Model):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    STATUS_CHOICES = [(OPEN, "Open"), (IN_PROGRESS, "In progress"), (RESOLVED, "Resolved"), (CLOSED, "Closed")]
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    PRIORITY_CHOICES = [(LOW, "Low"), (NORMAL, "Normal"), (HIGH, "High")]
    user = models.ForeignKey("auth.User", on_delete=models.PROTECT, related_name="support_tickets")
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.SET_NULL, related_name="support_tickets")
    subject = models.CharField(max_length=160)
    message = models.TextField(max_length=5000)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=OPEN)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=NORMAL)
    staff_response = models.TextField(blank=True, max_length=5000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"#{self.pk} {self.subject}"
