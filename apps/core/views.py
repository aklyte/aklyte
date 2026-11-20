from functools import wraps
from django.conf import settings
from decimal import Decimal
from django.db.models import Q
from django.db.models import Avg
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.utils import timezone
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.core.exceptions import ValidationError
import secrets, requests
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Q, Sum
from django.db import transaction
from django.utils.crypto import get_random_string
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, HttpResponseBadRequest
from decimal import Decimal, ROUND_HALF_UP
import hashlib, hmac, json
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .forms import CategoryForm, ProductForm, CustomerRegistrationForm, CustomerProfileForm, ScreenshotForm, validate_pdf_upload, validate_image_upload
from .models import Category, Product, ProductScreenshot, ProductDocument, CustomerProfile, Cart, CartItem, Order, OrderItem, Payment, GitHubAccess, AdminProfile, AuditLog, Coupon, CouponRedemption, ProductReview, SupportTicket

def staff_required(view_func):
    return user_passes_test(lambda u: u.is_authenticated and u.is_active and u.is_staff,
                            login_url="management_login")(view_func)

def staff_role_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            user = request.user
            if not (user.is_authenticated and user.is_active and user.is_staff):
                return redirect("management_login")
            if user.is_superuser:
                return view_func(request, *args, **kwargs)
            profile = getattr(user, "aklyte_admin_profile", None)
            if profile is None or profile.role not in allowed_roles:
                from django.core.exceptions import PermissionDenied
                raise PermissionDenied("Your AKLYTE staff role cannot perform this action.")
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator

def record_audit(request, action, obj=None, message=""):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
    AuditLog.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        action=action,
        object_type=obj.__class__.__name__ if obj else "",
        object_id=str(obj.pk) if obj and obj.pk else "",
        message=message[:2000],
        ip_address=ip or None,
    )

def home(request):
    categories = Category.objects.filter(is_active=True)
    featured = Product.objects.filter(status=Product.PUBLISHED, is_featured=True).select_related("category")[:6]
    latest = Product.objects.filter(status=Product.PUBLISHED).select_related("category")[:8]
    return render(request, "storefront/home.html", {"categories": categories, "featured": featured, "latest": latest})

def product_list(request):
    products = Product.objects.filter(status=Product.PUBLISHED).select_related("category")
    query = request.GET.get("q", "").strip()
    if query:
        products = products.filter(Q(name__icontains=query) | Q(short_description__icontains=query) | Q(description__icontains=query))
    return render(request, "storefront/product_list.html", {
        "products": products, "categories": Category.objects.filter(is_active=True), "query": query
    })

def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("category"),
        slug=slug,
        status=Product.PUBLISHED
    )

    reviews = ProductReview.objects.filter(
        product=product,
        approved=True
    ).order_by("-created_at")

    review_summary = reviews.aggregate(
        average=Avg("rating")
    )

    return render(request, "storefront/product_detail.html", {
        "product": product,
        "screenshots": product.screenshots.all(),
        "reviews": reviews,
        "review_count": reviews.count(),
        "average_rating": review_summary["average"] or 0,
    })

def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug, is_active=True)
    products = Product.objects.filter(
    Q(category=category) | Q(additional_categories=category),
    status=Product.PUBLISHED
    ).select_related("category").distinct()
    return render(request, "storefront/product_list.html", {
        "products": products, "categories": Category.objects.filter(is_active=True), "active_category": category
    })

def health(request):
    return JsonResponse({"status": "ok", "service": "AKLYTE"})

def management_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("management_dashboard")
    error = ""
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_active and user.is_staff:
            login(request, user)
            return redirect("management_dashboard")
        error = "Invalid staff credentials or this account does not have staff access."
    return render(request, "management/login.html", {"error": error})

@staff_required
def management_logout(request):
    if request.method == "POST":
        logout(request)
        return redirect("management_login")
    return redirect("management_dashboard")


@staff_required
def management_dashboard(request):
    User = get_user_model()
    today = timezone.localdate()

    paid_orders = Order.objects.filter(status=Order.PAID)
    today_paid_orders = paid_orders.filter(created_at__date=today)

    context = {
        # Sales and revenue
        "total_revenue": paid_orders.aggregate(
            total=Sum("total")
        )["total"] or 0,

        "today_revenue": today_paid_orders.aggregate(
            total=Sum("total")
        )["total"] or 0,

        "total_orders": Order.objects.count(),
        "paid_orders_count": paid_orders.count(),
        "pending_orders_count": Order.objects.filter(
            status=Order.PENDING_PAYMENT
        ).count(),
        "today_orders_count": Order.objects.filter(
            created_at__date=today
        ).count(),

        # Customers
        "customer_count": User.objects.filter(
            is_staff=False,
            is_superuser=False
        ).count(),

        # Products
        "product_count": Product.objects.count(),
        "published_count": Product.objects.filter(
            status=Product.PUBLISHED
        ).count(),
        "draft_count": Product.objects.filter(
            status=Product.DRAFT
        ).count(),
        "category_count": Category.objects.count(),

        # Payments
        "payment_count": Payment.objects.count(),
        "captured_payment_count": Payment.objects.filter(
            status=Payment.CAPTURED
        ).count(),
        "failed_payment_count": Payment.objects.filter(
            status=Payment.FAILED
        ).count(),

        # GitHub delivery
        "github_access_count": GitHubAccess.objects.count(),
        "github_pending_count": GitHubAccess.objects.filter(
            status__in=[
                GitHubAccess.PENDING,
                GitHubAccess.INVITATION_SENT
            ]
        ).count(),
        "github_failed_count": GitHubAccess.objects.filter(
            status=GitHubAccess.FAILED
        ).count(),

        # Help and Support
        "open_support_count": SupportTicket.objects.filter(
            status=SupportTicket.OPEN
        ).count(),
        "in_progress_support_count": SupportTicket.objects.filter(
            status=SupportTicket.IN_PROGRESS
        ).count(),

        # Recent activity
        "recent_orders": Order.objects.select_related(
            "user"
        ).order_by("-created_at")[:5],

        "recent_products": Product.objects.select_related(
            "category"
        ).order_by("-created_at")[:5],
    }

    return render(request, "management/dashboard.html", context)

@staff_required
def management_products(request):
    products = Product.objects.select_related("category")
    query = request.GET.get("q", "").strip()
    if query:
        products = products.filter(Q(name__icontains=query) | Q(github_repo_name__icontains=query))
    return render(request, "management/products.html", {"products": products, "query": query})


@staff_required
def management_customers(request):
    User = get_user_model()

    query = request.GET.get("q", "").strip()

    customers = User.objects.filter(
        is_staff=False,
        is_superuser=False
    ).order_by("-date_joined")

    if query:
        customers = customers.filter(
            Q(username__icontains=query) |
            Q(email__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        )

    return render(request, "management/customers.html", {
        "customers": customers,
        "query": query,
        "total_customers": customers.count(),
    })


@staff_required
def management_customer_detail(request, pk):
    User = get_user_model()

    customer = get_object_or_404(
        User,
        pk=pk,
        is_staff=False,
        is_superuser=False
    )

    profile = CustomerProfile.objects.filter(
        user=customer
    ).first()

    orders = Order.objects.filter(
        user=customer
    ).order_by("-created_at")

    github_accesses = GitHubAccess.objects.filter(
        customer=customer
    ).select_related("order_item", "order_item__product")

    support_requests = SupportTicket.objects.filter(
        user=customer
    ).order_by("-created_at")

    return render(request, "management/customer_detail.html", {
        "customer": customer,
        "profile": profile,
        "orders": orders,
        "github_accesses": github_accesses,
        "support_requests": support_requests,
    })

@staff_role_required(AdminProfile.SUPER_ADMIN, AdminProfile.PRODUCT_MANAGER)
def management_product_add(request):
    form = ProductForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        product = form.save()
        record_audit(request, "product.created", product, f"Created product {product.name}")
        messages.success(request, f'"{product.name}" was created.')
        return redirect("management_products")
    return render(request, "management/product_form.html", {"form": form, "heading": "Add product"})

@staff_role_required(AdminProfile.SUPER_ADMIN, AdminProfile.PRODUCT_MANAGER)
def management_product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = ProductForm(request.POST or None, request.FILES or None, instance=product)
    if request.method == "POST" and form.is_valid():
        product = form.save()
        record_audit(request, "product.updated", product, f"Updated product {product.name}; status={product.status}")
        messages.success(request, f'"{product.name}" was updated.')
        return redirect("management_products")
    return render(request, "management/product_form.html", {"form": form, "heading": "Edit product", "product": product, "screenshots": product.screenshots.all(), "document": ProductDocument.objects.filter(product=product).first()})

@staff_role_required(AdminProfile.SUPER_ADMIN, AdminProfile.PRODUCT_MANAGER)
@require_POST
def management_product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    name = product.name
    record_audit(request, "product.deleted", product, f"Deleted product {name}")
    product.delete()
    messages.success(request, f'"{name}" was deleted.')
    return redirect("management_products")

@staff_required
def management_categories(request):
    return render(request, "management/categories.html", {"categories": Category.objects.all()})

@staff_role_required(AdminProfile.SUPER_ADMIN, AdminProfile.PRODUCT_MANAGER)
def management_category_add(request):
    form = CategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        category = form.save()
        record_audit(request, "category.created", category, f"Created category {category.name}")
        messages.success(request, f'"{category.name}" was created.')
        return redirect("management_categories")
    return render(request, "management/category_form.html", {"form": form, "heading": "Add category"})

@staff_role_required(AdminProfile.SUPER_ADMIN, AdminProfile.PRODUCT_MANAGER)
def management_category_edit(request, pk):
    category = get_object_or_404(Category, pk=pk)
    form = CategoryForm(request.POST or None, instance=category)
    if request.method == "POST" and form.is_valid():
        category = form.save()
        record_audit(request, "category.updated", category, f"Updated category {category.name}")
        messages.success(request, f'"{category.name}" was updated.')
        return redirect("management_categories")
    return render(request, "management/category_form.html", {"form": form, "heading": "Edit category"})

@staff_role_required(AdminProfile.SUPER_ADMIN, AdminProfile.PRODUCT_MANAGER)
@require_POST
def management_category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if category.products.exists():
        messages.error(request, "This category contains products. Move or delete those products first.")
    else:
        name = category.name
        record_audit(request, "category.deleted", category, f"Deleted category {name}")
        category.delete()
        messages.success(request, f'"{name}" was deleted.')
    return redirect("management_categories")


def customer_register(request):
    if request.user.is_authenticated:
        return redirect("customer_dashboard")
    form = CustomerRegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.is_active = False
        user.email = form.cleaned_data["email"]
        user.save()
        CustomerProfile.objects.create(user=user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        url = request.build_absolute_uri(reverse("customer_verify", args=[uid, token]))
        from .notifications import send_customer_email
        send_customer_email(
            user,
            "Verify your AKLYTE email",
            f"Hello {user.username},\\n\\nPlease verify your email address using this link:\\n{url}\\n\\nIf you did not create an AKLYTE account, you can ignore this email.",
        )
        return render(request,"accounts/registration_sent.html")
    return render(request,"accounts/register.html",{"form":form})

def customer_verify(request, uidb64, token):
    User = get_user_model()
    try: user = User.objects.get(pk=urlsafe_base64_decode(uidb64).decode())
    except (User.DoesNotExist, ValueError, TypeError, OverflowError): user = None
    if user and default_token_generator.check_token(user,token):
        user.is_active = True
        user.save(update_fields=["is_active"])
        profile,_ = CustomerProfile.objects.get_or_create(user=user)
        profile.email_verified = True
        profile.save(update_fields=["email_verified"])
        from .notifications import send_customer_email
        send_customer_email(
            user,
            "Welcome to AKLYTE",
            f"Hello {user.username},\\n\\nYour email address has been verified. You can now sign in to AKLYTE and explore software projects.",
        )
        messages.success(request,"Email verified. You can now sign in.")
        return redirect("customer_login")
    return render(request,"accounts/verification_invalid.html")

def customer_login(request):
    if request.user.is_authenticated:
        return redirect("customer_dashboard")
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request,form.get_user())
        return redirect("customer_dashboard")
    return render(request,"accounts/login.html",{"form":form})

@require_http_methods(["GET"])
def google_login(request):
    """Start Google OpenID Connect sign-in for customer accounts."""
    if request.user.is_authenticated:
        return redirect("customer_dashboard")
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        messages.error(request, "Google sign-in is not configured")
        return redirect("customer_login")

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    request.session["google_oauth_state"] = state
    request.session["google_oauth_nonce"] = nonce
    next_url = request.GET.get("next", "")
    from django.utils.http import url_has_allowed_host_and_scheme
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        request.session["google_oauth_next"] = next_url
    else:
        request.session.pop("google_oauth_next", None)

    redirect_uri = settings.GOOGLE_REDIRECT_URI or request.build_absolute_uri(reverse("google_callback"))
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "prompt": "select_account",
    }
    from urllib.parse import urlencode
    return redirect("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))


def google_callback(request):
    """Validate OAuth state and Google's signed ID token before signing in."""
    if request.user.is_authenticated:
        return redirect("customer_dashboard")
    expected_state = request.session.pop("google_oauth_state", None)
    expected_nonce = request.session.pop("google_oauth_nonce", None)
    returned_state = request.GET.get("state", "")
    if not expected_state or not secrets.compare_digest(expected_state, returned_state):
        messages.error(request, "Google sign-in could not be verified. Please try again.")
        return redirect("customer_login")
    if request.GET.get("error"):
        messages.error(request, "Google sign-in was cancelled or denied.")
        return redirect("customer_login")
    code = request.GET.get("code")
    if not code:
        messages.error(request, "Google did not return an authorization code. Please try again.")
        return redirect("customer_login")

    redirect_uri = settings.GOOGLE_REDIRECT_URI or request.build_absolute_uri(reverse("google_callback"))
    try:
        token_response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
        token_response.raise_for_status()
        token_data = token_response.json()
        id_token_value = token_data.get("id_token")
        if not id_token_value:
            raise ValueError("Google did not return an ID token.")

        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2 import id_token as google_id_token
        claims = google_id_token.verify_oauth2_token(
            id_token_value, GoogleRequest(), settings.GOOGLE_CLIENT_ID, clock_skew_in_seconds=10
        )
        email = (claims.get("email") or "").strip().lower()
        if (not email or claims.get("email_verified") is not True or not claims.get("sub")
                or not expected_nonce or claims.get("nonce") != expected_nonce):
            raise ValueError("Google account identity or nonce could not be verified.")
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Google OAuth callback failed")
        messages.error(request, "Google sign-in failed. Please try again or use email and password.")
        return redirect("customer_login")

    User = get_user_model()
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().filter(email__iexact=email).first()
            if user and (user.is_staff or user.is_superuser):
                messages.error(request, "Google sign-in is available for customer accounts only.")
                return redirect("customer_login")
            if user is None:
                base_username = (email.split("@", 1)[0] or "googleuser")[:130]
                username = base_username
                suffix = 1
                while User.objects.filter(username=username).exists():
                    suffix += 1
                    username = f"{base_username[:140-len(str(suffix))]}{suffix}"
                user = User(
                    username=username,
                    email=email,
                    first_name=(claims.get("given_name") or "")[:150],
                    last_name=(claims.get("family_name") or "")[:150],
                    is_active=True,
                )
                user.set_unusable_password()
                user.save()
            else:
                # A verified Google email safely verifies an existing customer account.
                changed = []
                if not user.is_active:
                    user.is_active = True
                    changed.append("is_active")
                if not user.email:
                    user.email = email
                    changed.append("email")
                if claims.get("given_name") and not user.first_name:
                    user.first_name = claims["given_name"][:150]
                    changed.append("first_name")
                if claims.get("family_name") and not user.last_name:
                    user.last_name = claims["family_name"][:150]
                    changed.append("last_name")
                if changed:
                    user.save(update_fields=changed)

            profile, _ = CustomerProfile.objects.get_or_create(user=user)
            if not profile.email_verified:
                profile.email_verified = True
                profile.save(update_fields=["email_verified"])
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Could not create or retrieve AKLYTE Google customer")
        messages.error(request, "We could not connect this Google account to AKLYTE. Please contact support.")
        return redirect("customer_login")

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    messages.success(request, "Signed in successfully with Google.")
    from django.utils.http import url_has_allowed_host_and_scheme
    next_url = request.session.pop("google_oauth_next", "")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect("customer_dashboard")


def customer_logout(request):
    logout(request)
    return redirect("home")

@user_passes_test(lambda u: u.is_authenticated, login_url="customer_login")
def customer_dashboard(request):
    profile,_ = CustomerProfile.objects.get_or_create(user=request.user)
    return render(request,"accounts/dashboard.html",{"profile":profile})

@user_passes_test(lambda u: u.is_authenticated, login_url="customer_login")
def customer_profile(request):
    form = CustomerProfileForm(request.POST or None,instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request,"Profile updated.")
        return redirect("customer_dashboard")
    return render(request,"accounts/profile.html",{"form":form})

@staff_required
def management_product_media(request,pk):
    product=get_object_or_404(Product,pk=pk)
    form=ScreenshotForm(request.POST or None,request.FILES or None)
    if request.method == "POST":
        if "add_screenshot" in request.POST:
            if product.screenshots.count() >= 6:
                messages.error(request,"Maximum 6 screenshots per product.")
            elif form.is_valid():
                obj=form.save(commit=False)
                obj.product=product
                obj.save()
                messages.success(request,"Screenshot added.")
                return redirect("management_product_media",pk=pk)
        elif "upload_pdf" in request.POST:
            pdf=request.FILES.get("pdf")
            if not pdf:
                messages.error(request,"Choose a PDF file.")
            else:
                try:
                    validate_pdf_upload(pdf)
                    doc,_=ProductDocument.objects.get_or_create(product=product)
                    if doc.pdf: doc.pdf.delete(save=False)
                    doc.pdf=pdf
                    doc.save()
                    messages.success(request,"PDF documentation uploaded.")
                    return redirect("management_product_media",pk=pk)
                except ValidationError as e:
                    messages.error(request," ".join(e.messages))
    return render(request,"management/product_media.html",{"product":product,"form":form,"screenshots":product.screenshots.all(),"document":ProductDocument.objects.filter(product=product).first()})

@staff_required
@require_POST
def management_screenshot_delete(request,pk):
    screenshot=get_object_or_404(ProductScreenshot,pk=pk)
    product_pk=screenshot.product_id
    screenshot.image.delete(save=False)
    screenshot.delete()
    messages.success(request,"Screenshot removed.")
    return redirect("management_product_media",pk=product_pk)

@staff_required
@require_POST
def management_document_delete(request,pk):
    product=get_object_or_404(Product,pk=pk)
    doc=ProductDocument.objects.filter(product=product).first()
    if doc:
        doc.pdf.delete(save=False)
        doc.delete()
    return redirect("management_product_media",pk=pk)

@staff_required
def management_private_pdf(request,pk):
    from django.http import FileResponse, Http404
    doc=get_object_or_404(ProductDocument,product_id=pk)
    if not doc.pdf: raise Http404()
    return FileResponse(doc.pdf.open("rb"),content_type="application/pdf",as_attachment=True,filename="documentation.pdf")

@user_passes_test(lambda u:u.is_authenticated,login_url="customer_login")
def github_connect(request):
    if not settings.GITHUB_APP_CLIENT_ID or not settings.GITHUB_APP_CLIENT_SECRET:
        messages.error(request,"GitHub connection is not configured yet.")
        return redirect("customer_dashboard")
    from urllib.parse import urlencode
    state=secrets.token_urlsafe(32)
    request.session["github_oauth_state"]=state
    redirect_uri=request.build_absolute_uri(reverse("github_callback"))
    params=urlencode({"client_id":settings.GITHUB_APP_CLIENT_ID,"redirect_uri":redirect_uri,"state":state})
    return redirect("https://github.com/login/oauth/authorize?"+params)

@user_passes_test(lambda u:u.is_authenticated,login_url="customer_login")
def github_callback(request):
    state=request.session.pop("github_oauth_state",None)
    if not state or not secrets.compare_digest(state,request.GET.get("state","")) or not request.GET.get("code"):
        messages.error(request,"GitHub authorization failed. Please try again.")
        return redirect("customer_dashboard")
    try:
        token_response=requests.post("https://github.com/login/oauth/access_token",data={
            "client_id":settings.GITHUB_APP_CLIENT_ID,
            "client_secret":settings.GITHUB_APP_CLIENT_SECRET,
            "code":request.GET["code"],
            "redirect_uri":request.build_absolute_uri(reverse("github_callback")),
        },headers={"Accept":"application/json"},timeout=12)
        token_response.raise_for_status()
        token=token_response.json().get("access_token")
        if not token:
            result = token_response.json()

            import logging
            logging.error(
                "GitHub OAuth token exchange rejected: %s - %s",
                result.get("error", "unknown"),
                result.get("error_description", "No description")
            )

            raise ValueError("GitHub token exchange failed")
        response = requests.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "AKLYTE",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
        response.raise_for_status()
        github = response.json()
        response.raise_for_status()
        github=response.json()
        gid=int(github["id"])
        if CustomerProfile.objects.filter(github_user_id=gid).exclude(user=request.user).exists():
            messages.error(request,"This GitHub account is already linked to another customer.")
            return redirect("customer_dashboard")
        profile,_=CustomerProfile.objects.get_or_create(user=request.user)
        profile.github_user_id=gid
        profile.github_username=github["login"]
        profile.github_connected_at=timezone.now()
        profile.save()
        messages.success(request,"GitHub account verified and connected.")
    except Exception:
        import logging
        logging.exception("GITHUB OAUTH ERROR")
        messages.error(
            request,
            "GitHub connection failed. Please try again."
        )
    return redirect("customer_dashboard")

@user_passes_test(lambda u:u.is_authenticated,login_url="customer_login")
@require_POST
def github_disconnect(request):
    profile,_=CustomerProfile.objects.get_or_create(user=request.user)
    profile.github_user_id=None
    profile.github_username=""
    profile.github_connected_at=None
    profile.save()
    messages.success(request,"GitHub account disconnected.")
    return redirect("customer_dashboard")


# Customer cart and order workflow (payment integration is a later phase).
def _get_user_cart(user):
    cart, _ = Cart.objects.get_or_create(user=user)
    return cart

@user_passes_test(lambda u: u.is_authenticated and u.is_active, login_url="customer_login")
def cart_detail(request):
    cart = _get_user_cart(request.user)
    items = cart.items.select_related("product", "product__category")
    return render(request, "commerce/cart.html", {"cart": cart, "items": items})

@user_passes_test(lambda u: u.is_authenticated and u.is_active, login_url="customer_login")
@require_POST
def cart_add(request, product_id):
    product = get_object_or_404(Product, pk=product_id, status=Product.PUBLISHED)
    cart = _get_user_cart(request.user)
    item, created = CartItem.objects.get_or_create(cart=cart, product=product, defaults={"quantity": 1})
    if not created:
        if item.quantity < 10:
            item.quantity += 1
            item.save(update_fields=["quantity"])
        else:
            messages.warning(request, "Maximum quantity for one project is 10.")
    else:
        messages.success(request, f"{product.name} was added to your cart.")
    return redirect("cart_detail")

@user_passes_test(lambda u: u.is_authenticated and u.is_active, login_url="customer_login")
@require_POST
def cart_update(request, item_id):
    cart = _get_user_cart(request.user)
    item = get_object_or_404(CartItem, pk=item_id, cart=cart)
    try:
        quantity = int(request.POST.get("quantity", "1"))
    except (TypeError, ValueError):
        quantity = 1
    if quantity < 1:
        item.delete()
    elif quantity > 10:
        messages.error(request, "Maximum quantity for one project is 10.")
    else:
        item.quantity = quantity
        item.save(update_fields=["quantity"])
        messages.success(request, "Cart updated.")
    return redirect("cart_detail")

@user_passes_test(lambda u: u.is_authenticated and u.is_active, login_url="customer_login")
@require_POST
def cart_remove(request, item_id):
    cart = _get_user_cart(request.user)
    item = get_object_or_404(CartItem, pk=item_id, cart=cart)
    item.delete()
    messages.success(request, "Item removed from cart.")
    return redirect("cart_detail")

@user_passes_test(lambda u: u.is_authenticated and u.is_active, login_url="customer_login")
def checkout_review(request):
    cart = _get_user_cart(request.user)
    items = list(cart.items.select_related("product").filter(product__status=Product.PUBLISHED))
    if not items:
        messages.info(request, "Your cart is empty. Add a project before checkout.")
        return redirect("cart_detail")
    subtotal = sum((item.product.display_price * item.quantity for item in items), start=0)
    coupon = None
    discount = Decimal("0.00")
    coupon_code = request.session.get("aklyte_coupon_code", "")
    if coupon_code:
        coupon = Coupon.objects.filter(code__iexact=coupon_code).first()
        if coupon and coupon.is_valid_for(request.user, subtotal):
            if coupon.discount_type == Coupon.PERCENT:
                discount = (subtotal * coupon.value / Decimal("100")).quantize(Decimal("0.01"))
            else:
                discount = min(coupon.value, subtotal)
        else:
            request.session.pop("aklyte_coupon_code", None)
            coupon = None
            coupon_code = ""
    total = max(Decimal("0.00"), subtotal - discount)
    if request.method == "POST" and request.POST.get("action") == "apply_coupon":
        code = request.POST.get("coupon_code", "").strip().upper()
        candidate = Coupon.objects.filter(code__iexact=code).first()
        if candidate and candidate.is_valid_for(request.user, subtotal):
            request.session["aklyte_coupon_code"] = candidate.code
            messages.success(request, "Coupon applied.")
        else:
            messages.error(request, "This coupon is invalid, expired, already used, or does not meet the minimum order.")
        return redirect("checkout_review")
    if request.method == "POST" and request.POST.get("action") == "remove_coupon":
        request.session.pop("aklyte_coupon_code", None)
        return redirect("checkout_review")
    if request.method == "POST":
        with transaction.atomic():
            order = Order.objects.create(
                user=request.user,
                order_number="AK-" + timezone.now().strftime("%y%m%d") + "-" + get_random_string(6).upper(),
                subtotal=subtotal,
                total=total,
                status=Order.PENDING_PAYMENT,
            )
            for item in items:
                price = item.product.display_price
                OrderItem.objects.create(
                    order=order,
                    product=item.product,
                    product_name=item.product.name,
                    unit_price=price,
                    quantity=item.quantity,
                    line_total=price * item.quantity,
                )
            if coupon and discount > 0:
                CouponRedemption.objects.create(coupon=coupon, user=request.user, order=order, discount_amount=discount)
                coupon.usage_count += 1
                coupon.save(update_fields=["usage_count"])
            request.session.pop("aklyte_coupon_code", None)
            cart.items.all().delete()
        messages.success(request, f"Order {order.order_number} was created. Please complete your payment.")
        return redirect("order_detail", order_number=order.order_number)
    return render(request, "commerce/checkout.html", {"cart": cart, "items": items, "subtotal": subtotal, "discount": discount, "total": total, "coupon_code": coupon_code})

@user_passes_test(lambda u: u.is_authenticated and u.is_active, login_url="customer_login")
def order_list(request):
    orders = Order.objects.filter(user=request.user).prefetch_related("items")
    return render(request, "commerce/orders.html", {"orders": orders})

@user_passes_test(lambda u: u.is_authenticated and u.is_active, login_url="customer_login")
def order_detail(request, order_number):
    order = get_object_or_404(Order.objects.prefetch_related("items"), order_number=order_number, user=request.user)
    return render(request, "commerce/order_detail.html", {"order": order})

@user_passes_test(lambda u: u.is_authenticated and u.is_active, login_url="customer_login")
def customer_product_documentation(request, order_number, item_id):
    from django.http import FileResponse, Http404

    order = get_object_or_404(
        Order,
        order_number=order_number,
        user=request.user
    )

    if order.status != Order.PAID:
        raise Http404("Documentation is not available.")

    item = get_object_or_404(
        OrderItem,
        order=order,
        pk=item_id
    )

    document = get_object_or_404(
        ProductDocument,
        product_id=item.product_id
    )

    if not document.pdf:
        raise Http404("Documentation not found.")

    return FileResponse(
        document.pdf.open("rb"),
        content_type="application/pdf",
        as_attachment=True,
        filename="documentation.pdf"
    )


@user_passes_test(lambda u: u.is_authenticated and u.is_active, login_url="customer_login")
def support_ticket_list(request):
    tickets = SupportTicket.objects.filter(user=request.user).select_related("order")
    return render(request, "accounts/support_tickets.html", {"tickets": tickets})


@user_passes_test(lambda u: u.is_authenticated and u.is_active, login_url="customer_login")
def support_ticket_create(request):
    orders = Order.objects.filter(user=request.user)
    if request.method == "POST":
        subject = request.POST.get("subject", "").strip()
        message = request.POST.get("message", "").strip()
        order_id = request.POST.get("order_id", "").strip()
        order = orders.filter(pk=order_id).first() if order_id else None
        if not subject or not message or len(subject) > 160 or len(message) > 5000:
            messages.error(request, "Enter a subject and message within the allowed limits.")
        else:
            ticket = SupportTicket.objects.create(user=request.user, order=order, subject=subject, message=message)
            messages.success(request, f"Support ticket #{ticket.pk} was submitted.")
            return redirect("support_ticket_list")
    return render(request, "accounts/support_ticket_form.html", {"orders": orders})


@user_passes_test(lambda u: u.is_authenticated and u.is_active, login_url="customer_login")
def support_ticket_detail(request, ticket_id):
    ticket = get_object_or_404(SupportTicket, pk=ticket_id, user=request.user)
    return render(request, "accounts/support_ticket_detail.html", {"ticket": ticket})


@user_passes_test(lambda u: u.is_authenticated and u.is_active, login_url="customer_login")
def product_review_create(request, order_item_id):
    item = get_object_or_404(OrderItem.objects.select_related("order", "product"), pk=order_item_id, order__user=request.user, order__status=Order.PAID)
    if ProductReview.objects.filter(order_item=item).exists():
        messages.info(request, "You have already reviewed this purchase.")
        return redirect("order_detail", order_number=item.order.order_number)
    if request.method == "POST":
        try:
            rating = int(request.POST.get("rating", "0"))
        except ValueError:
            rating = 0
        body = request.POST.get("body", "").strip()
        title = request.POST.get("title", "").strip()
        if rating not in range(1, 6) or not body or len(body) > 2000 or len(title) > 120:
            messages.error(request, "Choose a rating from 1 to 5 and enter a review.")
        else:
            ProductReview.objects.create(product=item.product, user=request.user, order_item=item, rating=rating, title=title, body=body)
            messages.success(request, "Thank you. Your review will appear after moderation.")
            return redirect("order_detail", order_number=item.order.order_number)
    return render(request, "accounts/review_form.html", {"item": item})



@staff_role_required(AdminProfile.SUPER_ADMIN, AdminProfile.SUPPORT_MANAGER)
def management_support_tickets(request):
    all_tickets = SupportTicket.objects.select_related("user", "order")

    if request.method == "POST":
        ticket = get_object_or_404(
            SupportTicket,
            pk=request.POST.get("ticket_id")
        )

        status = request.POST.get("status")
        priority = request.POST.get("priority")
        response_text = request.POST.get("staff_response", "").strip()

        valid_status = status in dict(SupportTicket.STATUS_CHOICES)
        valid_priority = priority in dict(SupportTicket.PRIORITY_CHOICES)

        if valid_status and valid_priority and len(response_text) <= 5000:
            ticket.status = status
            ticket.priority = priority
            ticket.staff_response = response_text

            ticket.save(update_fields=[
                "status",
                "priority",
                "staff_response",
                "updated_at",
            ])

            record_audit(
                request,
                "support.ticket.updated",
                ticket,
                f"Updated support request #{ticket.pk}"
            )

            messages.success(request, "Support request updated.")
        else:
            messages.error(request, "Invalid status, priority, or response.")

        return redirect("management_support_tickets")

    query = request.GET.get("q", "").strip()
    selected_status = request.GET.get("status", "")
    selected_priority = request.GET.get("priority", "")

    tickets = all_tickets

    if query:
        tickets = tickets.filter(
            Q(subject__icontains=query) |
            Q(message__icontains=query) |
            Q(user__username__icontains=query) |
            Q(user__email__icontains=query) |
            Q(order__order_number__icontains=query)
        )

    if selected_status in dict(SupportTicket.STATUS_CHOICES):
        tickets = tickets.filter(status=selected_status)

    if selected_priority in dict(SupportTicket.PRIORITY_CHOICES):
        tickets = tickets.filter(priority=selected_priority)

    context = {
        "tickets": tickets,
        "query": query,
        "selected_status": selected_status,
        "selected_priority": selected_priority,
        "status_choices": SupportTicket.STATUS_CHOICES,
        "priority_choices": SupportTicket.PRIORITY_CHOICES,

        "total_tickets": all_tickets.count(),
        "open_count": all_tickets.filter(
            status=SupportTicket.OPEN
        ).count(),
        "in_progress_count": all_tickets.filter(
            status=SupportTicket.IN_PROGRESS
        ).count(),
        "resolved_count": all_tickets.filter(
            status=SupportTicket.RESOLVED
        ).count(),
    }

    return render(
        request,
        "management/support_tickets.html",
        context
    )




@staff_role_required(AdminProfile.SUPER_ADMIN, AdminProfile.PRODUCT_MANAGER)
def management_reviews(request):
    all_reviews = ProductReview.objects.select_related(
        "product", "user", "order_item"
    )

    if request.method == "POST":
        review = get_object_or_404(
            ProductReview,
            pk=request.POST.get("review_id")
        )

        action = request.POST.get("action")

        if action == "approve":
            review.approved = True
            review.save(update_fields=["approved"])
            record_audit(request, "review.approved", review, f"Published review #{review.pk}")
            messages.success(request, "Review published.")

        elif action == "unpublish":
            review.approved = False
            review.save(update_fields=["approved"])
            record_audit(request, "review.unpublished", review, f"Unpublished review #{review.pk}")
            messages.success(request, "Review unpublished.")

        elif action == "delete":
            record_audit(request, "review.deleted", review, f"Deleted review #{review.pk}")
            review.delete()
            messages.success(request, "Review deleted.")

        return redirect("management_reviews")

    query = request.GET.get("q", "").strip()
    selected_status = request.GET.get("status", "")

    reviews = all_reviews

    if query:
        reviews = reviews.filter(
            Q(product__name__icontains=query) |
            Q(reviewer_name__icontains=query) |
            Q(title__icontains=query) |
            Q(body__icontains=query)
        )

    if selected_status == "published":
        reviews = reviews.filter(approved=True)
    elif selected_status == "unpublished":
        reviews = reviews.filter(approved=False)

    return render(request, "management/reviews.html", {
        "reviews": reviews,
        "query": query,
        "selected_status": selected_status,
        "total_reviews": all_reviews.count(),
        "published_count": all_reviews.filter(approved=True).count(),
        "unpublished_count": all_reviews.filter(approved=False).count(),
    })


@staff_role_required(AdminProfile.SUPER_ADMIN, AdminProfile.PRODUCT_MANAGER)
def management_review_create(request):
    products = Product.objects.all().order_by("name")

    if request.method == "POST":
        product = get_object_or_404(
            Product,
            pk=request.POST.get("product_id")
        )

        reviewer_name = request.POST.get("reviewer_name", "").strip()
        title = request.POST.get("title", "").strip()
        body = request.POST.get("body", "").strip()

        try:
            rating = int(request.POST.get("rating", "0"))
        except (TypeError, ValueError):
            rating = 0

        if not reviewer_name or len(reviewer_name) > 100:
            messages.error(request, "Enter a reviewer name (maximum 100 characters).")
        elif rating not in range(1, 6):
            messages.error(request, "Select a rating from 1 to 5.")
        elif not body or len(body) > 2000:
            messages.error(request, "Enter a review (maximum 2000 characters).")
        elif len(title) > 120:
            messages.error(request, "Review title must be 120 characters or fewer.")
        else:
            review = ProductReview.objects.create(
                product=product,
                reviewer_name=reviewer_name,
                rating=rating,
                title=title,
                body=body,
                approved=request.POST.get("publish") == "yes",
            )

            record_audit(
                request,
                "review.created",
                review,
                f"Created review for {product.name}"
            )

            messages.success(request, "Product review created.")
            return redirect("management_reviews")

    return render(request, "management/review_form.html", {
        "products": products,
        "review": None,
    })


@staff_role_required(AdminProfile.SUPER_ADMIN, AdminProfile.PRODUCT_MANAGER)
def management_review_edit(request, pk):
    review = get_object_or_404(ProductReview, pk=pk)
    products = Product.objects.all().order_by("name")

    if request.method == "POST":
        product = get_object_or_404(
            Product,
            pk=request.POST.get("product_id")
        )

        reviewer_name = request.POST.get("reviewer_name", "").strip()
        title = request.POST.get("title", "").strip()
        body = request.POST.get("body", "").strip()

        try:
            rating = int(request.POST.get("rating", "0"))
        except (TypeError, ValueError):
            rating = 0

        if not reviewer_name or len(reviewer_name) > 100:
            messages.error(request, "Enter a reviewer name (maximum 100 characters).")
        elif rating not in range(1, 6):
            messages.error(request, "Select a rating from 1 to 5.")
        elif not body or len(body) > 2000:
            messages.error(request, "Enter a review (maximum 2000 characters).")
        elif len(title) > 120:
            messages.error(request, "Review title must be 120 characters or fewer.")
        else:
            review.product = product
            review.reviewer_name = reviewer_name
            review.rating = rating
            review.title = title
            review.body = body
            review.approved = request.POST.get("publish") == "yes"

            review.save()

            record_audit(
                request,
                "review.updated",
                review,
                f"Updated review #{review.pk}"
            )

            messages.success(request, "Review updated.")
            return redirect("management_reviews")

    return render(request, "management/review_form.html", {
        "products": products,
        "review": review,
    })


@staff_role_required(AdminProfile.SUPER_ADMIN, AdminProfile.ORDER_MANAGER)
def management_payments(request):
    payments = Payment.objects.select_related(
        "order",
        "order__user"
    ).order_by("-created_at")

    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    if query:
        payments = payments.filter(
            Q(provider_order_id__icontains=query) |
            Q(provider_payment_id__icontains=query) |
            Q(order__order_number__icontains=query) |
            Q(order__user__username__icontains=query) |
            Q(order__user__email__icontains=query)
        )

    if status in dict(Payment.STATUS_CHOICES):
        payments = payments.filter(status=status)

    # Convert paise into rupees for display.
    for payment in payments:
        payment.amount_rupees = Decimal(payment.amount_paise) / Decimal("100")

    context = {
        "payments": payments,
        "query": query,
        "selected_status": status,
        "status_choices": Payment.STATUS_CHOICES,
        "total_payments": payments.count(),
        "captured_count": payments.filter(status=Payment.CAPTURED).count(),
        "failed_count": payments.filter(status=Payment.FAILED).count(),
        "pending_count": payments.filter(
            status__in=[Payment.CREATED, Payment.AUTHORIZED]
        ).count(),
    }

    return render(request, "management/payments.html", context)

@staff_role_required(AdminProfile.SUPER_ADMIN, AdminProfile.ORDER_MANAGER)
def management_orders(request):
    orders = Order.objects.select_related("user").prefetch_related(
        "items",
        "payments"
    )

    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    if query:
        orders = orders.filter(
            Q(order_number__icontains=query) |
            Q(user__username__icontains=query) |
            Q(user__email__icontains=query)
        )

    if status in dict(Order.STATUS_CHOICES):
        orders = orders.filter(status=status)

    return render(request, "management/orders.html", {
        "orders": orders,
        "query": query,
        "selected_status": status,
        "status_choices": Order.STATUS_CHOICES,
        "total_orders": orders.count(),
    })


@staff_role_required(AdminProfile.SUPER_ADMIN, AdminProfile.ORDER_MANAGER)
def management_order_detail(request, order_number):
    order = get_object_or_404(
        Order.objects.select_related("user").prefetch_related(
            "items__product",
            "payments",
        ),
        order_number=order_number
    )

    return render(request, "management/order_detail.html", {
        "order": order,
    })

# Razorpay payment integration. Never trust the browser's success callback alone.
def _razorpay_configured():
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)

def _amount_to_paise(amount):
    return int((Decimal(amount) * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def _razorpay_auth():
    return (settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)


def _mark_payment_captured(
    payment,
    provider_payment_id,
    signature_verified=False,
    webhook_verified=False,
    raw_event=None,
):
    """Mark a verified payment as captured and trigger fulfillment once per order."""
    with transaction.atomic():
        locked = Payment.objects.select_for_update().get(pk=payment.pk)

        if locked.status != Payment.CAPTURED:
            locked.status = Payment.CAPTURED
            locked.provider_payment_id = (
                provider_payment_id or locked.provider_payment_id
            )
            locked.signature_verified = (
                locked.signature_verified or signature_verified
            )
            locked.webhook_verified = (
                locked.webhook_verified or webhook_verified
            )
            if raw_event is not None:
                locked.raw_event = raw_event
            locked.save()
        else:
            changed = False

            if provider_payment_id and not locked.provider_payment_id:
                locked.provider_payment_id = provider_payment_id
                changed = True

            if signature_verified and not locked.signature_verified:
                locked.signature_verified = True
                changed = True

            if webhook_verified and not locked.webhook_verified:
                locked.webhook_verified = True
                changed = True

            if raw_event is not None:
                locked.raw_event = raw_event
                changed = True

            if changed:
                locked.save()

        order = Order.objects.select_for_update().get(pk=locked.order_id)

        # Only the transaction that changes the order to PAID triggers fulfillment.
        newly_paid = order.status != Order.PAID

        if newly_paid:
            order.status = Order.PAID
            order.save(update_fields=["status", "updated_at"])

            from .github_delivery import deliver_paid_order
            from .notifications import send_customer_email

            def _after_payment_commit(order_id=order.pk):
                paid_order = Order.objects.select_related("user").get(pk=order_id)

                send_customer_email(
                    paid_order.user,
                    f"Payment confirmed — {paid_order.order_number}",
                    (
                        f"Hello {paid_order.user.username},\n\n"
                        f"We have confirmed your payment for AKLYTE order "
                        f"{paid_order.order_number}.\n"
                        f"Total: {paid_order.currency} {paid_order.total}\n\n"
                        "You can view your order and repository delivery "
                        "status from your AKLYTE account."
                    ),
                )

                deliver_paid_order(paid_order)

            transaction.on_commit(_after_payment_commit)

    return locked

@user_passes_test(lambda u: u.is_authenticated and u.is_active, login_url="customer_login")
@require_POST
def razorpay_create_payment(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    if order.status == Order.PAID:
        messages.info(request, "This order is already paid.")
        return redirect("order_detail", order_number=order.order_number)
    if order.status != Order.PENDING_PAYMENT:
        messages.error(request, "This order is not eligible for payment.")
        return redirect("order_detail", order_number=order.order_number)
    if not _razorpay_configured():
        messages.error(request, "Razorpay is not configured. Add your test credentials to .env.")
        return redirect("order_detail", order_number=order.order_number)

    existing = order.payments.filter(status=Payment.CREATED).first()
    if existing:
        payment = existing
    else:
        amount_paise = _amount_to_paise(order.total)
        payload = {
            "amount": amount_paise,
            "currency": order.currency,
            "receipt": order.order_number,
            "notes": {"aklyte_order_number": order.order_number},
        }
        try:
            response = requests.post(
                "https://api.razorpay.com/v1/orders",
                auth=_razorpay_auth(),
                json=payload,
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
            payment = Payment.objects.create(
                order=order,
                provider_order_id=data["id"],
                amount_paise=amount_paise,
                currency=order.currency,
                status=Payment.CREATED,
                raw_event={"creation_response": data},
            )
        except (requests.RequestException, ValueError, KeyError):
            messages.error(request, "Unable to start payment with Razorpay. Please try again.")
            return redirect("order_detail", order_number=order.order_number)

    return render(request, "commerce/razorpay_checkout.html", {
        "order": order,
        "payment": payment,
        "razorpay_key_id": settings.RAZORPAY_KEY_ID,
        "customer_name": request.user.get_full_name() or request.user.username,
        "customer_email": request.user.email,
    })

@user_passes_test(lambda u: u.is_authenticated and u.is_active, login_url="customer_login")
@require_POST
def razorpay_payment_callback(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    provider_order_id = request.POST.get("razorpay_order_id", "")
    provider_payment_id = request.POST.get("razorpay_payment_id", "")
    supplied_signature = request.POST.get("razorpay_signature", "")
    payment = get_object_or_404(Payment, order=order, provider_order_id=provider_order_id)
    message = f"{provider_order_id}|{provider_payment_id}".encode("utf-8")
    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    if not (provider_payment_id and supplied_signature and hmac.compare_digest(expected, supplied_signature)):
        messages.error(request, "Payment verification failed. Your order has not been marked paid.")
        return redirect("order_detail", order_number=order.order_number)
    # A valid checkout signature proves the response belongs to this Razorpay order,
    # but we also fetch the payment from Razorpay and require captured status before
    # marking the customer's order as paid.
    try:
        verify_response = requests.get(
            f"https://api.razorpay.com/v1/payments/{provider_payment_id}",
            auth=_razorpay_auth(),
            timeout=20,
        )
        verify_response.raise_for_status()
        remote_payment = verify_response.json()
        if (
            remote_payment.get("order_id") != payment.provider_order_id
            or int(remote_payment.get("amount", -1)) != payment.amount_paise
            or remote_payment.get("currency") != payment.currency
        ):
            messages.error(request, "Payment details did not match this order. It has not been marked paid.")
            return redirect("order_detail", order_number=order.order_number)
        if remote_payment.get("status") == "captured":
            _mark_payment_captured(
                payment, provider_payment_id, signature_verified=True,
                raw_event={"payment_fetch": remote_payment}
            )
            messages.success(request, "Payment verified and captured successfully.")
        elif remote_payment.get("status") == "authorized":
            payment.status = Payment.AUTHORIZED
            payment.provider_payment_id = provider_payment_id
            payment.signature_verified = True
            payment.raw_event = {"payment_fetch": remote_payment}
            payment.save()
            messages.info(request, "Payment is authorized and awaiting capture confirmation. Your order is not marked paid yet.")
        else:
            payment.status = Payment.FAILED
            payment.failure_reason = str(remote_payment.get("error_description") or remote_payment.get("status") or "Payment not captured")[:500]
            payment.provider_payment_id = provider_payment_id
            payment.signature_verified = True
            payment.raw_event = {"payment_fetch": remote_payment}
            payment.save()
            messages.error(request, "Razorpay has not confirmed a captured payment. Your order remains unpaid.")
    except (requests.RequestException, ValueError, TypeError):
        messages.error(request, "We could not confirm the payment status with Razorpay. Your order has not been marked paid.")
    return redirect("order_detail", order_number=order.order_number)


@csrf_exempt
@require_POST
def razorpay_webhook(request):
    secret = settings.RAZORPAY_WEBHOOK_SECRET

    if not secret:
        return HttpResponseBadRequest("Webhook secret is not configured.")

    supplied = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(
        secret.encode("utf-8"),
        request.body,
        hashlib.sha256,
    ).hexdigest()

    if not supplied or not hmac.compare_digest(expected, supplied):
        return HttpResponseBadRequest("Invalid webhook signature.")

    try:
        event = json.loads(request.body.decode("utf-8"))
        event_name = event.get("event", "")
        payload = event.get("payload", {})

        if not isinstance(payload, dict):
            return HttpResponseBadRequest("Invalid webhook payload.")

    except (ValueError, UnicodeDecodeError, AttributeError):
        return HttpResponseBadRequest("Invalid webhook payload.")

    if event_name == "payment.captured":
        entity = payload.get("payment", {}).get("entity", {})

        if not isinstance(entity, dict):
            return HttpResponseBadRequest("Invalid payment entity.")

        provider_order_id = entity.get("order_id")
        provider_payment_id = entity.get("id")
        amount = entity.get("amount")
        currency = entity.get("currency")

        if not all((provider_order_id, provider_payment_id, amount, currency)):
            return HttpResponseBadRequest("Incomplete captured payment details.")

        try:
            amount = int(amount)
        except (ValueError, TypeError):
            return HttpResponseBadRequest("Invalid payment amount.")

        payment = Payment.objects.filter(
            provider_order_id=provider_order_id
        ).first()

        if not payment:
            return HttpResponse("ok", status=200)

        if amount != payment.amount_paise:
            return HttpResponseBadRequest("Payment amount mismatch.")

        if currency != payment.currency:
            return HttpResponseBadRequest("Payment currency mismatch.")

        if (
            payment.provider_payment_id
            and payment.provider_payment_id != provider_payment_id
        ):
            return HttpResponseBadRequest("Payment ID mismatch.")

        _mark_payment_captured(
            payment,
            provider_payment_id,
            webhook_verified=True,
            raw_event=event,
        )

    elif event_name == "payment.failed":
        entity = payload.get("payment", {}).get("entity", {})

        if not isinstance(entity, dict):
            return HttpResponseBadRequest("Invalid payment entity.")

        provider_order_id = entity.get("order_id")

        if not provider_order_id:
            return HttpResponseBadRequest("Missing Razorpay order ID.")

        with transaction.atomic():
            payment = Payment.objects.select_for_update().filter(
                provider_order_id=provider_order_id
            ).first()

            if payment:
                order = Order.objects.select_for_update().get(
                    pk=payment.order_id
                )

                if (
                    payment.status != Payment.CAPTURED
                    and order.status != Order.PAID
                    and payment.status != Payment.FAILED
                ):
                    payment.status = Payment.FAILED
                    payment.failure_reason = str(
                        entity.get("error_description", "Payment failed")
                    )[:500]
                    payment.raw_event = event
                    payment.save()

                    if order.status == Order.PENDING_PAYMENT:
                        order.status = Order.PAYMENT_FAILED
                        order.save(
                            update_fields=["status", "updated_at"]
                        )

                    from .notifications import send_customer_email

                    def notify_failure(order_id=order.pk):
                        failed_order = Order.objects.select_related(
                            "user"
                        ).get(pk=order_id)

                        send_customer_email(
                            failed_order.user,
                            f"Payment not completed — {failed_order.order_number}",
                            (
                                f"Hello {failed_order.user.username},\n\n"
                                f"Razorpay reported that payment for AKLYTE "
                                f"order {failed_order.order_number} failed.\n\n"
                                "You can revisit your order in your AKLYTE "
                                "account and try again.\n\n"
                                "No GitHub repository access has been "
                                "granted for this unpaid order."
                            ),
                        )

                    transaction.on_commit(notify_failure)

    return HttpResponse("ok", status=200)

@user_passes_test(lambda u: u.is_authenticated and u.is_active, login_url="customer_login")
def github_access_list(request):
    accesses = GitHubAccess.objects.filter(customer=request.user).select_related("order_item", "order_item__order", "order_item__product")
    return render(request, "accounts/github_access.html", {"accesses": accesses})

@user_passes_test(lambda u: u.is_authenticated and u.is_active, login_url="customer_login")
@require_POST
def github_access_refresh(request, access_id):
    access = get_object_or_404(GitHubAccess, pk=access_id, customer=request.user)
    try:
        from .github_delivery import refresh_repository_access, GitHubDeliveryError
        refresh_repository_access(access)
        if access.status == GitHubAccess.ACTIVE:
            messages.success(request, "GitHub repository access is active.")
        else:
            messages.info(request, "Invitation is still pending. Accept it in your GitHub account, then check again.")
    except (GitHubDeliveryError, requests.RequestException, ValueError) as exc:
        messages.error(request, f"Could not refresh access status: {str(exc)[:180]}")
    return redirect("github_access_list")

@staff_role_required(AdminProfile.SUPER_ADMIN, AdminProfile.SUPPORT_MANAGER)
@require_POST
def management_github_retry(request, access_id):
    access = get_object_or_404(GitHubAccess, pk=access_id)
    record_audit(request, "github.delivery.retry", access, "Staff retried GitHub repository invitation")
    if access.order_item.order.status != Order.PAID:
        messages.error(request, "Access cannot be granted before payment is verified.")
        return redirect("management_dashboard")
    try:
        from .github_delivery import send_repository_invitation, GitHubDeliveryError
        send_repository_invitation(access)
        messages.success(request, "GitHub invitation request processed.")
    except (GitHubDeliveryError, requests.RequestException, ValueError) as exc:
        access.status = GitHubAccess.FAILED
        access.last_error = str(exc)[:500]
        access.save(update_fields=["status", "last_error", "updated_at"])
        messages.error(request, f"GitHub delivery failed: {str(exc)[:180]}")
    return redirect("management_github_access")

@staff_required
def management_github_access(request):
    accesses = GitHubAccess.objects.select_related("customer", "order_item", "order_item__order", "order_item__product")
    return render(request, "management/github_access.html", {"accesses": accesses})


def about(request):
    return render(request, "storefront/about.html")


def contact(request):
    return render(request, "storefront/contact.html")


def help_center(request):
    return render(request, "storefront/help_center.html")


def faqs(request):
    return render(request, "storefront/faqs.html")


def privacy_policy(request):
    return render(request, "storefront/privacy_policy.html")
