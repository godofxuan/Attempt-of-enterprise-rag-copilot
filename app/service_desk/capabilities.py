"""Trusted capability contracts, not a natural-language intent classifier."""
def catalog(*, read_contract=False):
    from app.service_desk.contracts import TOOL_SCHEMAS
    tools=set(TOOL_SCHEMAS)
    capabilities=[{'id':'explain_policy','mode':'explain','action':'explain','object':'policy',
                   'description':'Explain authorized knowledge and status concepts; never performs a business operation.'}]
    if {'tickets.list_mine','tickets.get'}<=tools:
        capabilities.append({'id':'inspect_ticket','mode':'inspect','action':'inspect','object':'ticket',
                             'description':'Read actual owned ticket status and parameters; compare a current owned snapshot with explicitly supplied user parameters and report differences or an exact match. This read-only result does not modify a ticket, create another application, approve it or allocate a device. Status concepts and policy rules are knowledge explanations, not actual record reads.'})
    if 'tickets.propose_create' in tools:
        capabilities.append({'id':'create_loan','mode':'act','action':'create','object':'loan_request',
                             'required_user_facts':['loan_start','loan_end','purpose'],
                             'description':'Prepare a laptop loan preview. Only explicit human confirmation permits host submission. Submission is PENDING_APPROVAL, not approval or allocation.'})
    if 'assets.search' in tools:
        capabilities.append({'id':'inspect_assets','mode':'inspect','action':'inspect','object':'device',
            'description':'Read only available laptops and current repair eligibility. No allocation status, ownership or approval read; no reservation or business write.',
            **({'read_contract':{'tool':'assets.search',
                'returned_fields':['assets[].asset_id','assets[].category','assets[].available','assets[].version',
                    'repair.active','repair.version'],
                'not_provided':['actual_device_allocation','device_owner','application_approval']}}
                if read_contract else {})})
    return capabilities

def resolve_frame(frame):
    if frame.request_mode=='ambiguous': return 'unknown',None
    if frame.request_mode=='explain': return 'inspect_policy','explain_policy'
    for cap in catalog():
        if (frame.request_mode,frame.action,frame.object)==(cap['mode'],cap['action'],cap['object']):
            return {'inspect_ticket':'inspect_ticket_status','inspect_assets':'inspect_asset_status','create_loan':'submit_loan'}[cap['id']],cap['id']
    return 'unsupported_action',None
