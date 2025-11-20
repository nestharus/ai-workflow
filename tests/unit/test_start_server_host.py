from scripts.start_server import _format_health_probe_host


def test_format_health_probe_host_preserves_encoded_zone_id() -> None:
    assert _format_health_probe_host("[fe80::1%25eth0]") == "[fe80::1%25eth0]"


def test_format_health_probe_host_encodes_multiple_percent_signs() -> None:
    assert _format_health_probe_host("[fe80::1%eth0%enp0s3]") == "[fe80::1%25eth0%25enp0s3]"


def test_format_health_probe_host_handles_malformed_zone_identifier() -> None:
    assert _format_health_probe_host("[fe80::1%bad%zz]") == "[fe80::1%25bad%25zz]"
