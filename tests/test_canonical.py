import pytest

from sedb_ral.canonical import canonical_bytes, loads_strict, sha256_ref
from sedb_ral.errors import RALValidationError


def test_canonicalizes_key_order_and_unicode_nfc():
    value = {"b": "e\u0301", "a": 1}
    assert canonical_bytes(value) == '{"a":1,"b":"é"}'.encode("utf-8")
    assert sha256_ref(value) == (
        "sha256:09ad9fd2fb648cb2f62141215828ea00"
        "a62c299db05d20aa9ade2f527a301cc6"
    )


def test_rejects_duplicate_keys_before_dict_collapse():
    with pytest.raises(RALValidationError, match="duplicate_key"):
        loads_strict('{"a":1,"a":2}')


def test_rejects_floats():
    with pytest.raises(RALValidationError, match="unsupported_number"):
        loads_strict('{"a":1.5}')


def test_rejects_keys_that_collide_after_nfc():
    with pytest.raises(RALValidationError, match="normalized_key_collision"):
        canonical_bytes({"é": 1, "e\u0301": 2})


def test_emits_no_bom_cr_or_trailing_newline():
    result = canonical_bytes({"a": [True, None, "x"]})
    assert not result.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in result
    assert not result.endswith(b"\n")
