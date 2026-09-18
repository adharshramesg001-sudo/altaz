from atlaz.migration.technical_values import extract_static_values


def test_extracts_identifier_literal_assignments(tmp_path):
    (tmp_path / "config.py").write_text("MAX_RETRIES = 3\nTIMEOUT_SECONDS = 30\nname = 'unrelated'\n")

    values = extract_static_values(str(tmp_path), ["config.py"])

    names = {v.name for v in values}
    assert "MAX_RETRIES" in names
    assert "TIMEOUT_SECONDS" in names


def test_not_filtered_to_business_sounding_identifiers(tmp_path):
    # Unlike agents.domain_b.business_rule_extractor, this scanner deliberately has no
    # BUSINESS_IDENTIFIER_PATTERN filter -- purely technical constants matter here.
    (tmp_path / "settings.py").write_text('REDIS_PORT = 6379\nBASE_IMAGE_TAG = "python:3.11"\n')

    values = extract_static_values(str(tmp_path), ["settings.py"])

    names = {v.name for v in values}
    assert "REDIS_PORT" in names
    assert "BASE_IMAGE_TAG" in names


def test_records_correct_file_and_line(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\nPORT = 8080\n")

    values = extract_static_values(str(tmp_path), ["a.py"])

    port_value = next(v for v in values if v.name == "PORT")
    assert port_value.file_path == "a.py"
    assert port_value.line == 2
    assert port_value.value == "8080"


def test_missing_file_is_skipped_not_raised(tmp_path):
    values = extract_static_values(str(tmp_path), ["does_not_exist.py"])

    assert values == []


def test_respects_per_file_limit(tmp_path):
    lines = "\n".join(f"CONST_{i} = {i}" for i in range(50))
    (tmp_path / "many.py").write_text(lines)

    values = extract_static_values(str(tmp_path), ["many.py"])

    assert len(values) == 20


def test_respects_unit_wide_limit_across_multiple_files(tmp_path):
    for file_idx in range(3):
        lines = "\n".join(f"CONST_{file_idx}_{i} = {i}" for i in range(20))
        (tmp_path / f"file_{file_idx}.py").write_text(lines)

    values = extract_static_values(str(tmp_path), [f"file_{i}.py" for i in range(3)])

    assert len(values) == 30
