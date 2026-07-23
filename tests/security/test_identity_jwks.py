from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.security.identity import IdentityConfigurationError, LocalJwksKeyProvider
from tests.security.identity_test_support import (
    generate_rsa_jwk,
    write_jwks,
    write_standalone_private_file,
)


def test_valid_public_rsa_jwks_loads_as_immutable_key_ring(
    tmp_path: Path,
) -> None:
    _, public_jwk = generate_rsa_jwk()
    path = write_jwks(tmp_path / "identity" / "jwks.json", [public_jwk])

    provider = LocalJwksKeyProvider.load(
        path,
        max_bytes=65_536,
        max_keys=8,
        allow_standalone=True,
    )

    assert provider.key_ids == ("test-key-1",)
    assert provider.get("test-key-1").algorithm_name == "RS256"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda key: {**key, "d": "private-material"},
        lambda key: {**key, "alg": "RS512"},
        lambda key: {**key, "use": "enc"},
        lambda key: {**key, "key_ops": ["sign", "verify"]},
        lambda key: {**key, "kid": ""},
        lambda key: {**key, "kid": "nonascii-\u00e9"},
        lambda key: {**key, "kid": "bad key id"},
    ],
)
def test_jwks_rejects_private_or_policy_incompatible_keys(
    tmp_path: Path,
    mutate,
) -> None:
    _, public_jwk = generate_rsa_jwk()
    path = write_jwks(tmp_path / "jwks.json", [mutate(public_jwk)])

    with pytest.raises(IdentityConfigurationError):
        LocalJwksKeyProvider.load(
            path,
            max_bytes=65_536,
            max_keys=8,
            allow_standalone=True,
        )


def test_jwks_rejects_small_rsa_key_duplicate_kid_and_extra_top_level_data(
    tmp_path: Path,
) -> None:
    _, small = generate_rsa_jwk(key_size=1_024)
    with pytest.raises(IdentityConfigurationError, match="too small"):
        LocalJwksKeyProvider.load(
            write_jwks(tmp_path / "small.json", [small]),
            max_bytes=65_536,
            max_keys=8,
            allow_standalone=True,
        )

    _, public_jwk = generate_rsa_jwk()
    with pytest.raises(IdentityConfigurationError, match="unique"):
        LocalJwksKeyProvider.load(
            write_jwks(tmp_path / "duplicate.json", [public_jwk, public_jwk]),
            max_bytes=65_536,
            max_keys=8,
            allow_standalone=True,
        )

    extra = tmp_path / "extra.json"
    write_standalone_private_file(
        extra,
        json.dumps(
            {"keys": [public_jwk], "jku": "https://attacker.invalid"}
        ).encode("utf-8"),
    )
    with pytest.raises(IdentityConfigurationError):
        LocalJwksKeyProvider.load(
            extra,
            max_bytes=65_536,
            max_keys=8,
            allow_standalone=True,
        )


def test_jwks_rejects_duplicate_json_keys_and_oversized_file(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate-key.json"
    write_standalone_private_file(
        duplicate,
        b'{"keys":[],"keys":[]}',
    )
    with pytest.raises(IdentityConfigurationError):
        LocalJwksKeyProvider.load(
            duplicate,
            max_bytes=65_536,
            max_keys=8,
            allow_standalone=True,
        )

    oversized = tmp_path / "oversized.json"
    write_standalone_private_file(
        oversized,
        b"{" + b"a" * 1_024 + b"}",
    )
    with pytest.raises(IdentityConfigurationError, match="size limit"):
        LocalJwksKeyProvider.load(
            oversized,
            max_bytes=1_024,
            max_keys=8,
            allow_standalone=True,
        )


def test_jwks_rejects_symlink_when_platform_supports_it(tmp_path: Path) -> None:
    _, public_jwk = generate_rsa_jwk()
    target = write_jwks(tmp_path / "target.json", [public_jwk])
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is not available")

    with pytest.raises(IdentityConfigurationError, match="regular file"):
        LocalJwksKeyProvider.load(
            link,
            max_bytes=65_536,
            max_keys=8,
            allow_standalone=True,
        )


def test_managed_jwks_never_falls_back_when_manifest_is_missing(
    tmp_path: Path,
) -> None:
    _, public_jwk = generate_rsa_jwk()
    path = write_jwks(tmp_path / "jwks.json", [public_jwk])

    with pytest.raises(IdentityConfigurationError, match="not committed"):
        LocalJwksKeyProvider.load(
            path,
            max_bytes=65_536,
            max_keys=8,
        )


def test_managed_jwks_rejects_reserved_manifest_filename_without_commit_metadata(
    tmp_path: Path,
) -> None:
    _, public_jwk = generate_rsa_jwk()
    path = write_jwks(
        tmp_path / "identity_manifest.json",
        [public_jwk],
    )

    with pytest.raises(IdentityConfigurationError, match="not committed"):
        LocalJwksKeyProvider.load(
            path,
            max_bytes=65_536,
            max_keys=8,
        )
