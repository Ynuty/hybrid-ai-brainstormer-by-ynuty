from app.services import build_topic_prompt


def test_build_topic_prompt_includes_topic():
    prompt = build_topic_prompt("MVP за 2 недели")
    assert "MVP за 2 недели" in prompt


def test_build_topic_prompt_truncates_long_context():
    long_context = "x" * 100_000
    prompt = build_topic_prompt("t", context=long_context)
    assert len(prompt) < 100_000
