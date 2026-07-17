from copy import deepcopy

import pytest

from app.domain.queries import UserContext
from app.security.access import AccessPolicy, safe_access_error


def user(**updates) -> UserContext:
    values = {
        "user_id": "user-one",
        "tenant_id": "tenant-one",
        "region": "cn",
        "groups": ["employees"],
    }
    values.update(updates)
    return UserContext(**values)


def chunk(**updates) -> dict:
    values = {
        "chunk_id": "visible-chunk",
        "doc_id": "visible-doc",
        "tenant_id": "tenant-one",
        "region": "cn",
        "acl_groups": ["employees"],
        "text": "visible policy text",
    }
    values.update(updates)
    return values


def test_access_requires_tenant_region_and_group_intersection() -> None:
    policy = AccessPolicy()

    assert policy.evaluate(user(), chunk()).allowed is True
    assert policy.evaluate(
        user(), chunk(tenant_id="tenant-two")
    ).code == "tenant_mismatch"
    assert policy.evaluate(user(), chunk(region="us")).code == "region_mismatch"
    assert policy.evaluate(
        user(), chunk(acl_groups=["hr_confidential"])
    ).code == "group_mismatch"


def test_any_group_intersection_is_enough_but_roles_do_not_bypass_groups() -> None:
    policy = AccessPolicy()
    multi_group = chunk(acl_groups=["finance", "employees"])

    assert policy.evaluate(user(), multi_group).allowed is True
    denied = policy.evaluate(
        user(groups=["contractors"], roles=["admin"]),
        chunk(acl_groups=["employees"]),
    )
    assert denied.allowed is False
    assert denied.code == "group_mismatch"


@pytest.mark.parametrize(
    "bad_chunk",
    [
        {},
        {"tenant_id": "tenant-one", "region": "cn"},
        {
            "tenant_id": "tenant-one",
            "region": "cn",
            "acl_groups": "employees",
        },
        {
            "tenant_id": "",
            "region": "cn",
            "acl_groups": ["employees"],
        },
    ],
)
def test_malformed_metadata_fails_closed(bad_chunk: dict) -> None:
    decision = AccessPolicy().evaluate(user(), bad_chunk)

    assert decision.allowed is False
    assert decision.code == "malformed_metadata"


def test_visible_filter_returns_no_denied_objects_and_does_not_mutate_input() -> None:
    policy = AccessPolicy()
    chunks = [
        chunk(),
        chunk(
            chunk_id="secret-chunk",
            doc_id="secret-doc",
            acl_groups=["hr_confidential"],
            text="secret salary policy",
        ),
    ]
    before = deepcopy(chunks)

    visible, denied_count = policy.visible_chunks(user(), chunks)
    indices, index_denied_count = policy.visible_indices(user(), chunks)

    assert visible == [chunks[0]]
    assert denied_count == index_denied_count == 1
    assert indices == [0]
    assert chunks == before
    assert "secret-chunk" not in repr(visible)
    assert "secret salary" not in repr(visible)


def test_all_access_denials_share_one_public_error_message() -> None:
    policy = AccessPolicy()
    decisions = [
        policy.evaluate(user(), chunk(tenant_id="tenant-two")),
        policy.evaluate(user(), chunk(region="us")),
        policy.evaluate(user(), chunk(acl_groups=["secret-board"])),
        policy.evaluate(user(), {}),
    ]

    errors = [safe_access_error(decision) for decision in decisions]

    assert {error.code for error in errors} == {"permission"}
    assert {error.safe_message for error in errors} == {
        "The requested resource is unavailable for this identity."
    }
    combined = " ".join(error.safe_message for error in errors)
    assert "tenant-two" not in combined
    assert "secret-board" not in combined


def test_access_policy_rejects_malformed_user_like_objects() -> None:
    decision = AccessPolicy().evaluate(
        {"tenant_id": "tenant-one", "region": "cn", "groups": []},
        chunk(),
    )

    assert decision.allowed is False
    assert decision.code == "malformed_identity"
