"""Curated evaluation test cases for FinAgent compliance queries.

Each case has:
  question   — the compliance query sent to the agent
  reference  — optional ground-truth (used by RAGAS ContextRecall / Precision)
  tags       — topic labels for filtering eval runs
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvalCase:
    question: str
    reference: str = ""
    tags: list[str] = field(default_factory=list)


EVAL_CASES: list[EvalCase] = [
    # ── Sanctions ─────────────────────────────────────────────────────────
    EvalCase(
        question="Is Roman Abramovich subject to any international sanctions? Which jurisdictions?",
        reference=(
            "Roman Abramovich is sanctioned by the UK (OFSI), EU, and other Western "
            "jurisdictions following the 2022 Russia-Ukraine conflict, with asset freezes "
            "and travel bans."
        ),
        tags=["sanctions", "russia"],
    ),
    EvalCase(
        question="What is Oleg Deripaska's sanctions status and what companies is he associated with?",
        tags=["sanctions", "russia", "graph"],
    ),
    EvalCase(
        question="List the primary relationship types used to connect sanctioned Russian entities in the dataset.",
        tags=["sanctions", "graph", "schema"],
    ),
    EvalCase(
        question="Which entities from North Korea appear in the OpenSanctions dataset?",
        tags=["sanctions", "north_korea"],
    ),
    # ── PEP / AML ─────────────────────────────────────────────────────────
    EvalCase(
        question=(
            "What are the defining characteristics of a politically exposed person (PEP) "
            "and what AML risks do they present?"
        ),
        reference=(
            "PEPs are individuals holding or having held prominent public positions. "
            "Risks include bribery, corruption, and laundering of misappropriated public funds. "
            "Enhanced due diligence is required under FATF guidance."
        ),
        tags=["pep", "aml"],
    ),
    EvalCase(
        question=(
            "How should a compliance officer handle a payment from a PEP in a "
            "high-risk jurisdiction according to FATF guidelines?"
        ),
        tags=["pep", "aml", "compliance"],
    ),
    EvalCase(
        question="What is the difference between a domestic PEP and a foreign PEP for AML purposes?",
        tags=["pep", "aml"],
    ),
    # ── Offshore / ICIJ ───────────────────────────────────────────────────
    EvalCase(
        question="What types of offshore structures appear most frequently in the Panama Papers data?",
        tags=["icij", "offshore"],
    ),
    EvalCase(
        question=(
            "Which jurisdictions are most commonly used for shell company formation "
            "according to the ICIJ Offshore Leaks database?"
        ),
        tags=["icij", "offshore"],
    ),
    # ── SEC ───────────────────────────────────────────────────────────────
    EvalCase(
        question="Summarise recent SEC enforcement actions related to OFAC sanctions violations.",
        tags=["sec", "ofac", "enforcement"],
    ),
    EvalCase(
        question=(
            "What disclosures have public companies made regarding beneficial ownership "
            "risk in recent 10-K filings?"
        ),
        tags=["sec", "beneficial_ownership"],
    ),
    # ── Court ─────────────────────────────────────────────────────────────
    EvalCase(
        question="What legal precedents exist in US courts for prosecuting trade-based money laundering?",
        tags=["court", "aml", "tbml"],
    ),
    EvalCase(
        question=(
            "Describe the elements prosecutors must prove in a wire fraud case involving "
            "offshore accounts, citing relevant case law."
        ),
        tags=["court", "wire_fraud"],
    ),
    # ── Procurement ───────────────────────────────────────────────────────
    EvalCase(
        question=(
            "Which federal agencies have awarded the largest cybersecurity intelligence "
            "contracts, and to whom?"
        ),
        tags=["procurement", "cybersecurity"],
    ),
    # ── Cross-database (require retrieval across multiple sources) ───────────
    # Sanctions ↔ ICIJ
    EvalCase(
        question=(
            "Does Roman Abramovich appear in any ICIJ offshore leak dataset (Panama Papers, "
            "Offshore Leaks, Pandora Papers)? If so, in which jurisdictions were his offshore "
            "structures registered?"
        ),
        reference=(
            "Roman Abramovich appears in ICIJ offshore leak records with structures in "
            "British Virgin Islands and other secrecy jurisdictions, in addition to being "
            "subject to UK, EU and allied sanctions."
        ),
        tags=["cross_db", "sanctions", "icij", "russia"],
    ),
    EvalCase(
        question=(
            "Which individuals listed in the OpenSanctions dataset also appear in the "
            "Panama Papers or Pandora Papers? Name at least two and describe their offshore "
            "structures."
        ),
        tags=["cross_db", "sanctions", "icij", "offshore"],
    ),
    EvalCase(
        question=(
            "Identify sanctioned North Korean entities that also appear in ICIJ offshore "
            "leak records and describe the shell-company structures used."
        ),
        tags=["cross_db", "sanctions", "icij", "north_korea"],
    ),
    # Sanctions ↔ SEC
    EvalCase(
        question=(
            "Which public companies have disclosed material OFAC sanctions risk in SEC 10-K "
            "filings while simultaneously having a named officer or director appearing in the "
            "OpenSanctions dataset?"
        ),
        tags=["cross_db", "sanctions", "sec", "beneficial_ownership"],
    ),
    EvalCase(
        question=(
            "Summarise SEC enforcement actions against firms whose sanctioned counterparties "
            "also appear in the OpenSanctions database. What penalties were imposed?"
        ),
        tags=["cross_db", "sanctions", "sec", "enforcement"],
    ),
    # Sanctions ↔ Court
    EvalCase(
        question=(
            "Are there US federal court cases where a defendant is also listed on the OFAC "
            "SDN list or the EU consolidated sanctions list? Provide case names and charges."
        ),
        tags=["cross_db", "sanctions", "court"],
    ),
    EvalCase(
        question=(
            "What criminal charges have been brought against Oleg Deripaska or his associated "
            "companies in US courts, and how do those charges relate to his OFAC sanctions "
            "designation?"
        ),
        tags=["cross_db", "sanctions", "court", "russia"],
    ),
    # ICIJ ↔ Court
    EvalCase(
        question=(
            "Which shell companies registered in the British Virgin Islands and documented in "
            "ICIJ offshore leak data have also appeared as defendants or subjects in US federal "
            "court proceedings?"
        ),
        tags=["cross_db", "icij", "court", "offshore"],
    ),
    EvalCase(
        question=(
            "Describe US court cases that cited Panama Papers evidence. What offences were "
            "charged and what was the outcome?"
        ),
        tags=["cross_db", "icij", "court"],
    ),
    # PEP ↔ Sanctions ↔ ICIJ (triple cross)
    EvalCase(
        question=(
            "Identify politically exposed persons (PEPs) who appear in both an international "
            "sanctions list and an ICIJ offshore leak dataset. What AML red flags does the "
            "combination present?"
        ),
        tags=["cross_db", "pep", "sanctions", "icij", "aml"],
    ),
    # PEP ↔ SEC
    EvalCase(
        question=(
            "Have any SEC-registered public companies disclosed business relationships with "
            "politically exposed persons (PEPs) in recent proxy statements or 10-K risk "
            "factors? What enhanced due-diligence steps did they describe?"
        ),
        tags=["cross_db", "pep", "sec", "aml"],
    ),
    # Procurement ↔ Sanctions
    EvalCase(
        question=(
            "Are any companies that received US federal procurement contracts in the last "
            "three years also listed in international sanctions databases? Name the companies "
            "and the sanctioning authority."
        ),
        tags=["cross_db", "procurement", "sanctions"],
    ),
    EvalCase(
        question=(
            "Which US government contractors awarded cybersecurity or intelligence contracts "
            "have subsidiaries or beneficial owners that appear in OFAC or EU sanctions lists?"
        ),
        tags=["cross_db", "procurement", "sanctions", "cybersecurity"],
    ),
    # SEC ↔ Court
    EvalCase(
        question=(
            "Which SEC enforcement actions for OFAC violations have also led to parallel "
            "criminal indictments in US federal courts? Compare the civil and criminal "
            "outcomes."
        ),
        tags=["cross_db", "sec", "court", "ofac", "enforcement"],
    ),
    # Beneficial-ownership chain (multi-source)
    EvalCase(
        question=(
            "Trace the full beneficial ownership chain of a company that appears in both "
            "ICIJ offshore leak data and a US SEC filing. Identify any links to sanctioned "
            "individuals or entities at any layer of the chain."
        ),
        tags=["cross_db", "icij", "sec", "sanctions", "beneficial_ownership", "graph"],
    ),
    # ── Hallucination traps (no relevant data expected in corpus) ─────────
    EvalCase(
        question="What is Apple's current stock price?",
        reference="",
        tags=["hallucination_trap"],
    ),
    EvalCase(
        question="Describe FinAgent's internal database schema in detail.",
        reference="",
        tags=["hallucination_trap"],
    ),
    EvalCase(
        question="Who won the most recent FIFA World Cup?",
        reference="",
        tags=["hallucination_trap"],
    ),
]
