from atlaz.enhancement.models import FileValidation
from atlaz.migration.api_response_shape import extract_response_field_names, flag_missing_response_fields
from atlaz.migration.models import GeneratedFile, GeneratedUnit, MigrationUnit


def test_extracts_fields_from_return_dict_literal(tmp_path):
    (tmp_path / "app.py").write_text(
        '@app.get("/health")\n'
        "def health():\n"
        '    return {"status": "ok", "service": "inference"}\n'
    )

    fields = extract_response_field_names(str(tmp_path), ["app.py"])

    assert fields == ["service", "status"]


def test_extracts_fields_across_multiple_return_statements(tmp_path):
    (tmp_path / "app.py").write_text(
        "def infer(text):\n"
        '    return {"label": label, "score": score, "model_version": VERSION}\n'
    )

    fields = extract_response_field_names(str(tmp_path), ["app.py"])

    assert fields == ["label", "model_version", "score"]


def test_extracts_fields_from_dict_and_jsonify_kwargs(tmp_path):
    (tmp_path / "app.py").write_text(
        "def a():\n"
        "    return dict(status='ok', code=200)\n"
        "def b():\n"
        "    return jsonify(sentiment=label, confidence=score)\n"
    )

    fields = extract_response_field_names(str(tmp_path), ["app.py"])

    assert fields == ["code", "confidence", "sentiment", "status"]


def test_no_fields_when_response_is_built_via_a_variable_or_model(tmp_path):
    # Deliberately conservative: never invents a schema it didn't literally see.
    (tmp_path / "app.py").write_text(
        "def infer(text):\n"
        "    result = build_response(text)\n"
        "    return result\n"
    )

    fields = extract_response_field_names(str(tmp_path), ["app.py"])

    assert fields == []


def test_missing_file_is_skipped_not_raised(tmp_path):
    assert extract_response_field_names(str(tmp_path), ["does_not_exist.py"]) == []


def test_respects_unit_limit(tmp_path):
    lines = "\n".join(f'def f{i}():\n    return {{"field_{i}": {i}}}' for i in range(50))
    (tmp_path / "many.py").write_text(lines)

    fields = extract_response_field_names(str(tmp_path), ["many.py"])

    assert len(fields) == 40


def _unit(known_response_fields) -> MigrationUnit:
    return MigrationUnit(unit_id="cap-1", unit_type="capability", name="Billing", description="d",
                          known_response_fields=known_response_fields)


def test_flag_missing_response_fields_warns_when_a_field_is_dropped():
    # The exact reproduction of the observed failure: the health endpoint's original
    # {"status": "ok", "service": "inference"} response became a bare "OK" string.
    units = [_unit(["status", "service"])]
    generated_units = [
        GeneratedUnit(unit_id="cap-1", unit_type="capability", name="Billing", task_description="t",
                       files=[GeneratedFile(file_path="Health.java", content='return "OK";')])
    ]
    validations = [FileValidation(file_path="Health.java", syntax_valid=True)]

    result = flag_missing_response_fields(units, generated_units, validations)

    assert result[0].warnings
    assert "status" in result[0].warnings[0]
    assert "service" in result[0].warnings[0]


def test_flag_missing_response_fields_silent_when_all_fields_present():
    units = [_unit(["status", "service"])]
    generated_units = [
        GeneratedUnit(unit_id="cap-1", unit_type="capability", name="Billing", task_description="t",
                       files=[GeneratedFile(file_path="Health.java", content='"status": "ok", "service": "x"')])
    ]
    validations = [FileValidation(file_path="Health.java", syntax_valid=True)]

    result = flag_missing_response_fields(units, generated_units, validations)

    assert result[0].warnings == []


def test_flag_missing_response_fields_skips_units_with_no_known_fields():
    units = [_unit([])]
    generated_units = [
        GeneratedUnit(unit_id="cap-1", unit_type="capability", name="Billing", task_description="t",
                       files=[GeneratedFile(file_path="a.py", content="x = 1")])
    ]
    validations = [FileValidation(file_path="a.py", syntax_valid=True)]

    result = flag_missing_response_fields(units, generated_units, validations)

    assert result[0].warnings == []


def test_flag_missing_response_fields_creates_validation_entry_if_missing():
    units = [_unit(["status"])]
    generated_units = [
        GeneratedUnit(unit_id="cap-1", unit_type="capability", name="Billing", task_description="t",
                       files=[GeneratedFile(file_path="Health.java", content="return OK;")])
    ]

    result = flag_missing_response_fields(units, generated_units, [])

    assert len(result) == 1
    assert result[0].file_path == "Health.java"
    assert "status" in result[0].warnings[0]
