"""The 22 global checks, in execution order.

One place that answers "which global checks exist", so the UI and any
reader have a single list rather than a directory scan whose order depends
on the filesystem. The numbers are the pre-split definition order.

``catalogue.global_tests()`` does NOT read this file -- it parses the check
sources directly, so a check cannot exist without being discovered. This is
the human-facing index, and a test asserts the two agree.
"""

from __future__ import annotations

#: (order, function name, filename)
GLOBAL_CHECKS: tuple[tuple[int, str, str], ...] = (
    (1, "test_status_code_matches_spec", "01_status_code_matches_spec.py"),
    (2, "test_response_matches_full_schema", "02_response_matches_full_schema.py"),
    (3, "test_no_credential_leakage_in_response", "03_no_credential_leakage_in_response.py"),
    (4, "test_response_time_within_sla", "04_response_time_within_sla.py"),
    (5, "test_idempotent_get_returns_stable_result", "05_idempotent_get_returns_stable_result.py"),
    (6, "test_small_burst_does_not_trigger_immediate_blocking", "06_small_burst_does_not_trigger_immediate_blocking.py"),
    (7, "test_request_payload_size_enforcement", "07_request_payload_size_enforcement.py"),
    (8, "test_401_without_valid_token", "08_401_without_valid_token.py"),
    (9, "test_404_for_unknown_route", "09_404_for_unknown_route.py"),
    (10, "test_content_type_negotiation", "10_content_type_negotiation.py"),
    (11, "test_cors_preflight", "11_cors_preflight.py"),
    (12, "test_special_characters_in_input", "12_special_characters_in_input.py"),
    (13, "test_transport_is_https", "13_transport_is_https.py"),
    (14, "test_private_endpoint_rejects_anonymous_access", "14_private_endpoint_rejects_anonymous_access.py"),
    (15, "test_error_response_is_machine_readable", "15_error_response_is_machine_readable.py"),
    (16, "test_error_response_hides_internals", "16_error_response_hides_internals.py"),
    (17, "test_unsupported_media_type_rejected", "17_unsupported_media_type_rejected.py"),
    (18, "test_declared_idempotency_matches_method", "18_declared_idempotency_matches_method.py"),
    (19, "test_paginated_list_declares_page_metadata", "19_paginated_list_declares_page_metadata.py"),
    (20, "test_security_headers_present", "20_security_headers_present.py"),
    (21, "test_no_server_version_disclosure", "21_no_server_version_disclosure.py"),
    (22, "test_trace_method_is_disabled", "22_trace_method_is_disabled.py"),
)

CHECK_COUNT = len(GLOBAL_CHECKS)
