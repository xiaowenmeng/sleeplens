"""English topic terms match inflected words without matching unrelated words."""

import pytest

from sleeplens.knowledge import search_sleep_knowledge, term_matches
from sleeplens.query_policy import plan_query


@pytest.mark.parametrize("term, text", [
    ("snor", "i snore every night"),
    ("snor", "my partner says i'm snoring"),
    ("gasp", "gasping for air"),
    ("nap", "do naps help?"),
    ("napping", "is napping bad?"),
    ("relax", "relaxation techniques"),
    ("screen", "screens before bed"),
    ("tracker", "are sleep trackers accurate"),
    ("wearable", "wearables and sleep stages"),
    ("rem", "how much rem sleep"),
    ("tea", "green teas at night"),
])
def test_inflected_english_words_match(term, text):
    assert term_matches(term, text)


@pytest.mark.parametrize("term, text", [
    ("rem", "i don't remember my dreams"),
    ("rem", "remove the alarm"),
    ("tea", "my team works late"),
    ("tea", "teach me about sleep"),
    ("nap", "a napkin"),
    ("snor", "unsnorkeled"),  # No match in the middle of a word.
])
def test_short_terms_and_word_middles_do_not_overmatch(term, text):
    assert not term_matches(term, text)


@pytest.mark.parametrize("query, topic, citation", [
    ("I snore", "breathing", "H5:BreathingSymptoms"),
    ("snoring and gasping at night", "breathing", "H5:BreathingSymptoms"),
    ("are sleep trackers accurate", "wearables", "H10:Estimates"),
    ("do naps help", "naps", "H2:Naps"),
])
def test_search_retrieves_topic_passages_for_inflected_queries(query, topic, citation):
    result = search_sleep_knowledge(query)
    assert topic in result["matched_topics"]
    assert citation in [passage["citation_id"] for passage in result["passages"]]


def test_query_plan_recognizes_inflected_topics():
    assert "breathing" in plan_query("I keep snoring at night, what should I do?").topics
    assert "rem_sleep" not in plan_query("I can't remember how I slept").topics
