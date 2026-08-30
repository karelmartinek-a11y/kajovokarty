from kajovokarty.domain.reference_parser import ReservationReferenceParser


def test_parser_scans_all_channels_and_keeps_leading_zeroes() -> None:
    parser = ReservationReferenceParser()
    result = parser.parse(["bez reference", "<p>Original ID: 006689102875</p>"], reservation_uuid="r-1")
    assert result.status == "CONFIRMED"
    assert result.confirmed == "006689102875"
    assert result.extractions[0].candidate == "006689102875"


def test_parser_merges_equal_labels_and_detects_conflict() -> None:
    parser = ReservationReferenceParser()
    same = parser.parse(["Original ID: 6689102875\nChannel reservation id = 6689102875"], reservation_uuid="r-1")
    assert same.status == "CONFIRMED"
    conflict = parser.parse(["Original ID: 6689102875", "Channel reservation id: 6689102876"], reservation_uuid="r-2")
    assert conflict.status == "CONFLICT"
    assert conflict.confirmed is None


def test_reference_fixture() -> None:
    parser = ReservationReferenceParser()
    result = parser.parse(["Channel reservation id: 6689102875"], reservation_uuid="reservation-120268038")
    assert result.confirmed == "6689102875"
