from swim_coach.application.queries.get_capabilities import get_capabilities


def test_capabilities_are_harmless_and_p00_only() -> None:
    result = get_capabilities()

    assert result.status == "OK"
    assert result.data.available_tools == ["get_capabilities"]
    assert result.data.private_training_data_enabled is False
    assert result.data.garmin_read_enabled is False
    assert result.data.garmin_write_enabled is False
    assert result.data.custom_ui_enabled is False
    assert result.request_id.startswith("req_")
