"""One-way handoff and host validation; the runner remains the only executor."""
from __future__ import annotations

import re

from app.agent.controller_v2 import ControllerDecision, _terminal
from app.agent.evidence_ledger import build_ledger, evidence_view, with_open_evidence
from app.agent.policy_contract import (
    ALL_ACTIONS, normalized_action_text, validate_proposal, validate_rewrite,
    stage_task_proposal, task_search_query, TaskNeedCapacityExceeded,
)
from app.agent.model_policy import PolicyContextExceeded
from app.agent.request_capabilities import RequestCapabilities
from app.agent.task_plan import RequestNeed, observe_task
from app.domain.agent import AgentAction, ToolError
from app.domain.queries import SearchRequest
from app.domain.retrieved_security import GuardedFindResult, GuardedOpenAdmittedResult, GuardedSearchResult
from app.runtime.request_context import current_request_context, remaining_seconds


class HybridPolicy:
    def __init__(self, registry, state, policy, *, index_binding=None, allowed_actions=ALL_ACTIONS, policy_mode="hybrid_agent"):
        self.task_mode = policy_mode == "task_agent"
        self.policy = policy
        self.capabilities = RequestCapabilities(registry, state, index_binding)
        self.allowed_actions = allowed_actions
        self.phase = "initializing" if self.task_mode else "rule_fastpath"
        self.observations = ([{"schema_version":"task.v1", "observation_id":"I0", "tool":"host",
                              "status":"initial", "results":[], "error":None}]
                             if self.task_mode else [])
        self.evidence_refs = {}
        self.proposal_count = 0
        self.rejections = 0
        self.handoffs = int(self.task_mode)
        self.stop = None
        self.actions = []
        self.searched = set()
        self.found = set()
        self.no_progress = 0
        self.retried = False
        self.retry_action = None
        self.executed = set()
        self.negative_actions = set()
        self.seen_evidence = set()
        self.seen_content = set()

    def observe(self, execution, state):
        oid = f"O{len(self.observations)+1}"
        result, action = execution.result, execution.action
        results = []
        if isinstance(result, GuardedSearchResult):
            self.searched.add(normalized_action_text(action.search_request.query))
            previous_docs = len(self.capabilities.documents)
            self.capabilities.admit_search(result, state, oid)
            results = self.capabilities.document_view()
            ids = {h.hit.chunk_id for h in result.hits}
            progress = bool(ids - self.seen_evidence)
            self.seen_evidence.update(ids)
            self.seen_content.update(t for h in result.hits for t in (h.hit.matched_text,h.hit.context_text) if t)
        elif isinstance(result, GuardedFindResult):
            previous_windows = len(self.capabilities.windows)
            results = self.capabilities.admit_find(action, result, state, oid)
            progress = len(self.capabilities.windows) > previous_windows
            for r in results:
                w=self.capabilities.windows[r["ref"]]
                raw=self.capabilities.snapshot.all_chunks_by_id[w.target_id].text[w.start:w.start+w.length]
                r["information_status"]="already_seen" if any(raw in old for old in self.seen_content) else "unread_window"
        elif isinstance(result, GuardedOpenAdmittedResult):
            ref = next((ref for ref, w in self.capabilities.windows.items()
                        if (w.target_id,w.start) == (result.item.result.target_id,result.item.result.start_char)), None)
            binding_new = bool(ref and ref not in self.capabilities.used_windows)
            information_new = not any(result.item.result.content in old for old in self.seen_content)
            progress = information_new if self.task_mode else binding_new
            if ref:
                cap = self.capabilities.windows[ref]
                anchor = self.capabilities.documents[cap.document_ref].anchor
                aspect = state.analysis.required_aspects[0]
                from app.agent.question_parts import claim_is_relevant
                if ((self.task_mode or claim_is_relevant(state.analysis.original_question,result.item.result.content))
                    and not any(h.hit.chunk_id == anchor.hit.chunk_id for h in state.evidence_by_aspect.get(aspect, []))):
                    state.evidence_by_aspect[aspect] = [*state.evidence_by_aspect.get(aspect, []), anchor]
                    if not self.task_mode:
                        state.task_plan = state.task_plan.model_copy(update={"model_relevance_used": True})
                self.capabilities.used_windows.add(ref)
                from app.domain.evidence_packet import complete_evidence_prefix
                excerpt = complete_evidence_prefix(result.item.result.content, 1500)
                results = [{"kind": "evidence", "ref": ref, "excerpt": excerpt,
                            "is_complete_source_unit": not result.item.result.truncated and excerpt == result.item.result.content,
                            "context_status": "PARTIAL_COMPLETE_UNITS" if excerpt != result.item.result.content else "FULL",
                            "information_status":"new_content" if information_new else "binding_only"}]
                self.seen_content.add(result.item.result.content)
                continuation = self.capabilities.continuation(ref, result.item, state, oid)
                if continuation:
                    results.append(continuation)
        else:
            progress = False
        status = "ok" if results else "not_found"
        error = None
        if isinstance(result, ToolError):
            if result.code == "not_found":
                status = "not_found"
            elif result.failure_origin == "backend_transient" and result.retryable and not self.retried:
                status = "retryable_error"
                self.retry_action = action
                state.last_error = None
            else:
                status = "hard_error"
                self.stop = "hard_error"
            error = {"code": "transient_backend" if status == "retryable_error" else "not_available",
                     "retryable": status == "retryable_error", "message": "The requested operation is unavailable."}
        action_key = self._action_key(action)
        self.executed.add(action_key)
        useful_negative = status == "not_found" and action_key not in self.negative_actions
        if useful_negative:
            self.negative_actions.add(action_key)
        self.no_progress = 0 if progress or useful_negative else self.no_progress + 1
        self.observations.append({"schema_version": "2", "observation_id": oid,
            "for_action_id": f"A{action.sequence}", "tool": action.tool, "status": status,
            "results": results[:8], "progress": {"new_evidence_units": int(progress and action.tool != "find" and (action.tool!="open" or information_new)),
            "new_windows": int(progress and action.tool == "find"), "useful_negative_result": useful_negative},
            "error": error, "remaining": self.remaining(state)})
        if not isinstance(result, ToolError):
            state.ledger = build_ledger(state.analysis, state.evidence_by_aspect, open_results=state.open_results,
                denied_only=state.denied_only_signal and not any(state.evidence_by_aspect.values()))
            values = with_open_evidence(state.evidence_by_aspect, state.open_results)
            views = {evidence_view(v).citation_id: evidence_view(v) for vs in values.values() for v in vs}
            state.task_plan = observe_task(state.task_plan, state.analysis.original_question, list(views.values()),
                read_incomplete=state.task_plan.read_incomplete)

    def simple(self, state):
        question = state.analysis.original_question
        if re.search(r"例外|如果|但|分别|以及|还有|、|，|,|\band\b|\bexcept\b|我|这次|这笔", question, re.I):
            return False
        needs = state.task_plan.needs
        if len(needs) != 1 or state.analysis.intent != "fact" or state.task_plan.read_incomplete or state.ledger.conflicting_aspects:
            return False
        if needs[0].kind == "domain":
            return bool(needs[0].evidence_ids and not needs[0].clarification_needed)
        from app.agent.answer_contract import bounded_answer_slots
        texts = [h.hit.matched_text for hs in state.evidence_by_aspect.values() for h in hs]
        slots = bounded_answer_slots(question, texts)
        return bool(len(slots.requested) == 1 and not slots.missing and not slots.conditional)

    def remaining(self, state):
        budget = state.budget_state
        context = current_request_context()
        sends = context.attempt_budget.counts.get("policy", 0) if context and context.attempt_budget else 0
        return {"policy_attempts": max(0,4-max(self.proposal_count, sends)),
                "search": max(0,budget.budget.max_search_calls-budget.search_calls),
                "find": max(0,budget.budget.max_find_calls-budget.find_calls),
                "open": max(0,budget.budget.max_open_calls-budget.open_calls),
                "deadline_ms": max(0,(remaining_seconds() or 0)*1000)}

    def view(self, state):
        remaining = self.remaining(state)
        documents = self.capabilities.document_view()
        windows = [ref for ref in self.capabilities.windows if ref not in self.capabilities.used_windows]
        allowed = set(self.allowed_actions)
        for tool in ("search", "find", "open"):
            if remaining[tool] <= 0:
                allowed.discard(tool)
        if not documents:
            allowed.discard("find")
        if not windows:
            allowed.discard("open")
        personal = any(n.clarification_needed for n in state.task_plan.needs) or re.search(
            r"我|这笔|这次|本次", state.analysis.original_question)
        if (not self.task_mode and not personal) or len(state.clarification_replies) >= 2:
            allowed.discard("clarify")
        if self.task_mode and not state.task_plan.needs:
            allowed &= {"search", "clarify", "abstain"}
        view = {"original_question": state.analysis.original_question,
                "clarification_replies": state.clarification_replies,
                "business_scope":state.task_plan.business_scope,
                "needs": [{"id": n.need_id, "question": n.text,
                           "status": "user_fact_gap" if n.clarification_needed else
                           "supported_by_existing_checks" if n.evidence_ids and n.kind != "whole" else "unknown"}
                          for n in state.task_plan.needs],
                "documents": documents, "observations": self.observations[-4:],
                "available_window_refs": windows,
                "remaining": remaining, "allowed_actions": sorted(allowed)}
        if self.task_mode:
            from app.domain.evidence_packet import complete_evidence_prefix
            values = with_open_evidence(state.evidence_by_aspect, state.open_results)
            units = {evidence_view(item).citation_id:evidence_view(item)
                     for items in values.values() for item in items}
            evidence = []
            for cid, item in units.items():
                ref = next((r for r,ids in self.evidence_refs.items() if ids == (cid,)), None)
                if ref is None:
                    ref = self.capabilities._ref("E", len(self.evidence_refs)+1)
                    self.evidence_refs[ref] = (cid,)
                excerpt = complete_evidence_prefix(item.text, 1000)
                evidence.append({"ref":ref, "excerpt":excerpt,
                    "context_status":"FULL" if excerpt == item.text else "PARTIAL_COMPLETE_UNITS" if excerpt else "CONTEXT_INSUFFICIENT"})
            view.update(policy_mode="task_agent", phase="continue" if state.task_plan.needs else "initialize",
                user_sources=self.user_sources(state), evidence_units=evidence[:12])
            view["needs"] = [{"id":n.need_id,"question":n.text,"kind":n.semantic_kind,
                               "status":n.model_assessment} for n in state.task_plan.needs]
        return view

    @staticmethod
    def user_sources(state):
        return {"Q0":state.analysis.original_question,
                **{f"R{i}":r["reply"] for i,r in enumerate(state.clarification_replies,1)}}

    def _add_needs(self, proposal, state):
        additions, plan = proposal.add_needs, state.task_plan
        if not additions:
            return
        if plan.model_added_needs + len(additions) > 4 or len(plan.needs)+len(additions) > 8:
            state.task_plan = plan.model_copy(update={"overflow": True})
            raise ValueError("need capacity")
        question = state.analysis.original_question
        spans = {normalized_action_text(n.text) for n in plan.needs}
        new = []
        for addition in additions:
            if question[addition.source_start:addition.source_end] != addition.source_span or addition.source_end <= addition.source_start:
                raise ValueError("unbound need")
            key = normalized_action_text(addition.source_span)
            if key in spans:
                raise ValueError("duplicate need")
            spans.add(key)
            new.append(RequestNeed(need_id=f"N{len(plan.needs)+len(new)+1}", text=addition.source_span,
                       kind="model", source_start=addition.source_start, source_end=addition.source_end))
        state.task_plan = plan.model_copy(update={"needs": (*plan.needs,*new),
                                                 "model_added_needs": plan.model_added_needs+len(new)})

    def next_decision(self, state):
        if self.stop == "hard_error":
            return self.terminal(state, "system", "system_error")
        if self.phase == "rule_fastpath":
            if state.denied_only_signal and not self.capabilities.documents:
                return self.terminal(state, "permission", "permission")
            if state.security_filtered_signal and not self.capabilities.documents:
                return self.terminal(state, "security_filtered", "evidence_filtered")
            if self.simple(state):
                self.stop = "simple_fastpath"
                return self.terminal(state, "answered", "completed")
            self.phase = "model_recovery"
            self.handoffs += 1
        if self.proposal_count >= 4 or self.rejections >= 2 or self.no_progress >= 2:
            self.stop = self.stop or ("no_progress" if self.no_progress >= 2 else "host_budget_finalize")
            return self.finalize(state)
        if remaining_seconds() is not None and remaining_seconds() <= 5:
            self.stop = "generation_time_reserve"
            return self.finalize(state)
        budget = state.budget_state
        if budget.steps >= budget.budget.max_steps or budget.context_chars >= budget.budget.max_context_chars:
            self.stop = "host_budget_finalize"
            return self.finalize(state)
        self.capabilities.check(state)
        self.proposal_count += 1
        try:
            view = self.view(state)
            raw = self.policy.decide(view)
            staged = state.task_plan
            if self.task_mode:
                staged, proposal = stage_task_proposal(raw, plan=state.task_plan,
                    user_sources=self.user_sources(state), observations=[o["observation_id"] for o in self.observations],
                    evidence_refs={r:self.evidence_refs[r] for r in [e["ref"] for e in view["evidence_units"]]},
                    allowed_actions=set(view["allowed_actions"]))
            else:
                proposal = validate_proposal(raw, allowed_actions=set(view["allowed_actions"]))
            ids = {n.need_id for n in staged.needs}

            def commit():
                if self.task_mode:
                    state.task_plan = staged
                    self.phase = "investigating"
                else:
                    self._add_needs(proposal, state)
            if not set(proposal.target_need_ids) <= ids or self.observations[-1]["observation_id"] not in proposal.based_on_observation_ids:
                raise ValueError("unknown state IDs")
            if not set(proposal.based_on_observation_ids) <= {o["observation_id"] for o in self.observations}:
                raise ValueError("unknown observation")
            if not set(proposal.evidence_refs) <= set(self.capabilities.documents) | set(self.capabilities.windows):
                raise ValueError("unknown evidence")
            action = proposal.action
            if action.type == "finish":
                if not set(action.unresolved_need_ids) <= ids:
                    raise ValueError("unknown need")
                commit()
                state.terminal_request = action.model_dump()
                self.stop = "model_finish"
                self.actions.append({"selected_by": "llm", "tool": "finish", "reason_code": proposal.reason_code})
                return self.finalize(state)
            if action.type == "abstain":
                commit()
                state.terminal_request = action.model_dump()
                self.stop = "model_abstain"
                self.actions.append({"selected_by": "llm", "tool": "abstain", "reason_code": proposal.reason_code})
                return self.finalize(state)
            if action.type == "clarify":
                self._validate_clarification(action, proposal, state)
                commit()
                state.terminal_request = action.model_dump()
                self.stop = "model_clarify"
                self.actions.append({"selected_by": "llm", "tool": "clarify", "reason_code": proposal.reason_code})
                return self.terminal(state, "partial" if any(state.evidence_by_aspect.values()) else "clarify",
                                     "partial_evidence" if any(state.evidence_by_aspect.values()) else "clarification_needed")
            if action.type == "search":
                if self.task_mode:
                    query = task_search_query(state.analysis.original_question, action.query, mode=action.query_mode,
                        needs=[n for n in staged.needs if n.need_id in proposal.target_need_ids],
                        replies=[r["reply"] for r in state.clarification_replies])
                else:
                    query = validate_rewrite(state.analysis.original_question, action.query, mode=action.query_mode,
                        need_texts=[n.text for n in staged.needs if n.need_id in proposal.target_need_ids])
                fingerprint = normalized_action_text(query)
                resolved = AgentAction(sequence=state.budget_state.steps+1, tool="search", purpose="targeted evidence search",
                    aspect=state.analysis.required_aspects[0], search_request=SearchRequest(request_id=self.capabilities.nonce,
                    user=state.user, filters=state.analysis.filters, query=query, purpose="targeted evidence search", top_k=state.top_k,
                    candidate_k=min(200,max(state.top_k,state.top_k*4))))
            elif action.type == "find":
                fingerprint = (action.document_ref, normalized_action_text(action.pattern), action.section_ref)
                resolved = self.capabilities.resolve_find(action, state)
                self.found.add(fingerprint)
            else:
                resolved = self.capabilities.resolve_open(action, state)
            key = self._action_key(resolved)
            if key in self.executed:
                if (self.retry_action is None or self.retried or proposal.reason_code != "retryable_tool_error"
                    or key != self._action_key(self.retry_action)):
                    raise ValueError("duplicate operation")
                self.retried = True
                self.retry_action = None
            if self.remaining(state)[action.type] <= 0:
                raise ValueError("tool budget unavailable")
            commit()
            self.actions.append({"selected_by": "llm", "tool": action.type, "reason_code": proposal.reason_code})
            return ControllerDecision(action=resolved)
        except PolicyContextExceeded:
            self.stop = "policy_context_limit"
            return self.finalize(state)
        except (ValueError, TypeError) as exc:
            if isinstance(exc, TaskNeedCapacityExceeded):
                state.task_plan = state.task_plan.model_copy(update={"overflow": True})
            self.rejections += 1
            self.no_progress += 1
            rejection = {"schema_version": "2", "observation_id": f"O{len(self.observations)+1}",
                "for_action_id": None, "tool": "host", "status": "rejected", "results": [],
                "progress": {"new_evidence_units": 0, "new_windows": 0, "useful_negative_result": False},
                "error": {"code": "protected_constraint_changed" if "protected" in str(exc) else "invalid_proposal",
                          "retryable": False, "message": "Proposal rejected; use only allowed actions, current refs and unchanged constraints."},
                "remaining": self.remaining(state)}
            if self.task_mode and not state.task_plan.needs:
                rejection["observation_id"] = "I0"
                self.observations[:] = [rejection]
            else:
                self.observations.append(rejection)
            return None
        except Exception:
            self.stop = "policy_unavailable"
            return self.finalize(state)

    def _validate_clarification(self, action, proposal, state):
        if not set(action.missing_need_ids) <= set(proposal.target_need_ids) or len(state.clarification_replies) >= 2:
            raise ValueError("clarification unavailable")
        if re.search(r"密码|令牌|身份证|token|password|secret|管理员|租户|tenant", action.question+" ".join(action.options), re.I):
            raise ValueError("sensitive clarification")
        if self.task_mode:
            return
        personal = any(n.clarification_needed for n in state.task_plan.needs) or re.search(r"我|这笔|这次|本次", state.analysis.original_question)
        if not personal or not re.search(r"业务|单位|类型|金额|费用|地点|时间|总部|分部", action.question):
            raise ValueError("not a supported user-fact gap")

    def finalize(self, state):
        if any(state.evidence_by_aspect.values()):
            plan=state.task_plan
            if self.task_mode:
                # This is permission to generate, NOT permission to publish
                # answered. The one publisher recomputes final per-need support.
                return self.terminal(state, "answered", "completed")
            if (plan.needs and all(n.evidence_ids and not n.clarification_needed for n in plan.needs)
                and not plan.overflow and not plan.read_incomplete and not plan.model_relevance_used
                and not state.ledger.conflicting_aspects and (state.terminal_request or {}).get("type")!="abstain"):
                # Generation and the unique publisher still verify actual final claims.
                return self.terminal(state,"answered","completed")
            return self.terminal(state, "partial", "partial_evidence")
        return self.terminal(state, "not_found", "not_found")

    @staticmethod
    def _action_key(action):
        if action.tool == "search":
            return ("search", normalized_action_text(action.search_request.query))
        if action.tool == "find":
            request = action.find_request
            return ("find", request.doc_id, normalized_action_text(request.pattern), request.anchor_chunk_id)
        request = action.open_request
        return ("open", request.target_type, request.target_id, request.start_char, request.max_chars)

    def terminal(self, state, mode, reason):
        self.phase = "finalizing"
        return _terminal(state.budget_state.steps+1, tool="answer" if mode in {"partial","answered"} else "stop",
                         mode=mode, stop_reason=reason, purpose="host-controlled finalization")

    def trace(self):
        return {"phase": self.phase, "handoffs": self.handoffs, "proposal_count": self.proposal_count,
                "rejected_proposals": self.rejections, "stop": self.stop, "actions": self.actions,
                "observation_statuses": [{"tool": o["tool"], "status": o["status"]} for o in self.observations],
                "authorization_basis": "request_scope_snapshot_no_realtime_revocation_source"}

    def seal(self):
        self.phase = "sealed"
        self.capabilities.seal()
