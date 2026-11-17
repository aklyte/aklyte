import time
from pathlib import Path

import jwt
import requests
from django.conf import settings
from django.utils import timezone

from .models import GitHubAccess, OrderItem, CustomerProfile

API = getattr(settings, "GITHUB_API_URL", "https://api.github.com")
API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


class GitHubDeliveryError(Exception):
    pass


def _app_jwt():
    key_path = Path(settings.BASE_DIR) / settings.GITHUB_APP_PRIVATE_KEY_PATH
    if not settings.GITHUB_APP_ID or not settings.GITHUB_INSTALLATION_ID:
        raise GitHubDeliveryError("GitHub App ID or installation ID is not configured.")
    if not key_path.is_file():
        raise GitHubDeliveryError("GitHub App private key file was not found.")
    private_key = key_path.read_text(encoding="utf-8")
    now = int(time.time())
    token = jwt.encode(
        {"iat": now - 30, "exp": now + 8 * 60, "iss": str(settings.GITHUB_APP_ID)},
        private_key,
        algorithm="RS256",
    )
    return token


def _installation_token():
    app_token = _app_jwt()
    url = f"{API}/app/installations/{settings.GITHUB_INSTALLATION_ID}/access_tokens"
    response = requests.post(url, headers={**API_HEADERS, "Authorization": f"Bearer {app_token}"}, json={}, timeout=20)
    if response.status_code not in (200, 201):
        raise GitHubDeliveryError(f"GitHub installation token request failed ({response.status_code}).")
    token = response.json().get("token")
    if not token:
        raise GitHubDeliveryError("GitHub did not return an installation token.")
    return token


def _headers(token):
    return {**API_HEADERS, "Authorization": f"Bearer {token}"}


def _check_repository(token, owner, repo):
    response = requests.get(f"{API}/repos/{owner}/{repo}", headers=_headers(token), timeout=20)
    if response.status_code != 200:
        raise GitHubDeliveryError(f"Repository lookup failed ({response.status_code}). Check App access and repository mapping.")
    data = response.json()
    if data.get("private") is not True:
        raise GitHubDeliveryError("Mapped source-code repository must be private.")
    if (data.get("owner") or {}).get("login", "").lower() != settings.GITHUB_ORGANIZATION.lower():
        raise GitHubDeliveryError("Repository does not belong to the configured AKLYTE GitHub organization.")
    return data


def _profile_for_customer(user):
    try:
        profile = user.customer_profile
    except CustomerProfile.DoesNotExist:
        raise GitHubDeliveryError("Customer profile is missing.")
    if not profile.github_user_id or not profile.github_username:
        raise GitHubDeliveryError("Customer has not connected and verified a GitHub account.")
    return profile


def send_repository_invitation(access):
    if access.status == GitHubAccess.ACTIVE:
        return access
    if access.status == GitHubAccess.REVOKED:
        raise GitHubDeliveryError("This repository access has been revoked. Contact AKLYTE support.")
    profile = _profile_for_customer(access.customer)
    token = _installation_token()
    _check_repository(token, access.repo_owner, access.repo_name)

    # Avoid duplicate invitations by checking existing open repository invitations.
    invitations_response = requests.get(
        f"{API}/repos/{access.repo_owner}/{access.repo_name}/invitations",
        headers=_headers(token), timeout=20
    )
    if invitations_response.status_code == 200:
        for invitation in invitations_response.json():
            invitee = invitation.get("invitee") or {}
            if invitee.get("id") == profile.github_user_id:
                access.invitation_id = invitation.get("id")
                access.status = GitHubAccess.INVITATION_SENT
                access.github_username = profile.github_username
                access.github_user_id = profile.github_user_id
                access.invited_at = access.invited_at or timezone.now()
                access.last_error = ""
                access.save()
                return access

    response = requests.put(
        f"{API}/repos/{access.repo_owner}/{access.repo_name}/collaborators/{profile.github_username}",
        headers=_headers(token),
        json={"permission": "pull"},
        timeout=20,
    )
    if response.status_code not in (201, 204):
        raise GitHubDeliveryError(f"GitHub invitation request failed ({response.status_code}). Check repository Administration permission.")
    result = response.json() if response.content else {}
    access.invitation_id = result.get("id") or access.invitation_id
    access.github_username = profile.github_username
    access.github_user_id = profile.github_user_id
    access.status = GitHubAccess.INVITATION_SENT
    access.invited_at = timezone.now()
    access.last_error = ""
    access.save()
    from .notifications import send_customer_email
    send_customer_email(
        access.customer,
        f"GitHub invitation sent — {access.repo_name}",
        f"Hello {access.customer.username},\\n\\nAKLYTE has sent a GitHub repository invitation for {access.repo_owner}/{access.repo_name} to your connected GitHub account ({access.github_username}).\\n\\nOpen GitHub notifications or your GitHub email and accept the invitation. Then return to AKLYTE and check your GitHub access status.",
    )
    return access


def refresh_repository_access(access):
    if access.status == GitHubAccess.REVOKED:
        return access
    profile = _profile_for_customer(access.customer)
    if profile.github_user_id != access.github_user_id and access.github_user_id:
        raise GitHubDeliveryError("The connected GitHub account differs from the invited account.")
    token = _installation_token()
    _check_repository(token, access.repo_owner, access.repo_name)

    response = requests.get(
        f"{API}/repos/{access.repo_owner}/{access.repo_name}/collaborators/{profile.github_username}/permission",
        headers=_headers(token), timeout=20
    )
    if response.status_code == 200:
        became_active = access.status != GitHubAccess.ACTIVE
        access.status = GitHubAccess.ACTIVE
        access.accepted_at = access.accepted_at or timezone.now()
        access.last_error = ""
        access.save()
        if became_active:
            from .notifications import send_customer_email
            send_customer_email(
                access.customer,
                f"Repository access active — {access.repo_name}",
                f"Hello {access.customer.username},\\n\\nGitHub has confirmed your access to {access.repo_owner}/{access.repo_name}. You can now clone the repository using:\\n\\ngit clone https://github.com/{access.repo_owner}/{access.repo_name}.git\\n\\nYour AKLYTE account also shows the current delivery status.",
            )
    elif response.status_code == 404:
        # Not yet accepted / collaborator access not yet active.
        if access.status not in (GitHubAccess.PENDING, GitHubAccess.INVITATION_SENT):
            access.status = GitHubAccess.PENDING
        access.save(update_fields=["status", "updated_at"])
    else:
        raise GitHubDeliveryError(f"Could not check GitHub collaborator status ({response.status_code}).")
    return access


def create_access_records_for_paid_order(order):
    """Create one delivery record per purchased product, without trusting client input."""
    if order.status != order.PAID:
        return []
    created = []
    for item in order.items.select_related("product").all():
        owner = item.product.github_repo_owner.strip()
        repo = item.product.github_repo_name.strip()
        if not owner or not repo:
            continue
        access, _ = GitHubAccess.objects.get_or_create(
            order_item=item,
            defaults={
                "customer": order.user,
                "repo_owner": owner,
                "repo_name": repo,
                "status": GitHubAccess.PENDING,
            },
        )
        created.append(access)
    return created


def deliver_paid_order(order):
    records = create_access_records_for_paid_order(order)
    for access in records:
        try:
            send_repository_invitation(access)
        except (GitHubDeliveryError, requests.RequestException, ValueError) as exc:
            access.status = GitHubAccess.FAILED
            access.last_error = str(exc)[:500]
            access.save(update_fields=["status", "last_error", "updated_at"])
            from .notifications import send_admin_alert
            send_admin_alert(
                f"AKLYTE GitHub delivery failed — {access.repo_name}",
                f"Order: {order.order_number}\\nCustomer: {access.customer.username}\\nRepository: {access.repo_owner}/{access.repo_name}\\nError: {access.last_error}\\n\\nOpen the AKLYTE management GitHub delivery page to review and retry.",
            )
    return records
