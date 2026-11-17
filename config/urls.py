from django.urls import include, path
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("account/password/reset/", auth_views.PasswordResetView.as_view(template_name="accounts/password_form.html",email_template_name="accounts/password_reset_email.txt",success_url="/account/password/reset/done/"), name="password_reset"),
    path("account/password/reset/done/", auth_views.PasswordResetDoneView.as_view(template_name="accounts/password_done.html"), name="password_reset_done"),
    path("account/password/reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(template_name="accounts/password_form.html",success_url="/account/password/reset/complete/"), name="password_reset_confirm"),
    path("account/password/reset/complete/", auth_views.PasswordResetCompleteView.as_view(template_name="accounts/password_done.html"), name="password_reset_complete"),
    path("account/password/change/", auth_views.PasswordChangeView.as_view(template_name="accounts/password_form.html",success_url="/account/password/change/done/"), name="password_change"),
    path("account/password/change/done/", auth_views.PasswordChangeDoneView.as_view(template_name="accounts/password_done.html"), name="password_change_done"),
    path("", include("apps.core.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
