import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dv_harness.skill_resolver import SkillResolver


def _write_skill(root: Path, *parts: str) -> None:
    skill_dir = root.joinpath(".claude", "skills", *parts)
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# stub skill\n", encoding="utf-8")


def test_deprecated_skills_are_excluded_from_index(tmp_path):
    _write_skill(tmp_path, "_deprecated", "some-skill")
    _write_skill(tmp_path, "REAL_CATEGORY", "some-other-skill")

    resolver = SkillResolver(tmp_path)

    assert "some-skill" not in resolver.index
    assert "some-other-skill" in resolver.index

    results = resolver.resolve(["some-skill", "some-other-skill"])
    by_name = {r["skill"]: r for r in results}
    assert by_name["some-skill"]["found"] is False
    assert by_name["some-skill"]["path"] is None
    assert by_name["some-other-skill"]["found"] is True


def test_deprecated_pcie_production_builder_not_resolvable_from_real_repo():
    resolver = SkillResolver(ROOT)
    assert "pcie-production-builder" not in resolver.index
    result = resolver.resolve(["pcie-production-builder"])[0]
    assert result["found"] is False


@pytest.mark.parametrize("skill_name", [
    "usb-real-env-generator",
    "usb-complete-env-generator",
    "usb-production-builder",
])
def test_deprecated_usb_alternate_generators_not_resolvable_from_real_repo(skill_name):
    resolver = SkillResolver(ROOT)
    assert skill_name not in resolver.index
    result = resolver.resolve([skill_name])[0]
    assert result["found"] is False
