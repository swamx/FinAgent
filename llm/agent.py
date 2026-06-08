from __future__ import annotations

import json as _json
import logging
import re
from dataclasses import dataclass

from core.models import SearchResult
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.usage import UsageLimits
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from core.config import settings
from graph.exposure_service import ExposureService
from graph.redis_graph_repository import RedisGraphRepository
from observability.circuit_breakers import llm_breaker
from observability.metrics import llm_duration, llm_errors, tool_calls_total
from observability.tracing import get_tracer
from vector.retriever import RetrievalService

_log = logging.getLogger(__name__)

_STOPWORDS = frozenset({
    # Common function words
    "is", "are", "was", "the", "and", "or", "in", "on", "at", "of",
    "for", "to", "what", "which", "who", "how", "does", "do", "has",
    "any", "not", "its", "his", "her", "their", "this", "that",
    # Business-entity suffixes — shouldn't extend an entity-name caps-run
    "inc", "llc", "ltd", "corp", "co", "plc",
    # Common government/geo abbreviations that appear adjacent to company names
    # in agent search queries (e.g. "METGREEN SOLUTIONS INC VA contract")
    "va", "us", "uk", "eu", "un",
})


def _extract_caps_mentions(query: str) -> list[str]:
    """Extract probable entity names from caps/title-case runs in the query.

    Groups only tokens of the SAME case type (all-isupper or all-istitle) that
    are adjacent in the original sentence.  Mixed-type adjacency (e.g. "SAIC"
    followed by "Department") is NOT grouped — this prevents false compound
    names like "SAIC Department" from triggering the mismatch guard.
    """
    tokens = re.split(r"\s+", query.strip("?.,!"))
    # (original_idx, clean_token, is_all_caps)
    indexed: list[tuple[int, str, bool]] = []
    for i, t in enumerate(tokens):
        clean = re.sub(r"’s$|’s$", "", t.strip("’\",.?!"))
        if (len(clean) >= 2
                and (clean.isupper() or clean.istitle())
                and clean.lower() not in _STOPWORDS):
            indexed.append((i, clean, clean.isupper()))

    groups: list[str] = []
    current: list[str] = []
    last_idx = -2
    last_is_upper: bool | None = None
    for idx, tok, is_upper in indexed:
        # Allow grouping if same type (UPPER+UPPER or Title+Title) OR the
        # previous token is title-case and the current is all-caps — this
        # captures "firstname SURNAME" patterns (e.g. "Khalid SBAA").
        # Explicitly block all-caps followed by title-case to avoid false
        # compounds like "SAIC Department".
        can_extend = (
            idx == last_idx + 1
            and (is_upper == last_is_upper
                 or (last_is_upper is False and is_upper))
        )
        if can_extend:
            current.append(tok)
        else:
            if len(current) >= 2:
                groups.append(" ".join(current))
            elif len(current) == 1 and current[0].isupper():
                groups.append(current[0])
            current = [tok]
            last_is_upper = is_upper
        last_idx = idx
    if len(current) >= 2:
        groups.append(" ".join(current))
    elif len(current) == 1 and current[0].isupper():
        groups.append(current[0])
    return groups


def _name_in_text(name: str, text: str) -> bool:
    """Return True if name appears in text, forward or 2-token reverse order.

    Reverse order handles surname-first profiles (e.g. "EFENDIEVA KHAVA" in
    a document matches query "KHAVA EFENDIEVA") without the false-pass risk
    of individual-token matching.
    """
    tokens = name.lower().split()
    if " ".join(tokens) in text:
        return True
    if len(tokens) == 2 and f"{tokens[1]} {tokens[0]}" in text:
        return True
    return False


def _contract_signal(result: SearchResult, query: str, resolver) -> str | None:
    """Return entity name if it appears in a USASpending contract doc in result.

    Used to prepend a positive "entity found in contracts" hint to the
    search_documents return value, so the agent does not dismiss contract
    records as irrelevant when asked a compliance question.

    Only fires when:
    - At least one returned document has source "procurement" (USASpending)
    - The entity name extracted from the query appears in that document's text
    """
    spending_docs = [
        d for d in result.documents
        if (d.source or "").lower() == "procurement"
    ]
    if not spending_docs:
        return None

    caps = _extract_caps_mentions(query)
    spacy_mentions = resolver.extract_mentions(query)
    seen: set[str] = set()
    candidates: list[str] = []
    for m in caps + spacy_mentions:
        if m not in seen:
            seen.add(m)
            candidates.append(m)

    spending_text = " ".join(d.text.lower() for d in spending_docs)
    for name in candidates:
        if _name_in_text(name, spending_text):
            return name
    return None


def _mismatch_names(result: SearchResult, query: str, resolver) -> list[str]:
    """Return entity names from query absent from retrieved docs.

    Always combines regex caps-runs and spaCy mentions (no short-circuit) so
    that mixed-case names like "Khalid SBAA" are caught via spaCy even when
    the caps-only regex only finds "SBAA" alone.

    Uses any-order token matching to handle surname-first profiles
    ("EFENDIEVA KHAVA" matches "KHAVA EFENDIEVA" query).

    Filters to multi-word mentions with at least one ALL-CAPS token to avoid
    false fires on title-case-only phrases ("Panama Papers", "Veterans Affairs").
    """
    caps = _extract_caps_mentions(query)
    spacy = resolver.extract_mentions(query)
    # Deduplicate while preserving order (caps results take priority)
    seen: set[str] = set()
    candidates: list[str] = []
    for m in caps + spacy:
        if m not in seen:
            seen.add(m)
            candidates.append(m)

    mentions = [
        m for m in candidates
        if (len(m.split()) >= 2 and any(tok.isupper() for tok in m.split()))
        or (len(m.split()) == 1 and m.isupper() and len(m) >= 8)
    ]
    if not mentions:
        return []
    all_text = " ".join(d.text.lower() for d in result.documents)
    return [m for m in mentions if not _name_in_text(m, all_text)]


@dataclass
class AgentDeps:
    retrieval: RetrievalService
    graph: RedisGraphRepository
    exposure: ExposureService
    preflight_resolved: bool = False  # True when pre-flight found graph entities


_model = OpenAIModel(
    settings.primary_model,
    provider=OpenAIProvider(
        base_url=settings.litellm_base_url,
        api_key=settings.litellm_api_key,
    ),
)

agent = Agent(
    _model,
    deps_type=AgentDeps,
    system_prompt=(
        "You are a compliance analyst for AML, PEP, and sanctions investigations. "
        "Use the available tools to retrieve entities, check exposure, and surface "
        "relevant documents. Be concise and cite specific entity IDs where relevant. "
        "After every factual claim, cite the data source in square brackets. "
        "Use the source field from the retrieved documents or tool results. "
        "Known sources: [SEC EDGAR], [CourtListener], [ICIJ Offshore Leaks], "
        "[USASpending], [GDELT News], [OpenSanctions]. "
        "Example: 'Acme Corp received a $2M fine for OFAC violations [SEC EDGAR]. "
        "The company is connected to three sanctioned individuals [OpenSanctions].' "
        "CRITICAL — NO FABRICATION: Do NOT invent specific facts — entity names, "
        "sanctions designations, contract values, financial figures, legal outcomes, "
        "or PEP/watchlist status — that are absent from tool results. Base every "
        "claim about a specific entity, contract, or sanction exclusively on what "
        "the tools returned. If tools return no relevant information about the "
        "queried entity, respond concisely: 'I could not find [entity] in the "
        "knowledge base.' If retrieved documents are entirely irrelevant to the "
        "question, state: 'The retrieved context does not contain information "
        "about [topic]. I could not find this in the knowledge base.' "
        "Do not redirect, do not explain system limitations at length, do not "
        "offer alternative topics. "
        "DATA FORMAT: A document field 'PEP/Sanctions flag: NO' means the entity "
        "is NOT designated as a PEP or placed on a sanctions list — do not "
        "describe such an entity as sanctioned or flagged. Always cite the exact "
        "dataset name when reporting that an entity appears in a database. "
        "IMPORTANT: If expand_entity or get_entity returns 'not found', ALWAYS "
        "follow up with search_documents using the same name before concluding "
        "the entity does not exist — the search index may have data even when "
        "the graph lookup fails. Only say 'not found' after search_documents "
        "also returns no relevant results. "
        "IMPORTANT: When a tool result begins with a CONTEXT MISMATCH warning, "
        "respond ONLY with: 'I could not find [the named entity] in the knowledge "
        "base.' Do not add any other details."
    ),
)


@agent.tool
def search_documents(ctx: RunContext[AgentDeps], query: str) -> str:
    """Semantic + graph hybrid search over compliance documents."""
    tracer = get_tracer()
    tool_calls_total.add(1, {"tool": "search_documents"})
    with tracer.start_as_current_span("tool.search_documents") as span:
        span.set_attribute("tool.name", "search_documents")
        span.set_attribute("tool.input.query", query)
        result = ctx.deps.retrieval.search(query)

        # ── Context mismatch guard (secondary — pre-flight is primary) ───────
        # Skip entirely when pre-flight already confirmed the entity is in the
        # knowledge base (preflight_resolved=True).  Only run for queries where
        # the entity might genuinely be absent (preflight found nothing).
        warning = ""
        if not result.entities and not ctx.deps.preflight_resolved:
            missing = _mismatch_names(result, query, ctx.deps.retrieval.resolver)
            if missing:
                warning = (
                    f"CONTEXT MISMATCH: retrieved documents contain no mention of "
                    + ", ".join(f'"{m}"' for m in missing)
                    + f". You MUST respond: 'I could not find {missing[0]} in the "
                    f"knowledge base.' Do NOT use your training knowledge."
                )

        contract_name: str | None = None
        if warning:
            json_result = warning
        else:
            json_result = result.model_dump_json()
            # Positive contract signal: tell agent explicitly when the queried
            # entity appears in USASpending records so it doesn't dismiss them.
            contract_name = _contract_signal(
                result, query, ctx.deps.retrieval.resolver
            )
            if contract_name:
                json_result = (
                    f"CONTRACT FOUND: '{contract_name}' appears in federal "
                    f"contract records in the results below "
                    f"(source: [USASpending]). Report the contract details "
                    f"and cite [USASpending].\n\n" + json_result
                )

        span.set_attribute("tool.output.entities_found", len(result.entities))
        span.set_attribute("tool.output.docs_returned", len(result.documents))
        _log.info(
            "tool_call tool=search_documents entities=%d docs=%d query=%r "
            "warning=%s contract_signal=%s",
            len(result.entities), len(result.documents), query[:120],
            bool(warning), bool(contract_name),
        )
        return json_result


@agent.tool
def get_entity(ctx: RunContext[AgentDeps], entity_id: str) -> str:
    """Fetch the full profile for a known entity ID."""
    tracer = get_tracer()
    tool_calls_total.add(1, {"tool": "get_entity"})
    with tracer.start_as_current_span("tool.get_entity") as span:
        span.set_attribute("tool.name", "get_entity")
        span.set_attribute("tool.input.entity_id", entity_id)
        result = ctx.deps.graph.get_entity_profile(entity_id)
        _log.info("tool_call tool=get_entity entity_id=%r", entity_id)
        span.set_attribute("tool.output.found", bool(result.get("data")))
        return str(result)


@agent.tool
def get_exposure(ctx: RunContext[AgentDeps], entity_id: str) -> str:
    """Return PEP/sanctions exposure and related entity graph for an entity."""
    tracer = get_tracer()
    tool_calls_total.add(1, {"tool": "get_exposure"})
    with tracer.start_as_current_span("tool.get_exposure") as span:
        span.set_attribute("tool.name", "get_exposure")
        span.set_attribute("tool.input.entity_id", entity_id)
        result = ctx.deps.exposure.get_exposure(entity_id)
        _log.info("tool_call tool=get_exposure entity_id=%r", entity_id)
        return str(result)


@agent.tool
def expand_entity(ctx: RunContext[AgentDeps], entity_name: str) -> str:
    """Resolve a name to an entity and return its 2-hop graph neighbourhood."""
    tracer = get_tracer()
    tool_calls_total.add(1, {"tool": "expand_entity"})
    with tracer.start_as_current_span("tool.expand_entity") as span:
        span.set_attribute("tool.name", "expand_entity")
        span.set_attribute("tool.input.entity_name", entity_name)
        entities = ctx.deps.retrieval.resolver.extract_and_resolve(entity_name)
        if not entities:
            span.set_attribute("tool.output.resolved", False)
            _log.info("tool_call tool=expand_entity entity_name=%r resolved=False", entity_name)
            return (
                f"Entity '{entity_name}' not found in the graph. "
                "Do not call this tool again with the same name. "
                "Use search_documents instead to find relevant information."
            )
        related = ctx.deps.graph.expand_entity(entities[0].id)
        span.set_attribute("tool.output.resolved", True)
        span.set_attribute("tool.output.entity_id", entities[0].id)
        span.set_attribute("tool.output.related_count", len(related))
        _log.info(
            "tool_call tool=expand_entity entity_name=%r resolved_id=%r related=%d",
            entity_name, entities[0].id, len(related),
        )
        return str([e.model_dump() for e in related])


class ComplianceAgent:
    def __init__(self, deps: AgentDeps):
        self.deps = deps

    async def answer(self, question: str) -> str:
        import time
        tracer = get_tracer()
        t0 = time.time()
        with tracer.start_as_current_span("llm.agent_run") as span:
            span.set_attribute("question.length", len(question))

            # ── Pre-flight mismatch check ─────────────────────────────────
            # If the question names an entity not in the knowledge base,
            # return "not found" immediately — don't let the small LLM
            # fabricate from training data.
            preflight = self.deps.retrieval.search(question)
            if not preflight.entities:
                missing = _mismatch_names(
                    preflight, question, self.deps.retrieval.resolver
                )
                if missing:
                    _log.info(
                        "preflight_mismatch question=%r missing=%r",
                        question[:80], missing,
                    )
                    return (
                        f"I could not find {missing[0]} in the knowledge base."
                    )
            else:
                # Entity resolved at pre-flight — tell tools to skip the guard.
                self.deps.preflight_resolved = True

            try:
                result = await llm_breaker.call_async(
                    agent.run, question, deps=self.deps,
                    usage_limits=UsageLimits(request_limit=8),
                )
                llm_duration.record(time.time() - t0)
                return result.data
            except UsageLimitExceeded as exc:
                # Agent hit the 8-request cap — return whatever it produced so far
                llm_duration.record(time.time() - t0)
                partial = getattr(exc, "output", None) or getattr(exc, "result", None)
                if partial and isinstance(partial, str):
                    return partial
                return (
                    "I was unable to complete the full analysis within the request limit. "
                    "Please try rephrasing with a more specific question."
                )
            except Exception as exc:
                llm_errors.add(1)
                span.record_exception(exc)
                raise
