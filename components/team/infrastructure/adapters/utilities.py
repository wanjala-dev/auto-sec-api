from urllib.parse import urlencode, urlparse

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from django.contrib.sites.shortcuts import get_current_site

from components.shared_platform.infrastructure.services.core_utils import resolve_frontend_base_url

DEFAULT_INVITE_BENEFITS = [
    {
        'title': 'Team workspaces',
        'body': 'Organize initiatives, budgets, and deliverables in one shared place.',
    },
    {
        'title': 'Collaboration tools',
        'body': 'Discuss updates, assign tasks, and keep every contributor informed.',
    },
]


def _site_identity():
    fallback_name = getattr(settings, 'SITE_NAME', 'SEED')
    site_domain = ""
    try:
        site = Site.objects.get_current()
    except (ImproperlyConfigured, Site.DoesNotExist):
        site = None
    if site:
        fallback_name = site.name or fallback_name
        site_domain = site.domain or site_domain
    return fallback_name, site_domain


def _build_accept_url(code: str, email: str, site_domain: str) -> str:
    base_url = resolve_frontend_base_url(site_domain=site_domain)
    path = getattr(settings, 'TEAM_INVITE_ACCEPT_PATH', '/invite/accept') or '/invite/accept'
    path = f"/{path.lstrip('/')}"
    query = urlencode({'code': code, 'email': email})
    return f"{base_url}{path}?{query}"


def _format_inviter_name(team) -> str:
    inviter = getattr(team, 'created_by', None)
    if not inviter:
        return 'A teammate'
    full_name = getattr(inviter, 'get_full_name', lambda: '')()
    username = getattr(inviter, 'username', '') or ''
    fallback_email = getattr(inviter, 'email', '') or ''
    return (full_name or username or fallback_email or 'A teammate').strip()


def _team_initials(title: str) -> str:
    if not title:
        return 'T'
    parts = [chunk for chunk in title.split() if chunk]
    if not parts:
        return title[:2].upper()
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


PERSONA_LABELS = {
    'admin': 'Admin',
    'contributor': 'Contributor',
    'sponsor': 'Sponsor',
    'volunteer': 'Volunteer',
    'auditor': 'Auditor',
    'board_member': 'Board Member',
}


def send_persona_invitation(invitation, *, inviter_user=None, is_existing_user=False):
    """Send the magic-link email for a persona-aware invitation.

    Reuses the existing team/email_invitation.html template so the visual
    treatment matches the legacy team-invite email. When the invitation has
    no team (sponsor / auditor / board_member), we substitute the
    workspace name in the team-name slot. The accept URL points at the
    persona accept page with the magic-link token in the query string.

    ``is_existing_user`` toggles the CTA: established users see "Accept
    invite" (no password setup needed because they already have a
    password); new users see "Set password & sign in".
    """
    if invitation is None or not invitation.email:
        return False

    from_email = (
        getattr(settings, 'DEFAULT_FROM_EMAIL', None)
        or settings.EMAIL_HOST_USER
    )
    site_name, site_domain = _site_identity()
    base_url = resolve_frontend_base_url(site_domain=site_domain)
    accept_url = f"{base_url.rstrip('/')}/invite/accept?token={invitation.token}"

    persona_label = PERSONA_LABELS.get(invitation.persona, 'Member')
    team = invitation.team
    workspace = invitation.workspace
    workspace_name = (
        getattr(workspace, 'workspace_name', '') or 'this organization'
    ).strip()
    team_name = (
        getattr(team, 'title', None) or workspace_name or 'this organization'
    )
    inviter_name = 'A teammate'
    if inviter_user is not None:
        full_name = (
            getattr(inviter_user, 'get_full_name', lambda: '')() or ''
        ).strip()
        inviter_name = (
            full_name
            or getattr(inviter_user, 'username', '')
            or getattr(inviter_user, 'email', '')
            or 'A teammate'
        )
    elif team is not None:
        inviter_name = _format_inviter_name(team)

    support_email = (
        getattr(settings, 'SUPPORT_EMAIL', None)
        or getattr(settings, 'DEFAULT_FROM_EMAIL', from_email)
    )

    subject = (
        f"{inviter_name} invited you to join {workspace_name} "
        f"as a {persona_label}"
    )
    if is_existing_user:
        text_content = (
            f"{inviter_name} invited you to join {workspace_name} as a "
            f"{persona_label} on {site_name}.\n\n"
            f"You already have an account — just click below to accept "
            f"your invite:\n"
            f"{accept_url}\n\n"
            f"This link is single-use and expires in 24 hours.\n"
            f"If you have questions, reply to {support_email}."
        )
    else:
        text_content = (
            f"{inviter_name} invited you to join {workspace_name} as a "
            f"{persona_label} on {site_name}.\n\n"
            f"Click the link below to set up your account and accept "
            f"your invite:\n"
            f"{accept_url}\n\n"
            f"This link is single-use and expires in 24 hours.\n"
            f"If you have questions, reply to {support_email}."
        )
    # Template branches on password_setup_url: when present, the email
    # shows "Set Password & Sign In"; when None, it shows "Accept Invite".
    # Existing users skip the password step entirely.
    password_setup_url = None if is_existing_user else accept_url
    html_content = render_to_string(
        'team/email_invitation.html',
        {
            'code': invitation.token,
            'team_name': team_name,
            'team_initials': _team_initials(team_name or workspace_name),
            'workspace_name': workspace_name,
            'site_name': site_name,
            'site_domain': site_domain,
            'inviter_name': inviter_name,
            'team_members_label': persona_label,
            'accept_url': accept_url,
            'password_setup_url': password_setup_url,
            'is_existing_user': is_existing_user,
            'benefits': DEFAULT_INVITE_BENEFITS,
            'support_email': support_email,
            'recipient_email': invitation.email,
            'current_year': timezone.now().year,
        },
    )

    msg = EmailMultiAlternatives(
        subject, text_content, from_email, [invitation.email]
    )
    msg.attach_alternative(html_content, 'text/html')
    msg.send()
    return True


def send_invitation(to_email, code, team, *, password_setup_url=None):
    from_email = settings.EMAIL_HOST_USER
    site_name, site_domain = _site_identity()
    accept_url = _build_accept_url(code, to_email, site_domain)
    password_setup_url = (password_setup_url or "").strip()

    team_name = getattr(team, 'title', 'your team') or 'your team'
    workspace = getattr(team, 'workspace', None)
    workspace_name = getattr(workspace, 'workspace_name', '').strip() or team_name
    inviter_name = _format_inviter_name(team)
    member_count = getattr(team.members, 'count', lambda: 0)() if team else 0
    member_count = member_count or 1
    team_members_label = f"{member_count} member{'s' if member_count != 1 else ''}"
    support_email = getattr(settings, 'SUPPORT_EMAIL', None) or getattr(settings, 'DEFAULT_FROM_EMAIL', from_email)

    subject = f"{inviter_name} invited you to join {team_name} on {site_name}"
    text_content = (
        f"{inviter_name} invited you to join the {team_name} team on {site_name}.\n\n"
    )
    if password_setup_url:
        text_content += (
            f"Set your password to sign in: {password_setup_url}\n"
            f"After signing in, accept your invitation: {accept_url}\n"
        )
    else:
        text_content += f"Accept your invitation: {accept_url}\n"
    text_content += (
        f"Invitation code: {code}\n\n"
        f"Collaborate with {team_members_label} supporting {workspace_name}. "
        f"If you have questions, reply to {support_email}."
    )
    parsed_accept = urlparse(accept_url)
    html_content = render_to_string(
        'team/email_invitation.html',
        {
            'code': code,
            'team_name': team_name,
            'team_initials': _team_initials(team_name),
            'workspace_name': workspace_name,
            'site_name': site_name,
            'site_domain': site_domain or parsed_accept.netloc,
            'inviter_name': inviter_name,
            'team_members_label': team_members_label,
            'accept_url': accept_url,
            'password_setup_url': password_setup_url or None,
            'benefits': DEFAULT_INVITE_BENEFITS,
            'support_email': support_email,
            'recipient_email': to_email,
            'current_year': timezone.now().year,
        },
    )

    msg = EmailMultiAlternatives(subject, text_content, from_email, [to_email])
    msg.attach_alternative(html_content, 'text/html')
    msg.send()

def send_invitation_accepted(team, invitation):
    from_email = settings.EMAIL_HOST_USER
    subject = 'Invitation accepted'
    text_content = 'Your invitation was accepted'
    html_content = render_to_string('team/email_accepted_invitation.html', {'team': team, 'invitation': invitation})

    msg = EmailMultiAlternatives(subject, text_content, from_email, [team.created_by.email])
    msg.attach_alternative(html_content, 'text/html')
    msg.send()

def send_task_assignment_notification(request, task, user, team):
    """
    Sends an email notification to a user when they are assigned to a task
    within a team, including a formatted link to the task using the current site domain.
    """
    from_email = settings.EMAIL_HOST_USER
    subject = f'You have been assigned to the task "{task.title}" in team "{team.title}"'
    current_site = get_current_site(request).domain
    task_link = f'http://{current_site}/dashboard/{task.workspace_id}'

    text_content = f'You have been assigned to the task "{task.title}" in the team "{team.title}". ' \
                   f'You can view the task details here: {task_link}'
    html_content = render_to_string('team/email_task_assignment.html', {
        'task': task,
        'user': user,
        'team': team,
        'task_link': task_link,
    })

    msg = EmailMultiAlternatives(subject, text_content, from_email, [user.email])
    msg.attach_alternative(html_content, 'text/html')
    msg.send()
