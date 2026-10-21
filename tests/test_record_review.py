import pytest

from scripts.record_review import validated_request

GOOD = {"INCIDENT_ID": "inc-1a2b3c4d", "DECISION": "released", "REVIEWER": "Pat"}


def test_a_good_request_passes_through():
    request = validated_request(GOOD)
    assert (request["incident_id"], request["decision"], request["reviewer"]) == ("inc-1a2b3c4d", "released", "Pat")
    assert request["requested_at"]


@pytest.mark.parametrize("override", [
    {"INCIDENT_ID": "inc-1a2b3c4d; rm -rf /"},
    {"INCIDENT_ID": "1a2b3c4d"},
    {"DECISION": "approved"},
    {"REVIEWER": ""},
    {"REVIEWER": "x" * 61},
    {"REVIEWER": "Pat\n$(whoami)"},
])
def test_bad_input_is_rejected(override):
    with pytest.raises(ValueError):
        validated_request({**GOOD, **override})
