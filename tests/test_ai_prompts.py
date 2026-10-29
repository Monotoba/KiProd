from __future__ import annotations

from pathlib import Path

import pytest

from kiprod.ai.prompts import PromptError, load_prompt


def test_loads_bundled_versioned_bom_review_prompt() -> None:
    prompt = load_prompt("bom_review")

    assert prompt.role == "reasoning"
    assert prompt.schema == "bom_review_v1"
    assert prompt.version == "1.0.0"
    assert "invent or estimate price" in prompt.body


def test_project_prompt_directory_overrides_bundled_prompt(tmp_path: Path) -> None:
    (tmp_path / "bom_review.md").write_text(
        "---\nrole: reasoning\nschema: bom_review_v1\nversion: project-7\n---\n"
        "Review electrical and manufacturing risks with cited BOM lines.",
        encoding="utf-8",
    )

    prompt = load_prompt("bom_review", search_dirs=[tmp_path])

    assert prompt.version == "project-7"
    assert prompt.path == (tmp_path / "bom_review.md").resolve()
    assert "project-7" not in prompt.body


def test_prompt_loader_rejects_bad_front_matter_and_task_paths(tmp_path: Path) -> None:
    (tmp_path / "bom_review.md").write_text(
        "---\nrole: unsupported\nschema: bom_review_v1\nversion: 1\n---\nReview.",
        encoding="utf-8",
    )
    with pytest.raises(PromptError, match="unsupported prompt role"):
        load_prompt("bom_review", search_dirs=[tmp_path])
    with pytest.raises(PromptError, match="task name"):
        load_prompt("../outside", search_dirs=[tmp_path])
