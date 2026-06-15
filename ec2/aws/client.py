"""AWS client factory — lazy boto3 import with structured error mapping.

All AWS-facing code goes through :func:`build_client` so that missing
dependencies and credential problems surface as :class:`CliError` rather
than raw Python tracebacks.
"""

from __future__ import annotations

from ec2.cli._errors import EXIT_ENV_ERROR, CliError


def build_client(service: str, region: str | None = None):
    """Return a boto3 client for *service*, mapping failures to :class:`CliError`.

    Raises
    ------
    CliError
        * code 2 when boto3 is not installed (hint to pip-install).
        * code 2 when credentials are missing.
        * code 2 when AccessDenied is returned.
        * code 2 when no region is configured.
    """

    # Lazy import — boto3 is an optional dependency.
    try:
        import boto3
    except ImportError:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message="boto3 is not installed",
            remediation="pip install ec2-cli[aws] (or pip install boto3)",
        )

    try:
        return boto3.client(service, region_name=region)
    except Exception as exc:
        raise map_aws_error(exc)


def aws_call(method, *args, **kwargs):
    """Invoke an AWS client *method*, mapping any failure to :class:`CliError`.

    All AWS API calls should go through this so errors raised *during a request*
    (AccessDenied, throttling, network) surface as structured CliErrors (code 2
    with a hint) — matching the env-error contract — rather than leaking as a
    generic ``unexpected: ...`` (code 1) from the top-level dispatcher.
    """
    try:
        return method(*args, **kwargs)
    except CliError:
        raise
    except Exception as exc:
        raise map_aws_error(exc)


def map_aws_error(exc: Exception) -> CliError:
    """Translate a boto3 / botocore exception into :class:`CliError`."""

    # Missing credentials
    if _is_no_credentials(exc):
        return CliError(
            code=EXIT_ENV_ERROR,
            message="AWS credentials are not configured",
            remediation="Configure AWS credentials (e.g. aws configure or set "
            "AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY)",
        )

    # AccessDenied
    if _is_access_denied(exc):
        return CliError(
            code=EXIT_ENV_ERROR,
            message="AWS AccessDenied — insufficient IAM permissions",
            remediation="Check IAM policy grants the required ec2:* actions",
        )

    # No region
    if _is_no_region(exc):
        return CliError(
            code=EXIT_ENV_ERROR,
            message="No AWS region configured",
            remediation="Set AWS_DEFAULT_REGION or pass --region",
        )

    # Fallback: re-raise as generic env error
    return CliError(
        code=EXIT_ENV_ERROR,
        message=f"AWS client error: {exc}",
        remediation="Check AWS configuration and try again",
    )


# ---------------------------------------------------------------------------
# Exception detectors (no botocore import at module level)
# ---------------------------------------------------------------------------


def _is_no_credentials(exc: Exception) -> bool:
    name = type(exc).__name__
    return name in ("NoCredentialsError", "PartialCredentialsError")


def _is_access_denied(exc: Exception) -> bool:
    # botocore.exceptions.ClientError carries the error dict on .response
    # (shape: {"Error": {"Code": ...}}), NOT .response_error.
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        error = resp.get("Error", {})
        if isinstance(error, dict):
            return error.get("Code") == "AccessDenied"
    return False


def _is_no_region(exc: Exception) -> bool:
    return type(exc).__name__ == "NoRegionError"
