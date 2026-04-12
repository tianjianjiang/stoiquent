from __future__ import annotations

from stoiquent.llm.reasoning import extract_reasoning


class TestExtractReasoning:
    def test_single_think_block(self) -> None:
        content = "<think>I need to analyze this</think>The answer is 42."
        clean, reasoning = extract_reasoning(content)
        assert clean == "The answer is 42."
        assert reasoning == "I need to analyze this"

    def test_multiple_think_blocks(self) -> None:
        content = "<think>Step 1</think>First. <think>Step 2</think>Second."
        clean, reasoning = extract_reasoning(content)
        assert "First." in clean
        assert "Second." in clean
        assert "Step 1" in reasoning
        assert "Step 2" in reasoning

    def test_no_think_tags(self) -> None:
        content = "No thinking here"
        clean, reasoning = extract_reasoning(content)
        assert clean == "No thinking here"
        assert reasoning is None

    def test_empty_content(self) -> None:
        clean, reasoning = extract_reasoning("")
        assert clean == ""
        assert reasoning is None

    def test_think_block_with_newlines(self) -> None:
        content = "<think>\nLine 1\nLine 2\n</think>Result."
        clean, reasoning = extract_reasoning(content)
        assert clean == "Result."
        assert "Line 1" in reasoning
        assert "Line 2" in reasoning

    def test_only_think_block(self) -> None:
        content = "<think>All reasoning, no answer</think>"
        clean, reasoning = extract_reasoning(content)
        assert clean == ""
        assert reasoning == "All reasoning, no answer"

    def test_whitespace_handling(self) -> None:
        content = "  <think> padded </think>  answer  "
        clean, reasoning = extract_reasoning(content)
        assert "answer" in clean
        assert reasoning == "padded"
