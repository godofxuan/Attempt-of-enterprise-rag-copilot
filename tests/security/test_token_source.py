from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.security.token_source as token_source
from app.security.identity import IdentityConfigurationError
from app.security.private_fs import harden_private_directory
from app.security.token_source import (
    BearerTokenFileSource,
    PersonaTokenBundleSource,
    resolve_single_token_source,
)


TOKEN_ONE = "aaa.bbb.ccc"
TOKEN_TWO = "ddd.eee.fff"


def test_token_file_is_read_on_every_request_without_exposing_token(tmp_path: Path) -> None:
    path = tmp_path / "token.txt"
    path.write_text(TOKEN_ONE + "\n", encoding="ascii")
    harden_private_directory(tmp_path)
    source = BearerTokenFileSource(path, allow_standalone=True)

    assert source.get_token() == TOKEN_ONE
    path.write_text(TOKEN_TWO + "\n", encoding="ascii")
    assert source.get_token() == TOKEN_TWO
    assert TOKEN_ONE not in repr(source)
    assert TOKEN_TWO not in repr(source)


def test_single_token_source_rejects_ambiguous_or_missing_configuration(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "token.txt"
    token_file.write_text(TOKEN_ONE, encoding="ascii")

    with pytest.raises(ValueError, match="exactly one"):
        resolve_single_token_source(token=TOKEN_ONE, token_file=token_file)
    with pytest.raises(ValueError, match="exactly one"):
        resolve_single_token_source(token=None, token_file=None)


def test_bearer_identity_roles_reject_equal_tokens_from_different_files(
    tmp_path: Path,
    capsys,
) -> None:
    user_path = tmp_path / "user.token"
    operator_path = tmp_path / "operator.token"
    user_path.write_text(TOKEN_ONE, encoding="ascii")
    operator_path.write_text(TOKEN_ONE, encoding="ascii")
    harden_private_directory(tmp_path)

    with pytest.raises(IdentityConfigurationError) as exc_info:
        token_source.ensure_distinct_bearer_token_sources(
            BearerTokenFileSource(user_path, allow_standalone=True),
            BearerTokenFileSource(operator_path, allow_standalone=True),
        )

    captured = capsys.readouterr()
    assert str(exc_info.value) == "user and operator bearer tokens must differ"
    assert TOKEN_ONE not in str(exc_info.value)
    assert TOKEN_ONE not in repr(exc_info.value)
    assert TOKEN_ONE not in captured.out
    assert TOKEN_ONE not in captured.err


def test_persona_bundle_selects_exact_persona_and_reloads(tmp_path: Path) -> None:
    path = tmp_path / "personas.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "persona-token-bundle-v1",
                "tokens": {"employee-one": TOKEN_ONE},
            }
        ),
        encoding="ascii",
    )
    harden_private_directory(tmp_path)
    source = PersonaTokenBundleSource(path, allow_standalone=True)

    assert source.get_token("employee-one") == TOKEN_ONE
    with pytest.raises(IdentityConfigurationError, match="persona token"):
        source.get_token("auditor-one")

    path.write_text(
        json.dumps(
            {
                "schema_version": "persona-token-bundle-v1",
                "tokens": {"employee-one": TOKEN_TWO},
            }
        ),
        encoding="ascii",
    )
    assert source.get_token("employee-one") == TOKEN_TWO


def test_persona_bundle_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    path = tmp_path / "personas.json"
    path.write_text(
        '{"schema_version":"persona-token-bundle-v1",'
        '"tokens":{"employee-one":"aaa.bbb.ccc",'
        '"employee-one":"ddd.eee.fff"}}',
        encoding="ascii",
    )
    harden_private_directory(tmp_path)

    with pytest.raises(IdentityConfigurationError):
        PersonaTokenBundleSource(
            path,
            allow_standalone=True,
        ).get_token("employee-one")


def test_persona_bundle_rejects_an_operator_token_used_by_any_persona(
    tmp_path: Path,
    capsys,
) -> None:
    bundle_path = tmp_path / "personas.json"
    operator_path = tmp_path / "operator.token"
    bundle_path.write_text(
        json.dumps(
            {
                "schema_version": "persona-token-bundle-v1",
                "tokens": {
                    "employee-one": TOKEN_ONE,
                    "auditor-one": TOKEN_TWO,
                },
            }
        ),
        encoding="ascii",
    )
    operator_path.write_text(TOKEN_TWO, encoding="ascii")
    harden_private_directory(tmp_path)

    with pytest.raises(IdentityConfigurationError) as exc_info:
        token_source.ensure_distinct_persona_operator_token_sources(
            PersonaTokenBundleSource(
                bundle_path,
                allow_standalone=True,
            ),
            BearerTokenFileSource(
                operator_path,
                allow_standalone=True,
            ),
        )

    captured = capsys.readouterr()
    assert str(exc_info.value) == "persona and operator bearer tokens must differ"
    for secret in (TOKEN_ONE, TOKEN_TWO):
        assert secret not in str(exc_info.value)
        assert secret not in captured.out
        assert secret not in captured.err
