"""Regression for a real public development query that lost its direct evidence."""
import pytest

from sleeplens.knowledge import search_sleep_knowledge


@pytest.mark.parametrize('query', [
    '睡前使用手机 亮屏 蓝光 褪黑素 入睡困难 睡眠延迟 屏幕使用与睡眠',
    '手机 屏幕 褪黑素 入睡困难',
])
def test_screen_question_keeps_light_mechanism_and_practical_guidance(query):
    result = search_sleep_knowledge(query)
    ids = {passage['citation_id'] for passage in result['passages']}
    assert result['status'] == 'ok'
    assert {'H7:EveningLight', 'H2:WindDown'} <= ids
    assert len(result['passages']) <= 4


@pytest.mark.parametrize('query,expected', [
    ('CBT-I 认知行为治疗 失眠 一线治疗 长期失眠 效果', 'H3:CBTI'),
    ('成人每天睡眠时长建议 小时 CDC 参考 是否诊断', 'H1:AdultDuration'),
])
def test_other_public_development_topics_keep_their_primary_evidence(query, expected):
    result = search_sleep_knowledge(query)
    assert expected in {passage['citation_id'] for passage in result['passages']}
    assert len(result['passages']) <= 4
