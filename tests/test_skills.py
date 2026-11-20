"""The skill tree stays valid and in sync with the code it describes."""

import re
from pathlib import Path

from sovereign_shift import skills
from sovereign_shift.assess.common import WEIGHTS

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "skills" / "README.md").read_text()


def test_every_skill_has_valid_frontmatter():
    assert len(skills.names()) >= 13
    for name in skills.names():
        meta = skills.meta(name)
        assert meta["name"] == name
        assert len(meta["description"]) > 40
        assert skills.load(name) and not skills.load(name).startswith("---")


def test_tree_and_table_match_the_folders():
    linked = set(re.findall(r"\]\(([\w-]+)/SKILL\.md\)", README))
    assert linked == set(skills.names())
    for name in skills.names():
        assert name in README.split("```")[1], f"{name} missing from the tree drawing"


def test_root_lists_every_child():
    children = skills.load("sovereign-shift").split("Children:")[1].split("\n")[0]
    assert {c.strip(" .") for c in children.split(",")} == set(skills.names()) - {"sovereign-shift"}


def test_finding_ids_in_skills_exist_in_the_checks():
    checks = (ROOT / "sovereign_shift" / "graph" / "security.py").read_text()
    for name in ("assess-security-posture", "assess-risk"):
        for finding in set(re.findall(r"\b(?:SG|NET|ELB|EC2|RDS|S3|IAM)-\d{3}\b", skills.load(name))):
            assert finding in checks, f"{name} names {finding}, which no check produces"


def test_posture_weights_match_the_code():
    text = skills.load("assess-security-posture")
    for severity, points in WEIGHTS.items():
        assert f"{severity} {points}" in text


def test_risk_bands_and_ids_match_the_code():
    from sovereign_shift.assess.risk import rating

    text = skills.load("assess-risk")
    assert "critical 20+, high 12+, medium 6+" in text
    assert [rating(s) for s in (20, 12, 6, 5)] == ["critical", "high", "medium", "low"]
    code = (ROOT / "sovereign_shift" / "assess" / "risk.py").read_text()
    for rid in set(re.findall(r"\bM-[A-Z]+\b", text)):
        assert f'"{rid}-' in code or f'"{rid}' in code, f"assess-risk names {rid}, risk.py doesn't produce it"


def test_claude_code_can_find_the_skills():
    link = ROOT / ".claude" / "skills"
    assert link.is_symlink() and (link / "sovereign-shift" / "SKILL.md").exists()
