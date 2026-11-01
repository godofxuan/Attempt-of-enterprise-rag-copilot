from types import SimpleNamespace
from app.workbench_knowledge import named_source_scope

def test_only_unique_explicit_published_titles_bind_without_topic_or_test_id_rules():
    snapshot=SimpleNamespace(documents_by_id={},all_chunks_by_id={
        'a':SimpleNamespace(section_path=['资料甲','期限'],policy_id='family-a'),
        'b':SimpleNamespace(section_path=['资料乙','期限'],policy_id='family-b')})
    assert named_source_scope('《资料甲》的期限是什么？',snapshot)==['family-a']
    assert named_source_scope('比较《资料甲》和《资料乙》',snapshot)==['family-a','family-b']
    assert named_source_scope('《没有这个名称》的期限是什么？',snapshot)==[]
    assert named_source_scope('资料甲的期限是什么？',snapshot)==[]
    snapshot.all_chunks_by_id['c']=SimpleNamespace(section_path=['资料甲'],policy_id='another-family')
    assert named_source_scope('《资料甲》的期限是什么？',snapshot)==[]
