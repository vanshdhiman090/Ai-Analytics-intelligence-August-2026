from app.services.learning_memory import error_signature, format_lessons, RecalledLesson


def test_error_signature_is_stable_bounded_and_redacts_secrets():
    first = error_signature(RuntimeError("token=super-secret failed for row 123"))
    second = error_signature(RuntimeError("token=another-secret failed for row 999"))
    assert first[0] == second[0]
    assert "super-secret" not in first[1]
    assert len(first[1]) <= 500


def test_only_recalled_lessons_are_rendered():
    rendered = format_lessons([
        RecalledLesson("1", "A prior issue", "Validate the current contract", 2)
    ])
    assert "A prior issue" in rendered
    assert "Validate the current contract" in rendered
