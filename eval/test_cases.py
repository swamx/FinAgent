"""Curated evaluation test cases for FinAgent compliance queries.

All questions are grounded in data actually present in the index:
  - graph_profile: OpenSanctions / WikiData entity profiles
  - news: Panama Papers, offshore wealth, OFAC/BIS, Treasury 2026
  - procurement: US federal contract awards (VA, DFC, CFTC, etc.)

Each case has:
  question   — the compliance query sent to the agent
  reference  — ground-truth text used by RAGAS ContextRecall / Precision
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

    # ── Graph / OpenSanctions — person entities ────────────────────────────

    EvalCase(
        question="Is KHAVA EFENDIEVA on the Interpol red notices list and does she appear on any European sanctions list?",
        reference=(
            "KHAVA EFENDIEVA appears in two datasets: interpol_red_notices and "
            "be_fod_sanctions (Belgian Federal Public Service sanctions). "
            "Her PEP/Sanctions flag is YES."
        ),
        tags=["graph", "opensanctions", "interpol", "sanctions"],
    ),
    EvalCase(
        question="Which sanctions lists include Vitaly KULIKOV, and what is his PEP/sanctions flag?",
        reference=(
            "Vitaly KULIKOV is listed in be_fod_sanctions, fr_tresor_gels_avoir, "
            "mc_fund_freezes, eu_fsf, and eu_journal_sanctions. "
            "His PEP/Sanctions flag is YES."
        ),
        tags=["graph", "opensanctions", "sanctions", "eu"],
    ),
    EvalCase(
        question="Is Jian Xia on the Dutch most-wanted list? What other law enforcement databases include this person?",
        reference=(
            "Jian Xia is listed in both interpol_red_notices and nl_most_wanted "
            "(Dutch most wanted). The PEP/Sanctions flag is NO."
        ),
        tags=["graph", "opensanctions", "interpol", "law_enforcement"],
    ),
    EvalCase(
        question="What dataset lists SANAVBARI NIKITENKO and what is their entity type?",
        reference=(
            "SANAVBARI NIKITENKO is a Person listed in the interpol_red_notices dataset. "
            "Their PEP/Sanctions flag is NO."
        ),
        tags=["graph", "opensanctions", "interpol"],
    ),
    EvalCase(
        question="Is DZHAMBULAT GALIMOV listed on any Interpol database?",
        reference=(
            "DZHAMBULAT GALIMOV is a Person listed in the interpol_red_notices dataset."
        ),
        tags=["graph", "opensanctions", "interpol"],
    ),
    EvalCase(
        question="What is Eduardo GONZALEZ QUIRARTE's entity type and which datasets list this individual?",
        reference=(
            "Eduardo GONZALEZ QUIRARTE is a Person. "
            "Datasets include us_sam_exclusions, us_trade_csl, and us_ofac_sdn."
        ),
        tags=["graph", "opensanctions", "ofac", "us_sanctions"],
    ),
    EvalCase(
        question="Is Khalid SBAA flagged in any European sanctions database?",
        reference=(
            "Khalid SBAA is a Person listed in be_fod_sanctions (Belgian sanctions). "
            "PEP/Sanctions flag is YES."
        ),
        tags=["graph", "opensanctions", "sanctions", "eu"],
    ),
    EvalCase(
        question="What entity type is MANDALA and which sanctions regime has designated it?",
        reference=(
            "MANDALA is a Vessel listed in ua_war_sanctions (Ukrainian war sanctions) "
            "and gb_fcdo_sanctions. Its PEP/Sanctions flag is YES."
        ),
        tags=["graph", "opensanctions", "vessel", "war_sanctions"],
    ),

    # ── Graph / OpenSanctions — company entities ───────────────────────────

    EvalCase(
        question="What type of entity is Myanmar Yatai International Holding Group Co., Ltd. and which US sanctions lists include it?",
        reference=(
            "Myanmar Yatai International Holding Group Co., Ltd. is a Company. "
            "It appears in us_sam_exclusions, ext_us_ofac_press_releases, us_ofac_sdn, "
            "opencorporates, and us_trade_csl. PEP/Sanctions flag is NO."
        ),
        tags=["graph", "opensanctions", "ofac", "myanmar"],
    ),
    EvalCase(
        question="Is Limited Liability Company Rustmash listed under US OFAC sanctions and Ukrainian war sanctions?",
        reference=(
            "Limited Liability Company Rustmash is a Company listed in "
            "us_sam_exclusions, ua_war_sanctions, ext_us_ofac_press_releases, "
            "us_ofac_sdn, and us_trade_csl. PEP/Sanctions flag is YES."
        ),
        tags=["graph", "opensanctions", "ofac", "war_sanctions"],
    ),
    EvalCase(
        question="Which datasets include MARJAN METHANOL COMPANY and what is its entity type?",
        reference=(
            "MARJAN METHANOL COMPANY is a Company listed in permid, "
            "us_sam_exclusions, us_trade_csl, and us_ofac_sdn."
        ),
        tags=["graph", "opensanctions", "ofac", "iran"],
    ),

    # ── News / Panama Papers / Offshore ───────────────────────────────────

    EvalCase(
        question="How did the Panama Papers revelations affect Nigeria's transparency laws and regulatory policies?",
        reference=(
            "The Panama Papers rewrote Nigeria's transparency law and sparked "
            "regulatory policies focused on beneficial ownership and shell company "
            "disclosure, requiring stronger anti-money-laundering measures."
        ),
        tags=["news", "panama_papers", "beneficial_ownership", "nigeria"],
    ),
    EvalCase(
        question="What did the Treasury 2026 National Risk Assessments signal about beneficial ownership exposure?",
        reference=(
            "The Treasury 2026 National Risk Assessments signal expanding exposure "
            "related to beneficial ownership and shell company risks."
        ),
        tags=["news", "treasury", "beneficial_ownership", "risk"],
    ),
    EvalCase(
        question="What are the legal risks for a person reporting OFAC or BIS violations — are they a whistleblower, witness, or confidential source?",
        reference=(
            "A reporting person may be classified as a whistleblower (with statutory "
            "protections), witness, or confidential source, each carrying different "
            "legal risks and protections under OFAC and BIS violation frameworks."
        ),
        tags=["news", "ofac", "bis", "whistleblower", "compliance"],
    ),
    EvalCase(
        question="According to recent investigations, how many Nigerian politicians have hidden assets in Dubai and what is the estimated value?",
        reference=(
            "Over 200 Nigerian politicians, governors, senators, security chiefs, "
            "and other politically connected individuals have stashed at least $7 billion "
            "in Dubai properties across at least 1,824 traced assets."
        ),
        tags=["news", "pep", "offshore", "nigeria"],
    ),
    EvalCase(
        question="What has academic research said about the silence surrounding offshore wealth?",
        reference=(
            "Academic discourse has highlighted a deafening silence around offshore "
            "wealth, with opinion pieces from sources including The Jakarta Post and "
            "Bangkok Post pointing to the lack of transparency around hidden offshore assets."
        ),
        tags=["news", "offshore", "academic"],
    ),
    EvalCase(
        question="Ten years after the Panama Papers, what progress has been made in pursuing tax justice?",
        reference=(
            "A decade after the Panama Papers, enablers and tax cheats continue to be "
            "brought to justice. The long pursuit of tax justice continues, with "
            "investigations and prosecutions still ongoing globally."
        ),
        tags=["news", "panama_papers", "tax_justice"],
    ),
    EvalCase(
        question="What was a notable pump and dump scheme case involving British Columbia residents?",
        reference=(
            "Four British Columbia residents were fined millions for a pump and dump "
            "scheme by a Quebec tribunal."
        ),
        tags=["news", "fraud", "enforcement"],
    ),
    EvalCase(
        question="What is Beijing's new red line regarding offshore firms and China operations?",
        reference=(
            "Beijing's new red line restricts offshore firms from fully de-listing "
            "or separating from China, signalling new compliance exposure for companies "
            "using offshore structures to distance themselves from Chinese operations."
        ),
        tags=["news", "offshore", "china", "compliance"],
    ),

    # ── Procurement ────────────────────────────────────────────────────────

    EvalCase(
        question="What was the value and purpose of the SAIC contract awarded by the Department of Veterans Affairs under the T4NG vehicle?",
        reference=(
            "Science Applications International Corporation (SAIC) received a contract "
            "valued at $141,683,156 USD from the Department of Veterans Affairs under "
            "the T4NG (Transformation Twenty-One Total Technology Next Generation) vehicle, "
            "to provide on-site professional and technical IT support services for the "
            "VA Financial Services Center (FSC)."
        ),
        tags=["procurement", "va", "saic", "t4ng"],
    ),
    EvalCase(
        question="What services did PRO-SPHERE TEK, INC. provide under its VA contract and what was the contract value?",
        reference=(
            "PRO-SPHERE TEK, INC. received a T&M task order valued at $6,104,627 USD "
            "from the Department of Veterans Affairs to provide continued professional "
            "and IT services supporting the VA FSC Financial Technology Service, "
            "including IT infrastructure operations, software projects, and deliverables "
            "aligned with the Veterans-Focused Integration Process (VIP)."
        ),
        tags=["procurement", "va", "it_services"],
    ),
    EvalCase(
        question="What did ECONOMETRICA, INC. perform for the Export-Import Bank of the United States?",
        reference=(
            "ECONOMETRICA, INC. received a contract valued at $437,112 USD from the "
            "Export-Import Bank of the United States for financial technology (fintech) analysis."
        ),
        tags=["procurement", "exim_bank", "fintech"],
    ),
    EvalCase(
        question="What is the purpose of the METGREEN SOLUTIONS INC contract with the Department of Veterans Affairs?",
        reference=(
            "METGREEN SOLUTIONS INC received a $403,480 USD contract from the "
            "Department of Veterans Affairs to replace the end-of-lifecycle IBM FileNet "
            "P8 platform software for the VA Financial Technology Service Program Management Office."
        ),
        tags=["procurement", "va", "it_infrastructure"],
    ),
    EvalCase(
        question="Which two consulting firms received contracts from the DFC for the Uzbekistan fintech Project Nomad, and what were the contract values?",
        reference=(
            "Boston Consulting Group received $350,000 USD for commercial due diligence, "
            "and KPMG LLP received $142,589 USD for financial due diligence, both from "
            "the U.S. International Development Finance Corporation (DFC) for "
            "Project Nomad — Uzbekistan Financial Technology."
        ),
        tags=["procurement", "dfc", "uzbekistan", "fintech"],
    ),
    EvalCase(
        question="What data subscriptions has Clarus Financial Technology provided to the Commodity Futures Trading Commission?",
        reference=(
            "Clarus Financial Technology has provided multiple data subscriptions to "
            "the CFTC including SDR View, SEF View, CCP View license renewals, "
            "Clarus Swaps Databases, and site licenses for financial data services."
        ),
        tags=["procurement", "cftc", "clarus", "derivatives"],
    ),
    EvalCase(
        question="What optional task areas did the SAIC T4NG VA contract include beyond core IT support?",
        reference=(
            "The SAIC T4NG contract included optional tasks for privacy services, "
            "cloud services (Cloud Center of Excellence), and one 45-day phase-out "
            "transition task. The total task order period shall not exceed 60 months."
        ),
        tags=["procurement", "va", "saic", "cloud"],
    ),

    # ── Hallucination traps (no relevant data in corpus) ──────────────────

    EvalCase(
        question="What is Apple Inc.'s current stock price and market capitalisation?",
        reference="",
        tags=["hallucination_trap"],
    ),
    EvalCase(
        question="Who is the current CEO of Google and when did they take over?",
        reference="",
        tags=["hallucination_trap"],
    ),
    EvalCase(
        question="Describe FinAgent's internal database schema and table structure in detail.",
        reference="",
        tags=["hallucination_trap"],
    ),
    EvalCase(
        question="Who won the most recent FIFA World Cup and in which country was it held?",
        reference="",
        tags=["hallucination_trap"],
    ),
    EvalCase(
        question="What is the current interest rate set by the US Federal Reserve?",
        reference="",
        tags=["hallucination_trap"],
    ),
]
