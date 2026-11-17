from django.urls import path
from . import views

urlpatterns = [
    path("cart/", views.cart_detail, name="cart_detail"),
    path("account/support/", views.support_ticket_list, name="support_ticket_list"),
    path("account/support/new/", views.support_ticket_create, name="support_ticket_create"),
    path("account/support/<int:ticket_id>/", views.support_ticket_detail, name="support_ticket_detail"),
    path("account/review/<int:order_item_id>/", views.product_review_create, name="product_review_create"),

    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("help/", views.help_center, name="help_center"),
    path("faqs/", views.faqs, name="faqs"),
    path("privacy-policy/", views.privacy_policy, name="privacy_policy"),

    path("management/support/", views.management_support_tickets, name="management_support_tickets"),
    path("management/reviews/", views.management_reviews, name="management_reviews"),
    path(
        "management/reviews/add/",
        views.management_review_create,
        name="management_review_create"
    ),

    path(
        "management/reviews/<int:pk>/edit/",
        views.management_review_edit,
        name="management_review_edit"
    ),
    path("cart/add/<int:product_id>/", views.cart_add, name="cart_add"),
    path("cart/item/<int:item_id>/update/", views.cart_update, name="cart_update"),
    path("cart/item/<int:item_id>/remove/", views.cart_remove, name="cart_remove"),
    path("checkout/", views.checkout_review, name="checkout_review"),
    path("payments/razorpay/webhook/", views.razorpay_webhook, name="razorpay_webhook"),
    path("payments/razorpay/<str:order_number>/create/", views.razorpay_create_payment, name="razorpay_create_payment"),
    path("payments/razorpay/<str:order_number>/callback/", views.razorpay_payment_callback, name="razorpay_payment_callback"),
    path("account/orders/", views.order_list, name="order_list"),
    path("account/github-access/", views.github_access_list, name="github_access_list"),
    path("account/github-access/<int:access_id>/refresh/", views.github_access_refresh, name="github_access_refresh"),
    path("account/orders/<str:order_number>/", views.order_detail, name="order_detail"),
    path("account/orders/<str:order_number>/items/<int:item_id>/documentation/",
    views.customer_product_documentation,
    name="customer_product_documentation"),
    path("account/register/", views.customer_register, name="customer_register"),
    path("account/verify/<uidb64>/<token>/", views.customer_verify, name="customer_verify"),
    path("account/login/", views.customer_login, name="customer_login"),
    path("account/google/login/", views.google_login, name="google_login"),
    path("account/google/callback/", views.google_callback, name="google_callback"),
    path("account/logout/", views.customer_logout, name="customer_logout"),
    path("account/", views.customer_dashboard, name="customer_dashboard"),
    path("account/profile/", views.customer_profile, name="customer_profile"),
    path("account/github/connect/", views.github_connect, name="github_connect"),
    path("account/github/callback/", views.github_callback, name="github_callback"),
    path("account/github/disconnect/", views.github_disconnect, name="github_disconnect"),
    path("management/products/<int:pk>/media/", views.management_product_media, name="management_product_media"),
    path("management/screenshots/<int:pk>/delete/", views.management_screenshot_delete, name="management_screenshot_delete"),
    path("management/products/<int:pk>/document/delete/", views.management_document_delete, name="management_document_delete"),
    path("management/products/<int:pk>/document/download/", views.management_private_pdf, name="management_private_pdf"),
    path(
        "management/orders/",
        views.management_orders,
        name="management_orders"
    ),

    path(
        "management/orders/<str:order_number>/",
        views.management_order_detail,
        name="management_order_detail"
    ),
    
    path(
        "management/customers/",
        views.management_customers,
        name="management_customers"
    ),

    path(
        "management/customers/<int:pk>/",
        views.management_customer_detail,
        name="management_customer_detail"
    ),
    path(
    "management/payments/",
    views.management_payments,
    name="management_payments"
    ),

    path("", views.home, name="home"),
    path("products/", views.product_list, name="product_list"),
    path("products/<slug:slug>/", views.product_detail, name="product_detail"),
    path("categories/<slug:slug>/", views.category_detail, name="category_detail"),
    path("health/", views.health, name="health"),
    path("management/login/", views.management_login, name="management_login"),
    path("management/logout/", views.management_logout, name="management_logout"),
    path("management/", views.management_dashboard, name="management_dashboard"),
    path("management/github-access/", views.management_github_access, name="management_github_access"),
    path("management/github-access/<int:access_id>/retry/", views.management_github_retry, name="management_github_retry"),
    path("management/products/", views.management_products, name="management_products"),
    path("management/products/add/", views.management_product_add, name="management_product_add"),
    path("management/products/<int:pk>/edit/", views.management_product_edit, name="management_product_edit"),
    path("management/products/<int:pk>/delete/", views.management_product_delete, name="management_product_delete"),
    path("management/categories/", views.management_categories, name="management_categories"),
    path("management/categories/add/", views.management_category_add, name="management_category_add"),
    path("management/categories/<int:pk>/edit/", views.management_category_edit, name="management_category_edit"),
    path("management/categories/<int:pk>/delete/", views.management_category_delete, name="management_category_delete"),
]
