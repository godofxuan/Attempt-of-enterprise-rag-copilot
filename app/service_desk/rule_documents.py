"""Readable TEST documents generated from the actual executable rule record."""
from importlib.resources import files
from .catalog import LOAN,REPAIR
from .store import digest


def sample_documents(store,actor):
    loan=LOAN.rule(store,actor);repair=REPAIR.rule(store,actor)
    loan_text=(f'# 本地合成电脑借用制度\n\n规则版本：{loan["version"]}。仅适用于本地TEST系统。\n\n'
        f'只有存在有效维修记录的员工可以申请临时电脑。\n借用期限为1至{loan["max_days"]}天，开始日期不得早于申请当天。\n'
        '同一员工只能有一个未关闭的借用申请。\n提交后工单为待审批；待审批不等于已批准、已分配或已预留。\n'
        '本规则没有规定押金。资源和工单的实际状态须读取业务工具。\n')
    return [
        {'name':'sample_loan.md','content':loan_text,'service_tags':['loan'],
         'rule_binding':{'service':'loan','version':loan['version'],'digest':digest(loan),'source':'local SQLite loan_rules'}},
        {'name':'sample_repair.md','content':'# 本地合成IT报修制度\n\n'+repair['content']+'\n','service_tags':['repair'],
         'rule_binding':{'service':'repair','version':repair['version'],'digest':digest(repair),'source':'local SQLite it_repair_rules'}},
        {'name':'sample_meeting.md','content':files('app.resources').joinpath('sample_meeting.md').read_text('utf8'),
         'service_tags':[],'rule_binding':None}]
