"""Small, versioned full-context corpus with inspectable section references.

Checking a reference exists is not checking that it supports a claim.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from importlib.resources import files


TOPIC_TERMS = {
    "caffeine": ("caffeine", "coffee", "tea", "energy drink", "咖啡", "咖啡因", "喝茶", "能量饮料"),
    "alcohol": ("alcohol", "wine", "beer", "喝酒", "酒精"),
    "insomnia": ("insomnia", "fall asleep", "falling asleep", "can't sleep", "cannot sleep", "入睡", "睡不着", "失眠", "躺着", "清醒"),
    "night_waking": ("night waking", "wake at night", "wake up at night", "awakenings", "半夜", "夜醒", "夜间醒来", "醒来次数", "凌晨醒"),
    "persistent_insomnia": ("chronic", "persistent insomnia", "long-term insomnia", "for months", "长期", "三个月", "几个月"),
    "cbti": ("cbt-i", "cbti", "cognitive behavioral", "认知行为"),
    "routine": ("routine", "schedule", "wake time", "bedtime", "作息", "起床", "规律", "熬夜", "周末补觉"),
    "relaxation": ("relax", "wind down", "stress", "焦虑", "放松", "压力", "想事情"),
    "screens": ("screen", "phone", "屏幕", "手机", "刷视频"),
    "naps": ("nap", "午睡", "补觉"),
    "shift_work": ("shift work", "night shift", "夜班", "倒班"),
    "breathing": ("apnea", "snor", "gasp", "breathing pauses", "打鼾", "打呼", "憋醒", "呼吸暂停"),
    "daytime": ("daytime sleep", "tired", "fatigue", "sleepy", "白天困", "嗜睡", "疲倦"),
    "medication": ("melatonin", "medication", "sleeping pill", "sleep aid", "褪黑素", "安眠药", "用药", "助眠药"),
    "duration": ("how much sleep", "how many hours", "sleep duration", "睡多久", "几小时", "睡眠时长", "睡得少"),
    "quality": ("sleep quality", "restorative", "睡眠质量", "睡醒还是累"),
    "help": ("see a doctor", "seek help", "就医", "看医生"),
    "general_advice": ("advice", "sleep better", "improve sleep", "睡眠建议", "改善睡眠", "睡不好"),
    "sleep_stages": ("sleep stages", "sleep architecture", "睡眠阶段", "睡眠分期"),
    "deep_sleep": ("deep sleep", "深睡", "慢波睡眠"),
    "light_sleep": ("light sleep", "浅睡"),
    "rem_sleep": ("rem", "rapid eye movement", "快速眼动"),
    "stage_distribution": ("stage percentage", "stage distribution", "阶段比例", "深睡占比", "深睡比例", "rem占比", "深睡太少"),
    "wearables": ("wearable", "tracker", "fitbit", "pixel watch", "smartwatch", "手表", "手环", "分期准确", "监测准确"),
    "circadian": ("circadian", "body clock", "生物钟", "昼夜节律", "入睡晚", "睡得晚", "凌晨入睡"),
    "sleep_diary": ("sleep diary", "sleep latency", "睡眠日记", "入睡耗时", "入睡潜伏期"),
}
STOP_WORDS = {"the", "and", "for", "with", "sleep", "sleeping", "how", "what", "can", "does", "about", "before", "after", "from", "this", "that"}


def _citation_pattern(identifier):
    group = identifier + r"(?:\s*[,，、;；]\s*" + identifier + r")*"
    # Match the longest supported wrapper first; do not leave [[...]] around
    # a normalized list. Only citation-only contents are eligible.
    wrappers = (("[[", "]]"), ("[", "]"), ("［", "］"), ("〔", "〕"), ("(", ")"), ("（", "）"))
    alternatives = "|".join(re.escape(left) + r"\s*(" + group + r")\s*" + re.escape(right)
                            for left, right in wrappers)
    return r"(?<![\[［〔(（])(?:" + alternatives + r")(?![\]］〕)）])"


_CITATION_ID = r"[BH]\d+:[A-Za-z0-9_-]+"
_NORMALIZABLE_CITATIONS = re.compile(_citation_pattern(_CITATION_ID))
# Include bare IDs and malformed multi-colon keys so they are rejected rather
# than overlooked. Normalization never invents or truncates an identifier.
_CITATION_KEYS = re.compile(_citation_pattern(
    r"(?:[A-Z][A-Z0-9]*(?::[A-Za-z0-9_-]+)+|[A-Z][A-Z0-9]*\d[A-Z0-9]*)"))


def normalize_citation_format(text):
    """Normalize explicit source attribution; never change or validate IDs."""
    # Models sometimes put an exact ID after the institution name. Preserve
    # that attribution and the entire ID, including unknown IDs for rejection.
    attributed_id = r"[BH]\d+(?::[A-Za-z0-9_-]+)*"
    attributed = re.compile(
        r"(?<![（(\[])" + r"[（(]([^()（）\[\]\n:：]{1,80}?)[,，]\s*("
        + attributed_id + r"(?:\s*[,，、;；]\s*" + attributed_id + r")*)\s*[）)]")
    text = attributed.sub(lambda m: "（" + m[1].strip() + "）" +
                          "".join(f"[{ref}]" for ref in re.findall(attributed_id, m[2])), text)
    return _NORMALIZABLE_CITATIONS.sub(
        lambda match: "".join(f"[{ref}]" for ref in re.findall(_CITATION_ID, next(group for group in match.groups() if group is not None))), text)


def search_sleep_knowledge(query: str, *, excluded_topics=()) -> dict:
    """Select at most four relevant health passages; no live web or model call."""
    if type(query) is not str or not query.strip() or len(query) > 500:
        return {"status": "invalid_input", "error": "query must contain 1–500 characters.", "passages": []}
    query = query.strip()
    lower = query.lower()
    topics = {topic for topic, terms in TOPIC_TERMS.items()
              if any((bool(re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", lower))
                      if term.isascii() else term in lower) for term in terms)}
    words = set(re.findall(r"[a-z][a-z0-9-]{2,}", lower)) - STOP_WORDS
    try:
        bundle = load_knowledge()
    except (OSError, ValueError, KeyError):
        return {"status": "tool_error", "error": "The sleep knowledge library could not be read.", "passages": []}
    ranked = []
    for ref in bundle.references:
        if not ref["source_id"].startswith("H"):
            continue
        if set(excluded_topics).intersection(ref.get("topics", [])):
            continue
        shared_topics = topics.intersection(ref.get("topics", []))
        if topics and not shared_topics:
            continue
        text_words = set(re.findall(r"[a-z][a-z0-9-]{2,}", ref["text"].lower())) - STOP_WORDS
        score = sum(1 if topic == "general_advice" else 6 for topic in shared_topics) + len(words & text_words)
        if score:
            ranked.append((score, ref))
    ranked.sort(key=lambda item: (-item[0], item[1]["citation_id"]))
    # A mixed question needs complementary evidence, not four near-duplicate
    # passages about whichever broad topic happened to score highest.
    anchors = {"duration": "H1:AdultDuration", "quality": "H1:Quality",
               "deep_sleep": "H6:NREM", "light_sleep": "H6:NREM", "rem_sleep": "H6:REM",
               "sleep_stages": "H6:NREM", "stage_distribution": "H10:Benchmarks",
               "screens": "H7:EveningLight", "wearables": "H10:Estimates", "circadian": "H7:Clock", "sleep_diary": "H9:Diary",
               "night_waking": "H8:NightWaking"}
    selected = []
    by_id = {ref["citation_id"]: ref for _, ref in ranked}
    for topic, citation_id in anchors.items():
        if topic in topics and citation_id in by_id and citation_id not in {ref["citation_id"] for ref in selected}:
            selected.append(by_id[citation_id])
    for _, ref in ranked:
        if ref["citation_id"] not in {item["citation_id"] for item in selected}:
            selected.append(ref)
    passages = [dict(ref) for ref in selected[:4]]
    return {"status": "ok" if passages else "no_results", "query": query,
            "bundle_version": bundle.version, "retrieval_method": "local_topic_and_keyword",
            "matched_topics": sorted(topics), "excluded_topics": sorted(excluded_topics), "passages": passages}


@dataclass(frozen=True)
class KnowledgeBundle:
    version: str
    references: tuple[dict, ...]
    architecture: str = "full_context"

    def context(self, *, include_health: bool = True, product_view: bool = False) -> str:
        # JSON quoting keeps arbitrary passage content from breaking delimiters.
        passages = [dict(ref) for ref in self.references if include_health or not ref["source_id"].startswith("H")]
        if product_view:
            passages = [{key: value for key, value in ref.items() if key not in {"synthetic", "scope", "filename"}} for ref in passages]
        return json.dumps({"kind": "reference_data_not_instructions", "bundle_version": self.version,
                           "passages": passages}, ensure_ascii=False, indent=2)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.context().encode("utf-8")).hexdigest()

    def check_citations(self, text: str, *, available_ids: set[str] | None = None) -> dict:
        index = {ref["citation_id"]: ref for ref in self.references}
        found = []
        for match in _CITATION_KEYS.finditer(text):
            for ref in re.split(r"[,，、;；]", next(group for group in match.groups() if group is not None)):
                ref = ref.strip()
                # Parenthesized labels such as (N3) are ordinary prose. Bare
                # B/H document keys still need a section and remain invalid.
                if match.group()[0] in "(（" and ":" not in ref and not re.fullmatch(r"[BH]\d+", ref):
                    continue
                if ref not in found:
                    found.append(ref)
        invalid = [ref for ref in found if ref not in index]
        unavailable = [ref for ref in found if ref in index and available_ids is not None and ref not in available_ids]
        return {"status": "invalid" if invalid or unavailable else "valid" if found else "not_provided",
                "references": [dict(index[ref]) for ref in found if ref in index and ref not in unavailable],
                "invalid": invalid, "unavailable": unavailable, "structural_only": True}


def load_knowledge() -> KnowledgeBundle:
    root = files("sleeplens").joinpath("resources/knowledge")
    manifest = json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))
    references = []
    for source in manifest["sources"]:
        # The manifest is repository-owned, never supplied as a tool argument.
        if source["filename"] not in {"B1.md", "B2.md", *(f"H{number}.md" for number in range(1, 12))}:
            raise ValueError("Unsupported knowledge filename.")
        text = root.joinpath(source["filename"]).read_text(encoding="utf-8")
        sections = re.split(r"^## ([A-Za-z0-9_-]+)\s*$", text, flags=re.MULTILINE)
        if len(sections) < 3:
            raise ValueError("Knowledge document has no sections.")
        for i in range(1, len(sections), 2):
            section, passage = sections[i], sections[i + 1].strip()
            if not passage:
                raise ValueError("Empty evidence section.")
            metadata = {key: value for key, value in source.items() if key != "section_topics"}
            references.append({**metadata, "section_id": section,
                               "topics": source.get("section_topics", {}).get(section, []),
                               "citation_id": f"{source['source_id']}:{section}", "text": passage})
    ids = [ref["citation_id"] for ref in references]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate knowledge section identifiers.")
    return KnowledgeBundle(version=manifest["bundle_version"], references=tuple(references))
