# Accounts refactor - implementation

This implements section 18 of the discussion doc ("what I'd change right now"):
User stays auth-only; organization/role move to `Membership`; `UserProfile`,
`PhoneNumber`, `IdentityDocument`, `EmployeeProfile`, `Invitation` are added.
`Role` is a DB model (system roles shared across businesses, `organization=None`)
rather than a hardcoded `ROLE_CHOICES` list, since `Membership.role` needs
something to point at. Deliberately NOT built: the granular `Permission`
model, `UserSession`, `AuditLog` - those are explicitly later-stage items
in the doc, not part of the "right now" list.

## Files

```
accounts/
  models/
    __init__.py        re-exports everything - `from accounts.models import X` still works
    user.py             User: auth only now, + backward-compat .organization/.role properties
    role.py              Role: system roles (org=None) + per-org custom roles
    membership.py         Membership: the User <-> Organization <-> Role link
    profile.py             UserProfile: personal identity
    phone.py                 PhoneNumber
    identity.py                IdentityDocument
    employee.py                  EmployeeProfile: tied to Membership, not User
    invitation.py                 Invitation: link-based onboarding, no email/SMS gateway needed
  migrations/
    0002_seed_default_roles.py       seeds the 4 system roles - template, fix `dependencies`
    0003_backfill_memberships.py     copies existing User.organization/role into Membership - template, fix `dependencies`
  forms.py     SignupForm now creates Profile+Membership; EmployeeInviteForm replaced by InviteEmployeeForm (creates an Invitation) + AcceptInvitationForm
  views.py     TeamListView/ToggleEmployeeActiveView now operate on Membership; added AcceptInvitationView (public)
  admin.py     inlines for the new related models, Membership/Role/Invitation/EmployeeProfile registered
  urls.py      added /invite/<token>/

core/
  middleware.py            added CurrentMembershipMiddleware - sets request.membership / request.organization every request
  permissions.py           RoleRequiredMixin / OrganizationMixin read request.membership now; both independently redirect anonymous users instead of relying on mixin ordering
  context_processors.py    reads request.organization instead of re-querying request.user.organization on every page
  views.py                 dashboard/onboarding views use request.organization / request.membership; also fixes the OnboardingWizardView None-crash, unvalidated onboarding POST data, and the 30-days-per-month bucketing bug flagged in the earlier review

config/
  settings.py    added CurrentMembershipMiddleware to MIDDLEWARE; fixed MAILERS -> EMAIL_BACKEND
```

`organizations/models.py` (Organization) is unchanged - not included here.

## Rollout - do this in order, not all at once

If this is a fresh/empty database, you can skip straight to step 4. If you
already have real users, **do not** just drop the old `organization`/`role`
fields and run one migration - that deletes the data instead of moving it.

1. **Drop in every file above**, replacing your existing `accounts/models.py`
   with the `accounts/models/` package (delete the old `models.py` file first -
   a module and a package with the same name can't coexist).

2. **Temporarily keep the old fields** on `User` so there's something to
   read from during the backfill: don't delete `organization`/`role` from
   `user.py` yet if you have existing data. Run:
   ```
   python manage.py makemigrations accounts organizations
   ```
   This creates the new tables (Role, Membership, UserProfile, etc.)
   alongside the still-existing old fields.

3. Rename `0002_seed_default_roles.py` and `0003_backfill_memberships.py`
   so their numbers come after the migration from step 2, fix the
   `dependencies` tuples to match, then:
   ```
   python manage.py migrate
   ```
   Check that every existing user now has a matching `Membership` row
   before continuing.

4. **Now** remove `organization`/`role` from `User` (the version in
   `user.py` here already has them removed) and run:
   ```
   python manage.py makemigrations accounts
   python manage.py migrate
   ```

5. Update any templates that read `user.organization` or `user.role`
   directly - they'll still work via the backward-compat properties on
   `User`, but new code (and anywhere multi-business support matters)
   should use `request.organization` / `request.membership.role.slug`.

6. Templates referenced but not included here, since none were uploaded:
   `accounts/invite_employee.html` now needs `form` fields for
   `full_name`, `phone_number`, `email`, `role` (was previously
   `username`/`email`/`role` for a direct account); `invite_success.html`
   now gets `invite_link` (a URL to copy/share) instead of a
   username/password pair; a new `accept_invitation.html` needs a form for
   `username`/`password1`/`password2` plus an `{% if expired %}` branch.

## What's genuinely different in behavior

- **Employee invites no longer create an account immediately.** The owner
  fills in name/phone/role, gets a shareable link, and the employee sets
  their own username+password by opening it. This matches section 14 of
  the doc and sidesteps the global-username-collision problem flagged in
  the earlier review (two businesses can no longer fight over who gets
  `john` at signup time, though usernames are still globally unique at
  account-creation time - only *when* that collision gets surfaced changes).
- **A user can now hold more than one Membership.** Nothing in the UI
  exposes switching between businesses yet - `CurrentMembershipMiddleware`
  just picks the first active one. `active_membership_id` in the session
  is reserved for a future "switch business" control.
- **`RoleRequiredMixin`/`OrganizationMixin` no longer silently pass
  anonymous users through** if someone forgets to also list
  `LoginRequiredMixin` on a view - each mixin checks authentication itself.
