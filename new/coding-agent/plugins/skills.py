"""
Skills tools — read step-by-step playbooks from the skills/ directory.

Drop a .md file in skills/ to create a new skill. The agent will see it
listed in its system prompt and can load it with use_skill(name).
"""
from pathlib import Path
from tool_registry import tool

_SKILLS_DIR = Path(__file__).parent.parent / "skills"


@tool
def list_skills() -> str:
    """List all available skill names."""
    if not _SKILLS_DIR.is_dir():
        return "No skills directory found."
    names = sorted(p.stem for p in _SKILLS_DIR.glob("*.md"))
    if not names:
        return "No skills available."
    return "Available skills:\n" + "\n".join(f"  - {n}" for n in names)


@tool
def use_skill(name: str) -> str:
    """Load and return the instructions for a named skill.

    Args:
        name: Skill name without the .md extension (e.g. 'git_workflow').
    """
    if not _SKILLS_DIR.is_dir():
        return "ERROR: skills directory not found"
    path = _SKILLS_DIR / f"{name}.md"
    if not path.exists():
        available = sorted(p.stem for p in _SKILLS_DIR.glob("*.md"))
        hint = ", ".join(available) if available else "none"
        return f"ERROR: skill '{name}' not found. Available: {hint}"
    return path.read_text()
