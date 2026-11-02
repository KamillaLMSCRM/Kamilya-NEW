import base64
import hashlib
from uuid import uuid4

import pytest

from app.modules.ai.managed_luna_client import MAX_RESPONSE_BYTES, ManagedLunaError
from app.modules.ai.managed_response_rejection import ManagedResponseRejectedError
from app.modules.ai.source_first_response import parse_source_first_response

TENANT, USER, JOB = uuid4(), uuid4(), str(uuid4())
STAGE, ROUTE, WIRE = "a" * 64, "b" * 64, "c" * 64


def make(raw=b"secret", cause=None, **changes):
    args = dict(raw=raw, tenant_id=TENANT, user_id=USER, job_id=JOB, stage=STAGE,
                route_fingerprint=ROUTE, wire_request_sha256=WIRE, phase="content_json",
                cause=cause or ValueError("private secret"))
    args.update(changes)
    return ManagedResponseRejectedError(**args)


def receipt(err, **changes):
    args = dict(tenant_id=str(TENANT), user_id=USER, job_id=JOB, stage=STAGE, route_fingerprint=ROUTE)
    args.update(changes)
    return err.checked_receipt(**args)


@pytest.mark.parametrize("raw,subtype", [(b'{"x":1,"x":2}', "duplicate"),
                                         (b'{"x":NaN}', "nonfinite"), (b'[]', "nonobject"),
                                         (b'{bad', "syntax"), (b'\xffsecret', "unverified")])
def test_exact_bytes_and_sanitized_error(raw, subtype):
    try:
        parse_source_first_response(raw.decode("utf-8"))
    except Exception as cause:
        err = make(raw, cause)
    record = receipt(err)
    assert isinstance(err, ManagedLunaError)
    assert record["subtype"] == subtype and base64.b64decode(record["raw_base64"]) == raw
    assert record["body_sha256"] == hashlib.sha256(raw).hexdigest() and record["byte_count"] == len(raw)
    assert record["accepted"] is False and record["complete_http_response"] is True and record["status"] == 200
    assert "secret" not in str(err) + repr(err) + repr(err.args)
    assert (record["position"] is not None) == (subtype == "syntax")
    record["raw_base64"] = "tampered"
    assert base64.b64decode(receipt(err)["raw_base64"]) == raw
    with pytest.raises(AttributeError):
        err._raw = b"forged"
    with pytest.raises(AttributeError):
        err.args = ("forged",)


@pytest.mark.parametrize("field,value", [("tenant_id", str(uuid4())), ("user_id", uuid4()), ("job_id", str(uuid4())),
                                         ("stage", "d" * 64), ("route_fingerprint", "e" * 64),
                                         ("tenant_id", str(TENANT).upper()), ("user_id", True)])
def test_wrong_scope_rejected(field, value):
    with pytest.raises(ValueError, match="managed_rejection_scope_invalid"):
        receipt(make(), **{field: value})


@pytest.mark.parametrize("field,value", [("raw", bytearray(b"x")), ("raw", b"x" * (MAX_RESPONSE_BYTES + 1)),
                                         ("tenant_id", True), ("user_id", str(USER)), ("job_id", JOB.upper()),
                                         ("stage", "A" * 64), ("route_fingerprint", True),
                                         ("wire_request_sha256", "x" * 64), ("phase", "other"), ("cause", "oops")],
                         ids=["mutable-bytes", "too-large", "tenant-bool", "user-string", "job-uppercase",
                              "stage-uppercase", "route-bool", "wire-invalid", "phase-invalid", "cause-invalid"])
def test_bad_constructor_inputs_fail_closed(field, value):
    with pytest.raises(ValueError, match="managed_rejection_invalid"):
        make(**{field: value})


def test_noncanonical_exception_text_never_echoed():
    err = make(cause=ValueError("source_first_qa_duplicate_key with secret"))
    assert receipt(err)["subtype"] == "unverified"
    assert "secret" not in repr(err) + str(err) + repr(err.args)


def test_maximum_bytes_accepted_and_raise_preserves_sanitization():
    err = make(raw=b"x" * MAX_RESPONSE_BYTES)
    with pytest.raises(ManagedResponseRejectedError) as caught:
        raise err
    assert receipt(caught.value)["byte_count"] == MAX_RESPONSE_BYTES
