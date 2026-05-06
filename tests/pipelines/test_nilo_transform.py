from dataif_pipelines.connectors.nilo_pecanha.transform import normalize_record


def test_normalize_record_hash_and_fields() -> None:
    payload = {
        "id": "abc-1",
        "dataset": "nilo",
        "entidade": "Instituto X",
        "ano": "2024",
        "indicador": "matriculas",
        "valor": "123,45",
    }

    result = normalize_record(payload, "https://fonte.gov", "run-1")

    assert result["source_record_id"] == "abc-1"
    assert result["ano"] == 2024
    assert result["valor"] == 123.45
    assert len(result["payload_hash"]) == 64
