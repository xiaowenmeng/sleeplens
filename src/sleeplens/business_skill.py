"""Load only relevant sections of a repository-owned application skill."""

import hashlib
import re
from dataclasses import dataclass
from importlib.resources import files


class SkillLoadError(ValueError):
    pass


TASK_SECTIONS = {
    "records": ("records",), "definition": ("definition",), "health": ("health",),
    "combined": ("records", "health", "combined"), "sources": ("sources",),
    "capability": ("capability",), "conversation": ("conversation",),
}


def selected_sections(plan):
    sections = list(TASK_SECTIONS.get(plan.task, TASK_SECTIONS["conversation"]))
    if plan.include_rule_explanation:
        sections.append("definition")
    if set(plan.topics) & {"sleep_stages", "deep_sleep", "light_sleep", "rem_sleep", "stage_distribution", "wearables", "circadian", "sleep_diary", "night_waking"}:
        sections.append("measurement_interpretation")
    if plan.followup or plan.focus_citations:
        sections.append("followup")
    if plan.compare_sources:
        sections.append("source_comparison")
    return tuple(dict.fromkeys(sections))


def parse_entry(text):
    match = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.S)
    if not match:
        raise SkillLoadError("Skill frontmatter is missing.")
    metadata, body = match.groups()
    # This package deliberately uses simple single-line YAML scalars. It does
    # not require a general YAML dependency or evaluate arbitrary YAML tags.
    name = re.search(r"^name: ([a-z0-9-]+)\s*$", metadata, re.M)
    description = re.search(r"^description: (.+)$", metadata, re.M)
    version = re.search(r'^  version: "([0-9]+\.[0-9]+\.[0-9]+)"\s*$', metadata, re.M)
    if not name or name.group(1) != "sleep-analysis" or not description or not version or not body.strip():
        raise SkillLoadError("Skill metadata is invalid.")
    return name.group(1), version.group(1), body.strip()


def reference_sections(text):
    parts = re.split(r"^## ([a-z_]+)\s*$", text, flags=re.M)
    sections = {}
    for index in range(1, len(parts), 2):
        name, body = parts[index], parts[index + 1].strip()
        if name in sections or not body:
            raise SkillLoadError("Skill reference section is empty or duplicated.")
        sections[name] = body
    return sections


@dataclass(frozen=True)
class BusinessSkill:
    name: str
    version: str
    sections: tuple[str, ...]
    context: str
    source_hashes: dict

    def trace(self):
        return {"name": self.name, "version": self.version, "sections": list(self.sections),
                "context_sha256": hashlib.sha256(self.context.encode("utf-8")).hexdigest(),
                "source_sha256": dict(self.source_hashes), "status": "loaded"}


def load_business_skill(plan):
    # Never accept a file path, URL or skill name from model/user input.
    root = files("sleeplens").joinpath("resources/skills/sleep-analysis")
    try:
        texts = {name: root.joinpath(name).read_text(encoding="utf-8") for name in (
            "SKILL.md", "references/response_patterns.md", "references/examples.md")}
        name, version, entry = parse_entry(texts["SKILL.md"])
        chosen = selected_sections(plan)
        blocks = [f"BUSINESS SKILL: {name} v{version}\n{entry}"]
        for filename in ("references/response_patterns.md", "references/examples.md"):
            sections = reference_sections(texts[filename])
            for section in chosen:
                if section not in sections:
                    raise SkillLoadError("Selected skill section is missing.")
                blocks.append(f"[{filename} / {section}]\n{sections[section]}")
        context = "\n\n".join(blocks)
        if len(context) > 20000:
            raise SkillLoadError("Selected skill context is too large.")
        return BusinessSkill(name, version, chosen, context,
                             {key: hashlib.sha256(value.encode("utf-8")).hexdigest() for key, value in texts.items()})
    except (OSError, UnicodeError) as exc:
        raise SkillLoadError("The sleep-analysis skill cannot be read.") from exc
