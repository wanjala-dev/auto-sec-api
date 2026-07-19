"""django-otp adapter implementing OTPDevicePort."""

from __future__ import annotations

from uuid import UUID

from components.identity.application.ports.otp_device_port import OTPDeviceInfo, OTPDevicePort


class DjangoOTPDeviceAdapter(OTPDevicePort):
    """Concrete adapter backed by django-otp."""

    def _get_user(self, user_id: UUID):
        from infrastructure.persistence.users.models import CustomUser
        return CustomUser.objects.get(id=user_id)

    def get_totp_device(self, user_id: UUID, *, confirmed: bool | None = None) -> OTPDeviceInfo | None:
        from django_otp.plugins.otp_totp.models import TOTPDevice

        user = self._get_user(user_id)
        qs = TOTPDevice.objects.filter(user=user)
        if confirmed is not None:
            qs = qs.filter(confirmed=confirmed)
        device = qs.first()
        if device is None:
            return None
        return OTPDeviceInfo(device_id=device.id, name=device.name, confirmed=device.confirmed)

    def get_static_device(self, user_id: UUID) -> OTPDeviceInfo | None:
        from django_otp.plugins.otp_static.models import StaticDevice

        user = self._get_user(user_id)
        device = StaticDevice.objects.filter(user=user).first()
        if device is None:
            return None
        return OTPDeviceInfo(device_id=device.id, name=device.name, confirmed=device.confirmed)

    def create_totp_device(self, user_id: UUID, *, name: str = "default") -> OTPDeviceInfo:
        from django_otp.plugins.otp_totp.models import TOTPDevice

        user = self._get_user(user_id)
        device = TOTPDevice.objects.create(user=user, name=name, confirmed=False)
        return OTPDeviceInfo(device_id=device.id, name=device.name, confirmed=device.confirmed)

    def confirm_totp_device(self, device_id: int) -> None:
        from django_otp.plugins.otp_totp.models import TOTPDevice

        TOTPDevice.objects.filter(id=device_id).update(confirmed=True)

    def verify_token(self, device_id: int, token: str, *, method: str = "totp") -> bool:
        # django_otp.models.Device is ABSTRACT (no manager) — querying
        # Device.objects raised "Manager isn't available; Device is abstract"
        # and 500'd every OTP verification. Resolve the CONCRETE device class
        # from the method the caller already knows (static recovery code vs TOTP).
        from django_otp.plugins.otp_static.models import StaticDevice
        from django_otp.plugins.otp_totp.models import TOTPDevice

        model = StaticDevice if method == "static" else TOTPDevice
        device = model.objects.filter(id=device_id).first()
        if device is None:
            return False
        return bool(device.verify_token(token))

    def delete_device(self, device_id: int, *, method: str = "totp") -> None:
        # Same abstract-Device fix as verify_token — hit the concrete class.
        from django_otp.plugins.otp_static.models import StaticDevice
        from django_otp.plugins.otp_totp.models import TOTPDevice

        model = StaticDevice if method == "static" else TOTPDevice
        model.objects.filter(id=device_id).delete()

    def get_totp_config_url(self, device_id: int) -> str:
        from django_otp.plugins.otp_totp.models import TOTPDevice

        device = TOTPDevice.objects.get(id=device_id)
        return device.config_url

    def create_or_get_totp_device(self, user_id: UUID) -> tuple[OTPDeviceInfo, str]:
        from django_otp.plugins.otp_totp.models import TOTPDevice

        user = self._get_user(user_id)
        device = TOTPDevice.objects.filter(user=user).first()
        if not device:
            device = TOTPDevice.objects.create(user=user, confirmed=False)
        info = OTPDeviceInfo(device_id=device.id, name=device.name, confirmed=device.confirmed)
        return info, device.config_url

    def delete_all_devices(self, user_id: UUID) -> None:
        from django_otp import devices_for_user

        user = self._get_user(user_id)
        for device in devices_for_user(user, confirmed=None):
            device.delete()
