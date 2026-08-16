"""Frozen corpus source — shell=True with interpolated input."""

import subprocess


def restart_service(service_name: str) -> int:
    result = subprocess.run(f"systemctl restart {service_name}", shell=True, check=False)
    return result.returncode
