from atlaz.enhancement.models import FileModification
from atlaz.enhancement.validator import ValidationAgent


def _mod(file_path: str, content: str) -> FileModification:
    return FileModification(file_path=file_path, original_content="", modified_content=content, task_description="t")


def test_valid_python_passes():
    agent = ValidationAgent()
    result = agent.run([_mod("a.py", "def f():\n    return 1\n")])
    assert result[0].syntax_valid
    assert result[0].warnings == []


def test_invalid_python_syntax_is_flagged():
    agent = ValidationAgent()
    result = agent.run([_mod("a.py", "def f(:\n    return 1\n")])
    assert not result[0].syntax_valid
    assert result[0].warnings


def test_unbalanced_braces_in_js_are_flagged():
    agent = ValidationAgent()
    result = agent.run([_mod("a.js", "function f() { return 1;")])
    assert not result[0].syntax_valid


def test_balanced_braces_in_js_pass():
    agent = ValidationAgent()
    result = agent.run([_mod("a.js", "function f() { return 1; }")])
    assert result[0].syntax_valid


def test_sql_concatenation_is_flagged_as_security_issue():
    agent = ValidationAgent()
    content = 'query = "SELECT * FROM users WHERE id = " + user_id\n'
    result = agent.run([_mod("a.py", content)])
    assert result[0].security_issues


def test_hardcoded_secret_is_flagged():
    agent = ValidationAgent()
    content = 'api_key = "sk-abcdef1234567890"\n'
    result = agent.run([_mod("a.py", content)])
    assert result[0].security_issues


def test_clean_file_has_no_security_issues():
    agent = ValidationAgent()
    content = "def checkout(user_id):\n    return db.query('SELECT * FROM users WHERE id = %s', [user_id])\n"
    result = agent.run([_mod("a.py", content)])
    assert result[0].security_issues == []


def test_unknown_extension_skips_syntax_check_but_still_scans_security():
    agent = ValidationAgent()
    content = 'password = "hunter12345"\n'
    result = agent.run([_mod("config.env", content)])
    assert result[0].syntax_valid
    assert result[0].security_issues
