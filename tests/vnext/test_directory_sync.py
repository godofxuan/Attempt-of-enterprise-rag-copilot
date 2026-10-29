import asyncio
from tests.vnext.test_bootstrap import client_for


def test_explicit_directory_add_replace_missing_and_recovery_are_incremental(tmp_path):
    source=tmp_path/'chosen-documents';source.mkdir();(source/'one.md').write_text('# One\n\nVersion one.',encoding='utf8')
    (source/'second').mkdir();(source/'second'/'one.md').write_text('# Different\n\nDifferent policy.',encoding='utf8')
    with client_for(tmp_path/'data') as client:
        library=client.app.state.workspace.library;kb=library.create('Directory')['id']
        registered=library.register_directory(kb,str(source))
        first=asyncio.run(library.sync_directory(registered['id']))
        assert len(first['added'])==2
        before=library.list()['documents']
        same=asyncio.run(library.sync_directory(registered['id']))
        assert len(same['unchanged'])==2 and not same['added'] and not same['replaced']
        assert library.list()['documents']==before
        (source/'one.md').write_text('# One\n\nVersion two.',encoding='utf8')
        changed=asyncio.run(library.sync_directory(registered['id']))
        assert changed['replaced']==['one.md'] and changed['unchanged']==['second/one.md']
        (source/'second'/'one.md').unlink()
        missing=asyncio.run(library.sync_directory(registered['id']))
        assert missing['missing']==['second/one.md']
        assert any(d['active'] and d['status']=='SOURCE_MISSING' for d in library.list()['documents'])
        (source/'second'/'one.md').write_text('# Different\n\nDifferent policy.',encoding='utf8')
        asyncio.run(library.sync_directory(registered['id']))
        assert not any(d['active'] and d['status']=='SOURCE_MISSING' for d in library.list()['documents'])
