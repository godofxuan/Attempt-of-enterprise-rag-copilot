"""Release only state owned by a finished workbench run."""
from app.workbench_service import local_actor


class RunLifecycle:
    def __init__(self,workspace):
        self.workspace=workspace
        self.owners={}

    def own_task(self,run_id,task):
        self.owners[run_id]=(task['task_id'],task['active_run_id'],task.get('run_fence'))

    def finish(self,run_id,kind,payload,status,error):
        service=self.workspace.service
        if kind=='message':
            if status in {'cancelled','interrupted'}:service.message_cancelled(payload['task_id'],payload['message_id'])
            elif status=='failed':service.message_failed(payload['task_id'],payload['message_id'],error)
        owner=self.owners.pop(run_id,None)
        if not owner:return
        task_id,nonce,fence=owner
        with service.store.transaction() as db:
            task=service.store._task(db,local_actor(),task_id)
            if task.get('active_run_id')!=nonce or task.get('run_fence')!=fence:return
            task['active_run_id']=None
            if task['status']=='RUNNING':
                task.update(status='BLOCKED',last_error=error or ('RUN_CANCELLED' if status=='cancelled' else status.upper()))
            if status!='succeeded':task['run_fence']=task.get('run_fence',0)+1
            service.store._save(db,task)
            service.store._event(db,task_id,'execution_released',{'run_id':run_id,'status':status})
