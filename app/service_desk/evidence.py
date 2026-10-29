"""Task-local presentation handles over immutable admitted evidence identities."""
def ordered_evidence(task):
    by_id=task.get('knowledge',{})
    order=task.get('evidence_order',list(by_id))
    return [by_id[ref] for ref in order if ref in by_id and not by_id[ref].get('invalidated_by')]

def resolve_reference(task,ref):
    if ref in task.get('knowledge',{}): return ref
    found=task.get('evidence_aliases',{}).get(ref)
    if not found: raise ValueError('UNKNOWN_TASK_EVIDENCE_HANDLE')
    return found

def model_evidence(task):
    aliases={ref:alias for alias,ref in task.get('evidence_aliases',{}).items()}
    rows=[]
    for e in ordered_evidence(task):
        alias=aliases.get(e['ref'],e['ref'])
        row={k:e[k] for k in ('document_id','version_id','source_path','text','need_refs') if k in e}
        row.update(ref=alias,spans=[{'span_ref':alias+'.S1','text':e['text']}])
        rows.append(row)
    return rows

def resolve_span(task,span_ref,scope=None):
    if scope is not None and scope!=task['task_id'][:12]: raise ValueError('WRONG_TASK_EVIDENCE_SCOPE')
    if not span_ref.endswith('.S1'): raise ValueError('UNKNOWN_HOST_SPAN')
    ref=resolve_reference(task,span_ref[:-3]); source=task.get('knowledge',{}).get(ref)
    if not source: raise ValueError('UNKNOWN_HOST_SPAN')
    if source.get('invalidated_by'): raise ValueError('STALE_HOST_SPAN')
    return {'evidence_ref':ref,'quote':source['text']}
