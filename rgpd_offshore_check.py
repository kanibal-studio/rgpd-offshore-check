#!/usr/bin/env python3
"""rgpd-offshore-check: a GDPR checklist for outsourced customer-service processing.

You describe an outsourcing set-up (call centre or customer service located
outside the EU/EEA) in a JSON answers file. The tool compares it with a built-in
checklist tied to the GDPR (Regulation (EU) 2016/679) and prints a gap report.

Design rules:

* Fail-closed. A missing, unknown or malformed answer is reported as
  ``to_verify`` and never as compliant. Only a clear ``true`` answer can satisfy
  a check.
* A "blocking gap" is a blocking check whose status is ``gap`` (declared absent)
  or ``to_verify`` (not demonstrated). Any blocking gap gives exit code 1.
* Standard library only, no network access, no file written. Python 3.9+.

This is a preparation checklist. It is not legal advice and not a certification.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

__version__ = "0.1.1"
TOOL_NAME = "rgpd-offshore-check"
SCHEMA_VERSION = 1
LANGS = ("en", "fr")

# Finding statuses.
OK = "ok"
GAP = "gap"
TO_VERIFY = "to_verify"
NOT_APPLICABLE = "not_applicable"
STATUSES = (OK, GAP, TO_VERIFY, NOT_APPLICABLE)

# Finding severities.
BLOCKING = "blocking"
RECOMMENDED = "recommended"
INFORMATIONAL = "informational"

EXIT_OK = 0
EXIT_BLOCKING = 1
EXIT_INPUT = 2

# Art. 46 transfer tools the answers file may declare under "safeguards".
ART46_TOOLS = (
    "scc",
    "bcr",
    "code_of_conduct",
    "certification",
    "ad_hoc_clauses",
    "public_authority_instrument",
)
# Declared but never accepted as a general transfer basis (Art. 49).
DEROGATION = "art49_derogation"


class InputError(ValueError):
    """The answers file cannot be read or is not a JSON object."""


# --------------------------------------------------------------------------
# Checklist definition
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckSpec:
    """One checklist item: identity, legal anchor, severity and texts."""

    id: str
    category: str
    articles: Tuple[str, ...]
    severity: str
    title: Dict[str, str]
    action: Dict[str, str]


CATEGORY_ORDER = ("transfer", "contract", "security", "breach", "rights", "evidence")

CATEGORY_TITLES = {
    "transfer": {
        "en": "1. Transfer basis (GDPR Chapter V, Art. 44-49)",
        "fr": "1. Base du transfert (RGPD, chapitre V, art. 44 à 49)",
    },
    "contract": {
        "en": "2. Processor contract (Art. 28)",
        "fr": "2. Contrat de sous-traitance (art. 28)",
    },
    "security": {
        "en": "3. Security of processing (Art. 32)",
        "fr": "3. Sécurité du traitement (art. 32)",
    },
    "breach": {
        "en": "4. Personal data breach (Art. 33)",
        "fr": "4. Violation de données à caractère personnel (art. 33)",
    },
    "rights": {
        "en": "5. Data-subject rights (Art. 12-22)",
        "fr": "5. Droits des personnes concernées (art. 12 à 22)",
    },
    "evidence": {
        "en": "6. Optional evidence",
        "fr": "6. Éléments de preuve facultatifs",
    },
}

# Art. 28(2)-(4): (answer key, article, English title, French title).
CONTRACT_CLAUSES = (
    (
        "subject_matter_and_duration",
        "Art. 28(3)",
        "Subject-matter and duration of the processing",
        "Objet et durée du traitement",
    ),
    (
        "nature_and_purpose",
        "Art. 28(3)",
        "Nature and purpose of the processing",
        "Nature et finalité du traitement",
    ),
    (
        "data_types_and_data_subject_categories",
        "Art. 28(3)",
        "Type of personal data and categories of data subjects",
        "Type de données à caractère personnel et catégories de personnes concernées",
    ),
    (
        "documented_instructions",
        "Art. 28(3)(a)",
        "Processing only on the controller's documented instructions, including "
        "as regards transfers to a third country",
        "Traitement uniquement sur instruction documentée du responsable du "
        "traitement, y compris pour les transferts vers un pays tiers",
    ),
    (
        "personnel_confidentiality",
        "Art. 28(3)(b)",
        "Confidentiality commitment of the persons authorised to process the data",
        "Engagement de confidentialité des personnes autorisées à traiter les données",
    ),
    (
        "security_measures_art32",
        "Art. 28(3)(c)",
        "All security measures required under Article 32",
        "Toutes les mesures de sécurité requises en vertu de l'article 32",
    ),
    (
        "subprocessor_prior_authorisation",
        "Art. 28(2), Art. 28(3)(d)",
        "Prior specific or general written authorisation for engaging sub-processors",
        "Autorisation écrite préalable, spécifique ou générale, pour le recours à "
        "des sous-traitants ultérieurs",
    ),
    (
        "subprocessor_flowdown",
        "Art. 28(4)",
        "Same data-protection obligations imposed on each sub-processor by contract",
        "Mêmes obligations de protection des données imposées par contrat à "
        "chaque sous-traitant ultérieur",
    ),
    (
        "data_subject_rights_assistance",
        "Art. 28(3)(e)",
        "Assistance to the controller with data-subject requests",
        "Aide au responsable du traitement pour les demandes des personnes concernées",
    ),
    (
        "art32_36_assistance",
        "Art. 28(3)(f)",
        "Assistance with the obligations under Articles 32 to 36",
        "Aide au respect des obligations des articles 32 à 36",
    ),
    (
        "deletion_or_return",
        "Art. 28(3)(g)",
        "Deletion or return of all personal data at the end of the services, "
        "at the controller's choice",
        "Suppression ou restitution de toutes les données à la fin des services, "
        "au choix du responsable du traitement",
    ),
    (
        "audit_and_inspection",
        "Art. 28(3)(h)",
        "Information to demonstrate compliance, and audits including inspections",
        "Informations permettant de démontrer le respect des obligations, et "
        "audits, y compris inspections",
    ),
)

# Art. 32 controls: (answer key, article, English title, French title).
SECURITY_CONTROLS = (
    (
        "encryption_in_transit",
        "Art. 32(1)(a)",
        "Encryption of personal data in transit (VPN / TLS)",
        "Chiffrement des données en transit (VPN / TLS)",
    ),
    (
        "pseudonymisation",
        "Art. 32(1)(a)",
        "Pseudonymisation where possible (for example masked identifiers on agent screens)",
        "Pseudonymisation lorsque c'est possible (par exemple identifiants masqués "
        "sur les écrans des agents)",
    ),
    (
        "role_based_access",
        "Art. 32(1)",
        "Role-based access with least privilege",
        "Accès par rôle selon le principe du moindre privilège",
    ),
    (
        "access_logging",
        "Art. 32(1)",
        "Access logging and audit trail",
        "Journalisation des accès et piste d'audit",
    ),
    (
        "physical_access_control",
        "Art. 32(1)",
        "Physical access control to the premises",
        "Contrôle d'accès physique aux locaux",
    ),
    (
        "personal_devices_policy",
        "Art. 32(1)",
        "Policy on personal phones and removable media",
        "Politique sur les téléphones personnels et les supports amovibles",
    ),
    (
        "clean_desk",
        "Art. 32(1)",
        "Clean-desk policy",
        "Politique de bureau propre",
    ),
)

CONTROL_KEYS = tuple(item[0] for item in SECURITY_CONTROLS)
CLAUSE_KEYS = tuple(item[0] for item in CONTRACT_CLAUSES)

_CLAUSE_ACTION = {
    "en": "Add or negotiate this clause in the processing agreement, then update "
    "the answers file.",
    "fr": "Ajoutez ou négociez cette clause dans le contrat de sous-traitance, "
    "puis mettez à jour le fichier de réponses.",
}
_CONTROL_ACTION = {
    "en": "Consider this control and agree it with the provider if it is appropriate "
    "to the risk, or document why it is not needed.",
    "fr": "Étudiez cette mesure et convenez-en avec le prestataire si elle est adaptée "
    "au risque, ou documentez pourquoi elle n'est pas nécessaire.",
}


def _clause_id(key: str) -> str:
    return "ART28-" + key.upper().replace("_", "-")


def _control_id(key: str) -> str:
    return "ART32-" + key.upper().replace("_", "-")


def _build_specs() -> List[CheckSpec]:
    specs: List[CheckSpec] = [
        CheckSpec(
            "TRANSFER-DESTINATION",
            "transfer",
            ("Art. 44", "Art. 45"),
            BLOCKING,
            {
                "en": "Destination country identified",
                "fr": "Pays de destination identifié",
            },
            {
                "en": "Name the destination country in destination_country. Adequacy "
                "and the transfer risk assessment are done per destination: run the "
                "tool once per country.",
                "fr": "Indiquez le pays de destination dans destination_country. "
                "L'adéquation et l'évaluation du risque du transfert se font par "
                "destination : lancez l'outil une fois par pays.",
            },
        ),
        CheckSpec(
            "TRANSFER-BASIS",
            "transfer",
            ("Art. 44", "Art. 45", "Art. 46"),
            BLOCKING,
            {
                "en": "Chapter V transfer basis: adequacy decision or appropriate safeguards",
                "fr": "Base de transfert du chapitre V : décision d'adéquation ou "
                "garanties appropriées",
            },
            {
                "en": "Check the European Commission's current list of adequacy "
                "decisions for the destination, including its territorial and "
                "sectoral scope (Art. 45(3)). If none covers the transfer, put an "
                "Art. 46 tool in place before any transfer (for example the Standard "
                "Contractual Clauses of Implementing Decision (EU) 2021/914, or BCR) "
                "and declare it in safeguards.",
                "fr": "Vérifiez dans la liste à jour de la Commission européenne les "
                "décisions d'adéquation applicables à la destination, y compris leur "
                "champ territorial et sectoriel (art. 45, par. 3). Si aucune ne couvre "
                "le transfert, mettez en place un outil de l'article 46 avant tout "
                "transfert (par exemple les clauses contractuelles types de la "
                "décision d'exécution (UE) 2021/914, ou des BCR) et déclarez-le dans "
                "safeguards.",
            },
        ),
        CheckSpec(
            "TRANSFER-TIA",
            "transfer",
            ("Art. 46", "CJEU C-311/18", "SCC (2021/914) Clause 14"),
            BLOCKING,
            {
                "en": "Transfer impact assessment documented when relying on an "
                "Art. 46 tool (Schrems II)",
                "fr": "Évaluation de l'impact du transfert documentée lorsqu'un outil "
                "de l'article 46 est utilisé (Schrems II)",
            },
            {
                "en": "Document an assessment of the destination's laws and practices, "
                "including access to data by public authorities, and of any "
                "supplementary measures, before relying on the transfer tool. The "
                "assessment is a legal and technical task for the controller with its "
                "DPO or counsel; this tool only records whether it exists.",
                "fr": "Documentez une évaluation de la législation et des pratiques du "
                "pays de destination, notamment l'accès aux données par les autorités "
                "publiques, et des mesures supplémentaires éventuelles, avant de vous "
                "appuyer sur l'outil de transfert. Cette évaluation relève du "
                "responsable du traitement avec son DPO ou son conseil ; l'outil "
                "enregistre seulement si elle existe.",
            },
        ),
        CheckSpec(
            "ART28-WRITTEN",
            "contract",
            ("Art. 28(3)", "Art. 28(9)"),
            BLOCKING,
            {
                "en": "Written processor contract in place (electronic form accepted)",
                "fr": "Contrat écrit de sous-traitance en place (la forme électronique "
                "est admise)",
            },
            {
                "en": "Put a written data processing agreement in place with the "
                "provider (and with its entity abroad, if different) before the "
                "processing starts.",
                "fr": "Mettez en place un contrat écrit de sous-traitance avec le "
                "prestataire (et avec son entité à l'étranger si elle est distincte) "
                "avant le début du traitement.",
            },
        ),
    ]
    for key, article, title_en, title_fr in CONTRACT_CLAUSES:
        specs.append(
            CheckSpec(
                _clause_id(key),
                "contract",
                (article,),
                BLOCKING,
                {"en": "Contract clause: " + title_en, "fr": "Clause du contrat : " + title_fr},
                _CLAUSE_ACTION,
            )
        )
    specs.append(
        CheckSpec(
            "ART32-BASELINE",
            "security",
            ("Art. 32(1)",),
            BLOCKING,
            {
                "en": "At least one Art. 32 security control in place",
                "fr": "Au moins une mesure de sécurité de l'article 32 en place",
            },
            {
                "en": "Agree a risk-based set of technical and organisational measures "
                "with the provider (Art. 32(1)). The controls listed below are common "
                "examples, not an exhaustive or sufficient list.",
                "fr": "Convenez avec le prestataire d'un ensemble de mesures techniques "
                "et organisationnelles adapté au risque (art. 32, par. 1). Les mesures "
                "ci-dessous sont des exemples courants, pas une liste exhaustive ni "
                "suffisante.",
            },
        )
    )
    for key, article, title_en, title_fr in SECURITY_CONTROLS:
        specs.append(
            CheckSpec(
                _control_id(key),
                "security",
                (article,),
                RECOMMENDED,
                {"en": "Recommended control: " + title_en, "fr": "Mesure recommandée : " + title_fr},
                _CONTROL_ACTION,
            )
        )
    specs.extend(
        [
            CheckSpec(
                "ART33-PROCESSOR-NOTIFICATION",
                "breach",
                ("Art. 33(2)", "Art. 33(1)", "Art. 28(3)(f)"),
                BLOCKING,
                {
                    "en": "Written procedure for the processor to notify the controller "
                    "of a personal data breach without undue delay",
                    "fr": "Procédure écrite imposant au sous-traitant de notifier toute "
                    "violation de données au responsable du traitement dans les "
                    "meilleurs délais",
                },
                {
                    "en": "Agree a written procedure with named contacts and channels, so "
                    "that the controller can meet its own duty to notify the supervisory "
                    "authority (Art. 33(1)) and, where required, the data subjects "
                    "(Art. 34).",
                    "fr": "Convenez d'une procédure écrite avec des contacts et canaux "
                    "nommés, afin que le responsable du traitement puisse respecter sa "
                    "propre obligation de notifier l'autorité de contrôle (art. 33, "
                    "par. 1) et, le cas échéant, les personnes concernées (art. 34).",
                },
            ),
            CheckSpec(
                "RIGHTS-PROCESS",
                "rights",
                ("Art. 12", "Art. 15-22", "Art. 28(3)(e)"),
                RECOMMENDED,
                {
                    "en": "Process and timelines agreed with the provider for handling "
                    "data-subject requests",
                    "fr": "Processus et délais convenus avec le prestataire pour traiter "
                    "les demandes des personnes concernées",
                },
                {
                    "en": "Agree how the provider forwards and supports requests (access, "
                    "rectification, erasure, objection and others) and the internal "
                    "timelines that let the controller answer within the deadlines of "
                    "Art. 12(3).",
                    "fr": "Convenez de la manière dont le prestataire transmet et appuie "
                    "les demandes (accès, rectification, effacement, opposition et "
                    "autres) et des délais internes qui permettent au responsable du "
                    "traitement de répondre dans les délais de l'art. 12, par. 3.",
                },
            ),
            CheckSpec(
                "EVIDENCE-ISO27001",
                "evidence",
                ("ISO/IEC 27001",),
                INFORMATIONAL,
                {
                    "en": "ISO/IEC 27001 certificate scope verified (informational)",
                    "fr": "Périmètre de la certification ISO/IEC 27001 vérifié "
                    "(à titre informatif)",
                },
                {
                    "en": "If the provider holds an ISO/IEC 27001 certificate, check that "
                    "its scope covers the site, services and processes concerned. It is "
                    "evidence about information-security management; it is not proof of "
                    "GDPR compliance.",
                    "fr": "Si le prestataire détient un certificat ISO/IEC 27001, vérifiez "
                    "que son périmètre couvre le site, les services et les processus "
                    "concernés. C'est un élément de preuve sur le management de la "
                    "sécurité de l'information, pas une preuve de conformité au RGPD.",
                },
            ),
        ]
    )
    return specs


SPECS: List[CheckSpec] = _build_specs()
SPEC_BY_ID: Dict[str, CheckSpec] = {spec.id: spec for spec in SPECS}
CHECK_IDS: Tuple[str, ...] = tuple(spec.id for spec in SPECS)

# Top-level answer keys. Keys starting with "_" are free comments and ignored.
KNOWN_TOP_KEYS = (
    "label",
    "destination_country",
    "adequacy_decision",
    "adequacy_scope_verified",
    "safeguards",
    "tia_documented",
    "art28_contract",
    "security_controls",
    "breach_notification_procedure",
    "data_subject_rights_process",
    "iso27001_scope_verified",
)

# --------------------------------------------------------------------------
# Texts
# --------------------------------------------------------------------------

MESSAGES: Dict[str, Dict[str, str]] = {
    "declared_in_place": {
        "en": "Declared in place in the answers file.",
        "fr": "Déclaré en place dans le fichier de réponses.",
    },
    "declared_absent": {
        "en": "Declared absent in the answers file.",
        "fr": "Déclaré absent dans le fichier de réponses.",
    },
    "answer_missing": {
        "en": "No answer given: unknown, so not demonstrated. Verify it and answer "
        "true or false.",
        "fr": "Aucune réponse : situation inconnue, donc non démontrée. À vérifier puis "
        "à renseigner par true ou false.",
    },
    "answer_malformed": {
        "en": "The answer is not a valid JSON value of the expected type (true/false, "
        "list or object): unknown, so not demonstrated.",
        "fr": "La réponse n'est pas une valeur JSON valide du type attendu (true/false, "
        "liste ou objet) : situation inconnue, donc non démontrée.",
    },
    "destination_declared": {
        "en": "Destination declared: {country}.",
        "fr": "Destination déclarée : {country}.",
    },
    "adequacy_verified": {
        "en": "An adequacy decision covering the destination is declared and its "
        "territorial and sectoral scope is marked as verified.",
        "fr": "Une décision d'adéquation couvrant la destination est déclarée et son "
        "champ territorial et sectoriel est indiqué comme vérifié.",
    },
    "safeguard_declared": {
        "en": "Art. 46 transfer tool declared: {tools}.",
        "fr": "Outil de transfert de l'article 46 déclaré : {tools}.",
    },
    "adequacy_scope_not_covering": {
        "en": "An adequacy decision is declared, but its scope is marked as not "
        "covering this transfer, and no Art. 46 tool is declared.",
        "fr": "Une décision d'adéquation est déclarée, mais son champ est indiqué comme "
        "ne couvrant pas ce transfert, et aucun outil de l'article 46 n'est déclaré.",
    },
    "adequacy_scope_unverified": {
        "en": "An adequacy decision is declared, but the check of its territorial and "
        "sectoral scope (Art. 45(3)) is not confirmed, and no Art. 46 tool is declared.",
        "fr": "Une décision d'adéquation est déclarée, mais la vérification de son champ "
        "territorial et sectoriel (art. 45, par. 3) n'est pas confirmée, et aucun "
        "outil de l'article 46 n'est déclaré.",
    },
    "no_adequacy_no_safeguard": {
        "en": "No adequacy decision and no Art. 46 safeguard declared: the transfer has "
        "no declared Chapter V basis.",
        "fr": "Ni décision d'adéquation ni garantie de l'article 46 déclarée : le "
        "transfert n'a aucune base déclarée au titre du chapitre V.",
    },
    "derogation_only": {
        "en": "Only an Art. 49 derogation is declared. Derogations are exceptions to be "
        "read restrictively (EDPB Guidelines 2/2018) and should not be assumed to "
        "cover systematic, recurring outsourcing.",
        "fr": "Seule une dérogation de l'article 49 est déclarée. Les dérogations sont "
        "des exceptions d'interprétation restrictive (lignes directrices CEPD "
        "2/2018) et ne doivent pas être présumées couvrir une externalisation "
        "systématique et récurrente.",
    },
    "basis_undetermined": {
        "en": "Neither a verified adequacy decision nor an Art. 46 transfer tool is "
        "established yet.",
        "fr": "Ni une décision d'adéquation vérifiée ni un outil de transfert de "
        "l'article 46 ne sont établis à ce stade.",
    },
    "tia_documented": {
        "en": "A transfer impact assessment is declared as documented.",
        "fr": "Une évaluation de l'impact du transfert est déclarée comme documentée.",
    },
    "scc_without_tia": {
        "en": "Standard Contractual Clauses are declared but no documented transfer "
        "impact assessment (CJEU C-311/18; SCC Clause 14).",
        "fr": "Des clauses contractuelles types sont déclarées mais aucune évaluation "
        "documentée de l'impact du transfert (CJUE C-311/18 ; CCT clause 14).",
    },
    "tia_other_tool_absent": {
        "en": "Another Art. 46 tool is declared without a documented transfer impact "
        "assessment. EDPB Recommendations 01/2020 expect the same case-by-case "
        "assessment for these tools.",
        "fr": "Un autre outil de l'article 46 est déclaré sans évaluation documentée de "
        "l'impact du transfert. Les recommandations CEPD 01/2020 attendent la même "
        "évaluation au cas par cas pour ces outils.",
    },
    "tia_tool_unknown": {
        "en": "The transfer tool is not established, so the need for a transfer impact "
        "assessment cannot be excluded.",
        "fr": "L'outil de transfert n'est pas établi : le besoin d'une évaluation de "
        "l'impact du transfert ne peut pas être exclu.",
    },
    "not_applicable_adequacy": {
        "en": "Not applicable: the transfer relies on a verified adequacy decision and "
        "no Art. 46 tool is declared.",
        "fr": "Sans objet : le transfert repose sur une décision d'adéquation vérifiée "
        "et aucun outil de l'article 46 n'est déclaré.",
    },
    "contract_absent_clause": {
        "en": "No written processor contract is declared, so this clause cannot be in "
        "place.",
        "fr": "Aucun contrat écrit de sous-traitance n'est déclaré : cette clause ne "
        "peut pas être en place.",
    },
    "security_controls_declared": {
        "en": "{count} of {total} listed controls are declared in place. Declared "
        "controls are not verified, and the list is not exhaustive.",
        "fr": "{count} mesure(s) sur {total} listées sont déclarées en place. Les "
        "mesures déclarées ne sont pas vérifiées et la liste n'est pas exhaustive.",
    },
    "security_none_declared": {
        "en": "Every listed control is declared absent: no Art. 32 measure at all.",
        "fr": "Toutes les mesures listées sont déclarées absentes : aucune mesure de "
        "l'article 32.",
    },
    "security_none_confirmed": {
        "en": "No listed control is confirmed in place (answers missing, unknown or "
        "malformed).",
        "fr": "Aucune mesure listée n'est confirmée en place (réponses manquantes, "
        "inconnues ou mal formées).",
    },
    "iso_scope_verified": {
        "en": "Declared verified. Informational only: not proof of GDPR compliance.",
        "fr": "Déclaré vérifié. À titre informatif seulement : pas une preuve de "
        "conformité au RGPD.",
    },
    "iso_scope_not_verified": {
        "en": "Declared not verified (or no certificate).",
        "fr": "Déclaré non vérifié (ou pas de certificat).",
    },
    "warn_unknown_key": {
        "en": "Unrecognised key {key} under {path} was ignored; check for a typo.",
        "fr": "La clé non reconnue {key} sous {path} a été ignorée ; vérifiez une "
        "éventuelle faute de frappe.",
    },
    "warn_unknown_safeguard": {
        "en": "Unrecognised safeguards value {value} was ignored. Recognised values: "
        "{known}.",
        "fr": "La valeur de safeguards {value} n'est pas reconnue et a été ignorée. "
        "Valeurs reconnues : {known}.",
    },
    "warn_invalid_label": {
        "en": "label must be a string; it was ignored.",
        "fr": "label doit être une chaîne de caractères ; il a été ignoré.",
    },
}

UI: Dict[str, Dict[str, str]] = {
    "title": {
        "en": "# GDPR offshore outsourcing checklist: gap report",
        "fr": "# Checklist RGPD de l'externalisation hors UE : rapport d'écarts",
    },
    "disclaimer": {
        "en": "This report is a preparation checklist built from the answers you "
        "declared. It is not legal advice, not a certification and not a finding of "
        "compliance. Use it to prepare discussions with your Data Protection Officer "
        "(DPO) or legal counsel.",
        "fr": "Ce rapport est une checklist de préparation établie à partir des réponses "
        "que vous avez déclarées. Ce n'est ni un avis juridique, ni une certification, "
        "ni un constat de conformité. Utilisez-le pour préparer les échanges avec "
        "votre délégué à la protection des données (DPO) ou votre conseil juridique.",
    },
    "colon": {"en": ":", "fr": " :"},
    "setup": {"en": "Set-up", "fr": "Configuration"},
    "destination": {"en": "Destination", "fr": "Destination"},
    "not_declared": {"en": "(not declared)", "fr": "(non déclarée)"},
    "summary": {"en": "## Summary", "fr": "## Synthèse"},
    "result": {"en": "Result", "fr": "Résultat"},
    "result_blocking": {
        "en": "BLOCKING GAP(S) FOUND",
        "fr": "ÉCART(S) BLOQUANT(S) TROUVÉ(S)",
    },
    "result_none": {
        "en": "no blocking gap in the declared answers (this is not a finding of "
        "compliance)",
        "fr": "aucun écart bloquant dans les réponses déclarées (ce n'est pas un "
        "constat de conformité)",
    },
    "blocking_line": {
        "en": "Blocking: {gaps} declared gap(s), {unknown} answer(s) to verify",
        "fr": "Bloquants : {gaps} écart(s) déclaré(s), {unknown} réponse(s) à vérifier",
    },
    "recommended_line": {
        "en": "Recommended controls open: {n}",
        "fr": "Mesures recommandées ouvertes : {n}",
    },
    "informational_line": {
        "en": "Informational items open: {n}",
        "fr": "Éléments informatifs ouverts : {n}",
    },
    "counts_line": {"en": "Counts", "fr": "Décompte"},
    "blocking_items": {"en": "### Blocking items", "fr": "### Éléments bloquants"},
    "details": {"en": "## Checklist detail", "fr": "## Détail de la checklist"},
    "warnings": {"en": "## Warnings", "fr": "## Avertissements"},
    "notes": {"en": "## Notes", "fr": "## Notes"},
    "sources": {"en": "## Official sources", "fr": "## Sources officielles"},
    "why": {"en": "Status", "fr": "Constat"},
    "todo": {"en": "To do", "fr": "À faire"},
}

STATUS_LABELS = {
    OK: {"en": "OK", "fr": "OK"},
    GAP: {"en": "GAP", "fr": "ÉCART"},
    TO_VERIFY: {"en": "TO VERIFY", "fr": "À VÉRIFIER"},
    NOT_APPLICABLE: {"en": "N/A", "fr": "N/A"},
}

SEVERITY_LABELS = {
    BLOCKING: {"en": "blocking", "fr": "bloquant"},
    RECOMMENDED: {"en": "recommended", "fr": "recommandé"},
    INFORMATIONAL: {"en": "informational", "fr": "informatif"},
}

NOTES: Tuple[Dict[str, str], ...] = (
    {
        "en": "The controller remains accountable for GDPR compliance wherever the data "
        "is processed and whatever is delegated to a provider (Art. 5(2), Art. 24). "
        "Outsourcing abroad does not transfer that accountability.",
        "fr": "Le responsable du traitement reste responsable du respect du RGPD où que "
        "les données soient traitées et quoi qu'il délègue à un prestataire (art. 5, "
        "par. 2, art. 24). L'externalisation à l'étranger ne transfère pas cette "
        "responsabilité.",
    },
    {
        "en": "This report only reflects declared answers. It does not inspect contracts, "
        "systems or sites, does not assess the law of the destination country, and "
        "does not replace the transfer impact assessment, a data protection impact "
        "assessment where required (Art. 35), or the advice of your DPO or legal "
        "counsel.",
        "fr": "Ce rapport ne reflète que les réponses déclarées. Il n'inspecte ni les "
        "contrats, ni les systèmes, ni les sites, n'évalue pas le droit du pays de "
        "destination et ne remplace ni l'évaluation de l'impact du transfert, ni une "
        "analyse d'impact relative à la protection des données lorsqu'elle est "
        "requise (art. 35), ni l'avis de votre DPO ou de votre conseil juridique.",
    },
    {
        "en": "Adequacy decisions can be amended, suspended or repealed. Check the "
        "official texts and the European Commission's current list of adequacy "
        "decisions before relying on this checklist.",
        "fr": "Les décisions d'adéquation peuvent être modifiées, suspendues ou "
        "abrogées. Vérifiez les textes officiels et la liste à jour des décisions "
        "d'adéquation de la Commission européenne avant de vous appuyer sur cette "
        "checklist.",
    },
)

SOURCES: Tuple[Tuple[str, str], ...] = (
    (
        "GDPR, Regulation (EU) 2016/679",
        "https://eur-lex.europa.eu/eli/reg/2016/679/oj",
    ),
    (
        "Standard Contractual Clauses, Commission Implementing Decision (EU) 2021/914",
        "https://eur-lex.europa.eu/eli/dec_impl/2021/914/oj",
    ),
    (
        "CJEU, Case C-311/18 (Schrems II)",
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:62018CJ0311",
    ),
)


def _msg(reason: str, lang: str, **fmt: Any) -> str:
    return MESSAGES[reason][lang].format(**fmt)


# --------------------------------------------------------------------------
# Result model
# --------------------------------------------------------------------------


@dataclass
class Finding:
    """The outcome of one checklist item."""

    id: str
    category: str
    articles: List[str]
    severity: str
    status: str
    reason: str
    title: str
    detail: str
    action: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "articles": list(self.articles),
            "severity": self.severity,
            "status": self.status,
            "reason": self.reason,
            "title": self.title,
            "detail": self.detail,
            "action": self.action,
        }


@dataclass
class Report:
    """Evaluation result. Ordering of every list is deterministic."""

    lang: str
    label: Optional[str]
    destination_country: Optional[str]
    findings: List[Finding]
    warnings: List[Dict[str, str]]

    @property
    def summary(self) -> Dict[str, Any]:
        counts = {status: 0 for status in STATUSES}
        blocking_gaps: List[str] = []
        blocking_to_verify: List[str] = []
        recommended_open: List[str] = []
        informational_open: List[str] = []
        for finding in self.findings:
            counts[finding.status] += 1
            if finding.status not in (GAP, TO_VERIFY):
                continue
            if finding.severity == BLOCKING:
                target = blocking_gaps if finding.status == GAP else blocking_to_verify
                target.append(finding.id)
            elif finding.severity == RECOMMENDED:
                recommended_open.append(finding.id)
            else:
                informational_open.append(finding.id)
        blocking_total = len(blocking_gaps) + len(blocking_to_verify)
        return {
            "result": "blocking_gap" if blocking_total else "no_blocking_gap",
            "exit_code": EXIT_BLOCKING if blocking_total else EXIT_OK,
            "blocking_total": blocking_total,
            "blocking_gaps": blocking_gaps,
            "blocking_to_verify": blocking_to_verify,
            "recommended_open": recommended_open,
            "informational_open": informational_open,
            "counts": counts,
        }

    @property
    def exit_code(self) -> int:
        return int(self.summary["exit_code"])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": TOOL_NAME,
            "version": __version__,
            "schema_version": SCHEMA_VERSION,
            "lang": self.lang,
            "disclaimer": UI["disclaimer"][self.lang],
            "input": {
                "label": self.label,
                "destination_country": self.destination_country,
            },
            "summary": self.summary,
            "findings": [finding.to_dict() for finding in self.findings],
            "warnings": [dict(warning) for warning in self.warnings],
            "notes": [note[self.lang] for note in NOTES],
            "sources": [{"title": title, "url": url} for title, url in SOURCES],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"

    def to_markdown(self) -> str:
        return _render_markdown(self)


# --------------------------------------------------------------------------
# Answer parsing helpers (strict: only JSON true/false counts as a boolean)
# --------------------------------------------------------------------------

_MISSING = "missing"
_MALFORMED = "malformed"


def _clean(text: str, limit: int = 120) -> str:
    """Make echoed user text safe for a terminal: no control characters."""
    cleaned = "".join(ch if ch.isprintable() else " " for ch in text).strip()
    return cleaned[:limit]


def _quote(text: str) -> str:
    return json.dumps(_clean(text, 80), ensure_ascii=False)


def _section(container: Any, key: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Return a nested object and a problem code (None when usable)."""
    if not isinstance(container, dict):
        return None, _MISSING
    value = container.get(key)
    if value is None:
        return None, _MISSING
    if not isinstance(value, dict):
        return None, _MALFORMED
    return value, None


def _tri(
    container: Optional[Dict[str, Any]], key: str, inherited: Optional[str] = None
) -> Tuple[Optional[bool], Optional[str]]:
    """Read a tri-state boolean: (True|False, None) or (None, problem)."""
    if container is None:
        return None, inherited or _MISSING
    value = container.get(key)
    if value is None:
        return None, _MISSING
    if isinstance(value, bool):
        return value, None
    return None, _MALFORMED


def _problem_reason(problem: Optional[str]) -> str:
    return "answer_malformed" if problem == _MALFORMED else "answer_missing"


class _Collector:
    """Builds findings and warnings in checklist order for one language."""

    def __init__(self, lang: str) -> None:
        self.lang = lang
        self.findings: List[Finding] = []
        self.warnings: List[Dict[str, str]] = []

    def add(
        self,
        check_id: str,
        status: str,
        reason: str,
        severity: Optional[str] = None,
        **fmt: Any,
    ) -> None:
        spec = SPEC_BY_ID[check_id]
        action = "" if status in (OK, NOT_APPLICABLE) else spec.action[self.lang]
        self.findings.append(
            Finding(
                id=spec.id,
                category=spec.category,
                articles=list(spec.articles),
                severity=severity or spec.severity,
                status=status,
                reason=reason,
                title=spec.title[self.lang],
                detail=_msg(reason, self.lang, **fmt),
                action=action,
            )
        )

    def add_bool(
        self,
        check_id: str,
        state: Optional[bool],
        problem: Optional[str],
        ok_reason: str = "declared_in_place",
        gap_reason: str = "declared_absent",
    ) -> None:
        if state is True:
            self.add(check_id, OK, ok_reason)
        elif state is False:
            self.add(check_id, GAP, gap_reason)
        else:
            self.add(check_id, TO_VERIFY, _problem_reason(problem))

    def warn(self, code: str, path: str, **fmt: Any) -> None:
        self.warnings.append(
            {
                "code": code,
                "path": path,
                "message": _msg("warn_" + code, self.lang, path=path, **fmt),
            }
        )


def _warn_unknown_keys(
    collector: _Collector, container: Optional[Dict[str, Any]], known: Sequence[str], path: str
) -> None:
    if container is None:
        return
    for key in sorted(str(k) for k in container):
        if key.startswith("_") or key in known:
            continue
        collector.warn("unknown_key", path, key=_quote(key))


def _parse_safeguards(
    collector: _Collector, answers: Dict[str, Any]
) -> Tuple[List[str], bool, Optional[str]]:
    """Return (recognised Art. 46 tools, Art. 49 flag, problem code)."""
    value = answers.get("safeguards")
    if value is None:
        return [], False, _MISSING
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return [], False, _MALFORMED
    tools: List[str] = []
    derogation = False
    for item in value:
        normalised = item.strip().lower()
        if normalised in ART46_TOOLS:
            if normalised not in tools:
                tools.append(normalised)
        elif normalised == DEROGATION:
            derogation = True
        else:
            collector.warn(
                "unknown_safeguard",
                "$.safeguards",
                value=_quote(item),
                known=", ".join(ART46_TOOLS + (DEROGATION,)),
            )
    return sorted(tools), derogation, None


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------


def _eval_transfer(collector: _Collector, answers: Dict[str, Any]) -> None:
    country = answers.get("destination_country")
    if isinstance(country, str) and _clean(country):
        collector.add("TRANSFER-DESTINATION", OK, "destination_declared", country=_clean(country))
    else:
        problem = _MISSING if country is None else _MALFORMED
        collector.add("TRANSFER-DESTINATION", TO_VERIFY, _problem_reason(problem))

    adequacy, adequacy_problem = _tri(answers, "adequacy_decision")
    scope, _scope_problem = _tri(answers, "adequacy_scope_verified")
    tools, derogation, safeguards_problem = _parse_safeguards(collector, answers)
    adequacy_ok = adequacy is True and scope is True

    if adequacy_ok:
        collector.add("TRANSFER-BASIS", OK, "adequacy_verified")
    elif tools:
        collector.add("TRANSFER-BASIS", OK, "safeguard_declared", tools=", ".join(tools))
    elif adequacy is True and scope is False:
        collector.add("TRANSFER-BASIS", GAP, "adequacy_scope_not_covering")
    elif adequacy is True:
        collector.add("TRANSFER-BASIS", TO_VERIFY, "adequacy_scope_unverified")
    elif adequacy is False and safeguards_problem is None:
        reason = "derogation_only" if derogation else "no_adequacy_no_safeguard"
        collector.add("TRANSFER-BASIS", GAP, reason)
    elif adequacy_problem == _MALFORMED or safeguards_problem == _MALFORMED:
        collector.add("TRANSFER-BASIS", TO_VERIFY, "answer_malformed")
    else:
        collector.add("TRANSFER-BASIS", TO_VERIFY, "basis_undetermined")

    tia, tia_problem = _tri(answers, "tia_documented")
    if "scc" in tools:
        severity = BLOCKING
    elif tools:
        severity = RECOMMENDED
    else:
        severity = BLOCKING
    if tools:
        if tia is True:
            collector.add("TRANSFER-TIA", OK, "tia_documented", severity)
        elif tia is False:
            reason = "scc_without_tia" if "scc" in tools else "tia_other_tool_absent"
            collector.add("TRANSFER-TIA", GAP, reason, severity)
        else:
            collector.add("TRANSFER-TIA", TO_VERIFY, _problem_reason(tia_problem), severity)
    elif adequacy_ok:
        collector.add("TRANSFER-TIA", NOT_APPLICABLE, "not_applicable_adequacy")
    else:
        collector.add("TRANSFER-TIA", TO_VERIFY, "tia_tool_unknown")


def _eval_contract(collector: _Collector, answers: Dict[str, Any]) -> None:
    contract, contract_problem = _section(answers, "art28_contract")
    in_writing, writing_problem = _tri(contract, "in_writing", contract_problem)
    collector.add_bool("ART28-WRITTEN", in_writing, writing_problem)

    clauses, clauses_problem = _section(contract, "clauses")
    if contract is None:
        clauses_problem = contract_problem
    _warn_unknown_keys(collector, contract, ("in_writing", "clauses"), "$.art28_contract")
    _warn_unknown_keys(collector, clauses, CLAUSE_KEYS, "$.art28_contract.clauses")
    for key, _article, _title_en, _title_fr in CONTRACT_CLAUSES:
        check_id = _clause_id(key)
        if in_writing is False:
            collector.add(check_id, GAP, "contract_absent_clause")
            continue
        state, problem = _tri(clauses, key, clauses_problem)
        collector.add_bool(check_id, state, problem)


def _eval_security(collector: _Collector, answers: Dict[str, Any]) -> None:
    controls, controls_problem = _section(answers, "security_controls")
    _warn_unknown_keys(collector, controls, CONTROL_KEYS, "$.security_controls")
    states = {key: _tri(controls, key, controls_problem) for key in CONTROL_KEYS}
    declared = sum(1 for state, _problem in states.values() if state is True)
    absent = sum(1 for state, _problem in states.values() if state is False)

    if declared:
        collector.add(
            "ART32-BASELINE",
            OK,
            "security_controls_declared",
            count=declared,
            total=len(CONTROL_KEYS),
        )
    elif absent == len(CONTROL_KEYS):
        collector.add("ART32-BASELINE", GAP, "security_none_declared")
    else:
        collector.add("ART32-BASELINE", TO_VERIFY, "security_none_confirmed")

    for key in CONTROL_KEYS:
        state, problem = states[key]
        collector.add_bool(_control_id(key), state, problem)


def evaluate(answers: Dict[str, Any], lang: str = "en") -> Report:
    """Compare an answers object with the checklist and return a Report.

    ``answers`` must be a dict (use :func:`load_answers` for files). Any value
    that is not a clear JSON ``true`` is never treated as compliant.
    """
    if lang not in LANGS:
        raise ValueError("lang must be one of: " + ", ".join(LANGS))
    if not isinstance(answers, dict):
        raise InputError("answers must be a JSON object")

    collector = _Collector(lang)
    _warn_unknown_keys(collector, answers, KNOWN_TOP_KEYS, "$")

    label: Optional[str] = None
    raw_label = answers.get("label")
    if isinstance(raw_label, str):
        label = _clean(raw_label) or None
    elif raw_label is not None:
        collector.warn("invalid_label", "$.label")
    raw_country = answers.get("destination_country")
    country = _clean(raw_country) if isinstance(raw_country, str) else ""

    _eval_transfer(collector, answers)
    _eval_contract(collector, answers)
    _eval_security(collector, answers)

    state, problem = _tri(answers, "breach_notification_procedure")
    collector.add_bool("ART33-PROCESSOR-NOTIFICATION", state, problem)
    state, problem = _tri(answers, "data_subject_rights_process")
    collector.add_bool("RIGHTS-PROCESS", state, problem)
    state, problem = _tri(answers, "iso27001_scope_verified")
    collector.add_bool(
        "EVIDENCE-ISO27001", state, problem, "iso_scope_verified", "iso_scope_not_verified"
    )

    ordered = {finding.id: finding for finding in collector.findings}
    findings = [ordered[check_id] for check_id in CHECK_IDS]
    warnings = sorted(collector.warnings, key=lambda w: (w["path"], w["code"], w["message"]))
    return Report(lang, label, country or None, findings, warnings)


# --------------------------------------------------------------------------
# Input and rendering
# --------------------------------------------------------------------------


def _reject_duplicates(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputError("duplicate key in JSON object: " + _quote(key))
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise InputError("non-standard JSON constant is not allowed: " + name)


def load_answers(path: str) -> Dict[str, Any]:
    """Read an answers file. Raises InputError for anything but a JSON object."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        raise InputError("cannot read answers file: " + (exc.strerror or str(exc))) from exc
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputError("answers file is not valid UTF-8") from exc
    try:
        data = json.loads(
            text, object_pairs_hook=_reject_duplicates, parse_constant=_reject_constant
        )
    except InputError:
        raise
    except (ValueError, RecursionError) as exc:
        raise InputError("answers file is not valid JSON: " + str(exc)) from exc
    if not isinstance(data, dict):
        raise InputError("answers file must contain a JSON object at the top level")
    return data


def _render_finding(finding: Finding, lang: str) -> List[str]:
    status = STATUS_LABELS[finding.status][lang]
    severity = SEVERITY_LABELS[finding.severity][lang]
    articles = ", ".join(finding.articles)
    lines = [
        "- **[{}]** `{}` ({}) {} _({})_".format(
            status, finding.id, severity, finding.title, articles
        ),
        "  - {}{} {}".format(UI["why"][lang], UI["colon"][lang], finding.detail),
    ]
    if finding.action:
        lines.append("  - {}{} {}".format(UI["todo"][lang], UI["colon"][lang], finding.action))
    return lines


def _render_markdown(report: Report) -> str:
    lang = report.lang
    summary = report.summary
    counts = summary["counts"]
    lines: List[str] = [UI["title"][lang], "", "> " + UI["disclaimer"][lang], ""]
    colon = UI["colon"][lang]
    lines.append(
        "**{}{}** {} | **{}{}** {}".format(
            UI["setup"][lang],
            colon,
            report.label or UI["not_declared"][lang],
            UI["destination"][lang],
            colon,
            report.destination_country or UI["not_declared"][lang],
        )
    )
    lines.extend(["", UI["summary"][lang], ""])
    verdict = UI["result_blocking"][lang] if summary["blocking_total"] else UI["result_none"][lang]
    lines.append("- {}{} {}".format(UI["result"][lang], colon, verdict))
    lines.append(
        "- "
        + UI["blocking_line"][lang].format(
            gaps=len(summary["blocking_gaps"]), unknown=len(summary["blocking_to_verify"])
        )
    )
    lines.append("- " + UI["recommended_line"][lang].format(n=len(summary["recommended_open"])))
    lines.append("- " + UI["informational_line"][lang].format(n=len(summary["informational_open"])))
    lines.append(
        "- {}{} {}".format(
            UI["counts_line"][lang],
            colon,
            " | ".join(
                "{} {}".format(STATUS_LABELS[status][lang], counts[status]) for status in STATUSES
            ),
        )
    )

    if summary["blocking_total"]:
        lines.extend(["", UI["blocking_items"][lang], ""])
        blocking_ids = set(summary["blocking_gaps"]) | set(summary["blocking_to_verify"])
        for finding in report.findings:
            if finding.id in blocking_ids:
                lines.append(
                    "- [{}] `{}` {}".format(
                        STATUS_LABELS[finding.status][lang], finding.id, finding.title
                    )
                )

    lines.extend(["", UI["details"][lang]])
    for category in CATEGORY_ORDER:
        lines.extend(["", "### " + CATEGORY_TITLES[category][lang], ""])
        for finding in report.findings:
            if finding.category == category:
                lines.extend(_render_finding(finding, lang))

    if report.warnings:
        lines.extend(["", UI["warnings"][lang], ""])
        lines.extend("- " + warning["message"] for warning in report.warnings)

    lines.extend(["", UI["notes"][lang], ""])
    lines.extend("- " + note[lang] for note in NOTES)
    lines.extend(["", UI["sources"][lang], ""])
    lines.extend("- {}: {}".format(title, url) for title, url in SOURCES)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rgpd_offshore_check.py",
        description=(
            "GDPR checklist for customer-service processing outsourced outside the EU. "
            "Reads a JSON answers file and prints a gap report. Not legal advice, "
            "not a certification."
        ),
        epilog="Exit codes: 0 no blocking gap, 1 at least one blocking gap, 2 invalid input.",
    )
    parser.add_argument("answers", help="path to the JSON answers file")
    parser.add_argument(
        "--json", action="store_true", dest="as_json", help="print machine-readable JSON"
    )
    parser.add_argument(
        "--lang", choices=LANGS, default="en", help="report language (default: en)"
    )
    parser.add_argument("--version", action="version", version=TOOL_NAME + " " + __version__)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the CLI and return the exit code (0, 1 or 2)."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse: 2 on usage error, 0 for --help/--version
        return exc.code if isinstance(exc.code, int) else EXIT_INPUT
    try:
        answers = load_answers(args.answers)
    except InputError as exc:
        print("error: " + str(exc), file=sys.stderr)
        return EXIT_INPUT
    report = evaluate(answers, args.lang)
    sys.stdout.write(report.to_json() if args.as_json else report.to_markdown())
    return report.exit_code


def _force_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


if __name__ == "__main__":
    _force_utf8_streams()
    sys.exit(main())
