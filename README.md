# rgpd-offshore-check

A small GDPR checklist for outsourcing customer-service or call-centre processing outside the EU/EEA, for example to Morocco, Tunisia or Madagascar. You describe your set-up in a JSON answers file; the tool compares it with a built-in checklist and prints a gap report. Python 3.9+, standard library only, no network access, no file written.

**Not legal advice. Not a certification.** This is a checklist to prepare discussions with your Data Protection Officer (DPO) or legal counsel. A report without blocking gap is not a finding of compliance: it only means that your declared answers show no blocking gap. The controller remains accountable for GDPR compliance wherever the data is processed (Art. 5(2), Art. 24).

English | [Français](#français)

## What it does

The checklist is tied to the official texts and cites article numbers:

| Area | Source | What is checked |
|---|---|---|
| Destination | Art. 44, 45 | The destination country is named (adequacy and risk assessment are per destination). |
| Transfer basis | Chapter V, Art. 44-49 | An adequacy decision whose scope was verified, or an Art. 46 safeguard (Standard Contractual Clauses of Decision (EU) 2021/914, BCR, other Art. 46 tools). No adequacy and no safeguard is blocking. An Art. 49 derogation alone is not accepted as a basis. |
| Transfer impact assessment | CJEU C-311/18 (Schrems II), SCC Clause 14 | SCC without a documented assessment is blocking. For other Art. 46 tools it is a recommended item. |
| Processor contract | Art. 28(2)-(4), (9) | A written contract, and twelve clauses: subject-matter and duration, nature and purpose, data types and data-subject categories, documented instructions, personnel confidentiality, Art. 32 measures, prior authorisation of sub-processors, flow-down to sub-processors, assistance with data-subject rights, assistance with Art. 32-36, deletion or return, audit and inspection. Each missing clause is blocking. |
| Security | Art. 32 | Seven common controls (encryption in transit, pseudonymisation, role-based access, access logging, physical access control, policy on personal phones and removable media, clean desk). Individually recommended, not blocking; declaring none at all is blocking. The list is not exhaustive: Art. 32 requires measures appropriate to the risk. |
| Breach notification | Art. 33(2) | A written procedure for the processor to notify the controller without undue delay is blocking if absent. |
| Data-subject rights | Art. 12-22, Art. 28(3)(e) | A process and timelines agreed with the provider (recommended). |
| Optional evidence | ISO/IEC 27001 | Certificate scope verified. Informational only, never proof of GDPR compliance. |

The tool is **fail-closed**: only a clear JSON `true` satisfies a check. A missing, `null`, unknown or malformed answer (for example the string `"true"`, or a number) is reported as `to_verify`, never as compliant. A **blocking gap** is a blocking item that is either declared absent (`gap`) or not demonstrated (`to_verify`).

## Quick start

```sh
python3 rgpd_offshore_check.py examples/answers.json            # Markdown report (English)
python3 rgpd_offshore_check.py examples/answers.json --lang fr  # Rapport en français
python3 rgpd_offshore_check.py examples/answers.json --json     # machine-readable output
python3 rgpd_offshore_check.py examples/answers_minimal.json    # almost nothing answered
python3 -m unittest discover -s tests -v                        # run the tests
```

Run it once per destination country. Options: `--json`, `--lang en|fr` (default `en`), `--help`, `--version`.

## Input format

A JSON object. Every key is optional; every missing key is reported as `to_verify`. Keys starting with `_` are free comments and ignored. Unrecognised keys are ignored with a warning in the report (a typo never passes silently). Duplicate keys, `NaN` and a non-object file are rejected.

| Key | Type | Meaning |
|---|---|---|
| `label` | string | Free name for the set-up, echoed in the report. |
| `destination_country` | string | Destination of the transfer. |
| `adequacy_decision` | boolean | An EU adequacy decision exists for the destination. Check the European Commission's current list: the tool ships no list, so it cannot go stale. |
| `adequacy_scope_verified` | boolean | You checked that the decision's territorial and sectoral scope (Art. 45(3)) covers your transfer. |
| `safeguards` | list of strings | Art. 46 tools in place: `scc`, `bcr`, `code_of_conduct`, `certification`, `ad_hoc_clauses`, `public_authority_instrument`. `art49_derogation` is recognised but never accepted as a general basis. |
| `tia_documented` | boolean | A transfer impact assessment is documented. |
| `art28_contract.in_writing` | boolean | A written processor contract exists. |
| `art28_contract.clauses.<name>` | boolean | The clause is in the contract. Names: `subject_matter_and_duration`, `nature_and_purpose`, `data_types_and_data_subject_categories`, `documented_instructions`, `personnel_confidentiality`, `security_measures_art32`, `subprocessor_prior_authorisation`, `subprocessor_flowdown`, `data_subject_rights_assistance`, `art32_36_assistance`, `deletion_or_return`, `audit_and_inspection`. |
| `security_controls.<name>` | boolean | Names: `encryption_in_transit`, `pseudonymisation`, `role_based_access`, `access_logging`, `physical_access_control`, `personal_devices_policy`, `clean_desk`. |
| `breach_notification_procedure` | boolean | Written procedure for the processor to notify the controller. |
| `data_subject_rights_process` | boolean | Process and timelines agreed with the provider. |
| `iso27001_scope_verified` | boolean | Certificate scope verified (informational). |

A short fictitious example (see [examples/answers.json](examples/answers.json) for the complete one):

```json
{
  "label": "Fictitious retailer, support team in Morocco",
  "destination_country": "Morocco",
  "adequacy_decision": false,
  "safeguards": ["scc"],
  "tia_documented": false,
  "art28_contract": {
    "in_writing": true,
    "clauses": { "subprocessor_prior_authorisation": false }
  },
  "breach_notification_procedure": true
}
```

## Output example

`python3 rgpd_offshore_check.py examples/answers.json` (excerpt):

```text
## Summary

- Result: BLOCKING GAP(S) FOUND
- Blocking: 2 declared gap(s), 0 answer(s) to verify
- Recommended controls open: 2
- Informational items open: 1
- Counts: OK 22 | GAP 5 | TO VERIFY 0 | N/A 0

### Blocking items

- [GAP] `TRANSFER-TIA` Transfer impact assessment documented when relying on an Art. 46 tool (Schrems II)
- [GAP] `ART28-SUBPROCESSOR-PRIOR-AUTHORISATION` Contract clause: Prior specific or general written authorisation for engaging sub-processors
```

With `--json` the output has a stable schema (`schema_version: 1`): `tool`, `version`, `schema_version`, `lang`, `disclaimer`, `input`, `summary` (`result`, `exit_code`, `blocking_total`, `blocking_gaps`, `blocking_to_verify`, `recommended_open`, `informational_open`, `counts`), `findings` (each with `id`, `category`, `articles`, `severity`, `status`, `reason`, `title`, `detail`, `action`), `warnings`, `notes`, `sources`. Finding order is fixed and identical between runs. `status` is one of `ok`, `gap`, `to_verify`, `not_applicable`; `reason` is a language-independent code.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | No blocking gap in the declared answers (not a finding of compliance). |
| 1 | At least one blocking gap: a blocking item declared absent or not demonstrated. |
| 2 | Invalid input or command-line usage: unreadable file, invalid JSON, duplicate key, top level not an object, unknown option. Nothing is printed on stdout; the error goes to stderr (in English). |

## Limits

- The tool only reads what you declare. It does not inspect contracts, systems or sites, and a `true` is not verified.
- It does not assess the law or surveillance practices of the destination country. The transfer impact assessment must be done by people; the tool only records whether one is documented.
- It ships no list of adequacy decisions, on purpose: lists change. Check the Commission's current list and the scope of the decision.
- It covers outsourcing abroad only. It does not cover a data protection impact assessment (Art. 35), records of processing (Art. 30), information notices (Art. 13-14), joint controllership (Art. 26), telephone or e-mail marketing rules, call recording, employment or sector-specific rules, or the national law of the destination country.
- The Art. 28 checklist follows the text of Art. 28(2)-(4) and (9). Your supervisory authority or counsel may expect more.
- A recommended or informational item never changes the exit code. ISO/IEC 27001 is evidence about information-security management, not proof of GDPR compliance.
- Statements about EDPB documents (Guidelines 2/2018 on Art. 49, Recommendations 01/2020 on supplementary measures) are pointers; read the originals.

## Official sources

- GDPR, Regulation (EU) 2016/679: https://eur-lex.europa.eu/eli/reg/2016/679/oj
- Standard Contractual Clauses, Commission Implementing Decision (EU) 2021/914: https://eur-lex.europa.eu/eli/dec_impl/2021/914/oj
- CJEU, Case C-311/18 (Schrems II): https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:62018CJ0311 (also on https://curia.europa.eu/)

Related article (English): https://altavista360.com/en/blog/gdpr-offshore-outsourcing-guide/

---

# Français

## Avertissement

**Ceci n'est pas un avis juridique ni une certification.** C'est une checklist pour préparer les échanges avec votre délégué à la protection des données (DPO) ou votre conseil juridique. Un rapport sans écart bloquant n'est pas un constat de conformité : il signifie seulement que vos réponses déclarées ne montrent aucun écart bloquant. Le responsable du traitement reste responsable du respect du RGPD où que les données soient traitées (art. 5, par. 2, et art. 24).

## Ce que fait l'outil

Petite checklist RGPD pour l'externalisation d'un service client ou d'un centre d'appels hors UE/EEE, par exemple au Maroc, en Tunisie ou à Madagascar. Vous décrivez votre montage dans un fichier de réponses JSON ; l'outil le compare à une checklist intégrée et affiche un rapport d'écarts. Python 3.9+, bibliothèque standard uniquement, aucun accès réseau, aucun fichier écrit.

La checklist s'appuie sur les textes officiels et cite les articles :

| Domaine | Source | Ce qui est vérifié |
|---|---|---|
| Destination | art. 44, 45 | Le pays de destination est nommé (l'adéquation et l'évaluation du risque se font par destination). |
| Base du transfert | chapitre V, art. 44 à 49 | Une décision d'adéquation dont le champ a été vérifié, ou une garantie de l'article 46 (clauses contractuelles types de la décision (UE) 2021/914, BCR, autres outils de l'article 46). Ni adéquation ni garantie : bloquant. Une dérogation de l'article 49 seule n'est pas acceptée comme base. |
| Évaluation de l'impact du transfert | CJUE C-311/18 (Schrems II), clause 14 des CCT | CCT sans évaluation documentée : bloquant. Pour les autres outils de l'article 46 : point recommandé. |
| Contrat de sous-traitance | art. 28, par. 2 à 4 et 9 | Un contrat écrit et douze clauses : objet et durée, nature et finalité, types de données et catégories de personnes, instructions documentées, confidentialité du personnel, mesures de l'art. 32, autorisation préalable des sous-traitants ultérieurs, répercussion des obligations aux sous-traitants ultérieurs, aide pour les droits des personnes, aide pour les art. 32 à 36, suppression ou restitution, audit et inspection. Chaque clause manquante est bloquante. |
| Sécurité | art. 32 | Sept mesures courantes (chiffrement en transit, pseudonymisation, accès par rôle, journalisation des accès, contrôle d'accès physique, politique sur téléphones personnels et supports amovibles, bureau propre). Recommandées individuellement, non bloquantes ; n'en déclarer aucune est bloquant. La liste n'est pas exhaustive : l'art. 32 exige des mesures adaptées au risque. |
| Violation de données | art. 33, par. 2 | Une procédure écrite imposant au sous-traitant de notifier le responsable du traitement dans les meilleurs délais est bloquante si elle est absente. |
| Droits des personnes | art. 12 à 22, art. 28, par. 3, point e | Un processus et des délais convenus avec le prestataire (recommandé). |
| Preuve facultative | ISO/IEC 27001 | Périmètre du certificat vérifié. À titre informatif seulement, jamais une preuve de conformité au RGPD. |

L'outil est **fail-closed** (échec par défaut) : seul un `true` JSON explicite satisfait un contrôle. Une réponse absente, `null`, inconnue ou mal formée (par exemple la chaîne `"true"` ou un nombre) est signalée `to_verify` (à vérifier), jamais comme conforme. Un **écart bloquant** est un point bloquant déclaré absent (`gap`) ou non démontré (`to_verify`).

## Démarrage rapide

```sh
python3 rgpd_offshore_check.py examples/answers.json --lang fr  # rapport Markdown en français
python3 rgpd_offshore_check.py examples/answers.json --json     # sortie lisible par machine
python3 rgpd_offshore_check.py examples/answers_minimal.json    # presque rien de renseigné
python3 -m unittest discover -s tests -v                        # lancer les tests
```

Lancez l'outil une fois par pays de destination. Options : `--json`, `--lang en|fr` (défaut `en`), `--help`, `--version`.

## Format d'entrée

Un objet JSON. Toutes les clés sont facultatives ; une clé absente est signalée `to_verify`. Les clés commençant par `_` sont des commentaires libres, ignorés. Les clés non reconnues sont ignorées avec un avertissement dans le rapport (une faute de frappe ne passe jamais en silence). Les clés dupliquées, `NaN` et un fichier dont la racine n'est pas un objet sont rejetés.

| Clé | Type | Signification |
|---|---|---|
| `label` | chaîne | Nom libre du montage, repris dans le rapport. |
| `destination_country` | chaîne | Destination du transfert. |
| `adequacy_decision` | booléen | Une décision d'adéquation de l'UE existe pour la destination. Consultez la liste à jour de la Commission européenne : l'outil n'en embarque aucune, donc elle ne peut pas devenir obsolète. |
| `adequacy_scope_verified` | booléen | Vous avez vérifié que le champ territorial et sectoriel de la décision (art. 45, par. 3) couvre votre transfert. |
| `safeguards` | liste de chaînes | Outils de l'article 46 en place : `scc`, `bcr`, `code_of_conduct`, `certification`, `ad_hoc_clauses`, `public_authority_instrument`. `art49_derogation` est reconnu mais jamais accepté comme base générale. |
| `tia_documented` | booléen | Une évaluation de l'impact du transfert est documentée. |
| `art28_contract.in_writing` | booléen | Un contrat écrit de sous-traitance existe. |
| `art28_contract.clauses.<nom>` | booléen | La clause figure au contrat. Noms : `subject_matter_and_duration`, `nature_and_purpose`, `data_types_and_data_subject_categories`, `documented_instructions`, `personnel_confidentiality`, `security_measures_art32`, `subprocessor_prior_authorisation`, `subprocessor_flowdown`, `data_subject_rights_assistance`, `art32_36_assistance`, `deletion_or_return`, `audit_and_inspection`. |
| `security_controls.<nom>` | booléen | Noms : `encryption_in_transit`, `pseudonymisation`, `role_based_access`, `access_logging`, `physical_access_control`, `personal_devices_policy`, `clean_desk`. |
| `breach_notification_procedure` | booléen | Procédure écrite imposant au sous-traitant de notifier le responsable du traitement. |
| `data_subject_rights_process` | booléen | Processus et délais convenus avec le prestataire. |
| `iso27001_scope_verified` | booléen | Périmètre du certificat vérifié (à titre informatif). |

Exemple fictif court (le complet : [examples/answers.json](examples/answers.json)) :

```json
{
  "label": "Détaillant fictif, équipe support au Maroc",
  "destination_country": "Maroc",
  "adequacy_decision": false,
  "safeguards": ["scc"],
  "tia_documented": false,
  "art28_contract": {
    "in_writing": true,
    "clauses": { "subprocessor_prior_authorisation": false }
  },
  "breach_notification_procedure": true
}
```

## Exemple de sortie

`python3 rgpd_offshore_check.py examples/answers.json --lang fr` (extrait) :

```text
## Synthèse

- Résultat : ÉCART(S) BLOQUANT(S) TROUVÉ(S)
- Bloquants : 2 écart(s) déclaré(s), 0 réponse(s) à vérifier
- Mesures recommandées ouvertes : 2
- Éléments informatifs ouverts : 1
- Décompte : OK 22 | ÉCART 5 | À VÉRIFIER 0 | N/A 0

### Éléments bloquants

- [ÉCART] `TRANSFER-TIA` Évaluation de l'impact du transfert documentée lorsqu'un outil de l'article 46 est utilisé (Schrems II)
- [ÉCART] `ART28-SUBPROCESSOR-PRIOR-AUTHORISATION` Clause du contrat : Autorisation écrite préalable, spécifique ou générale, pour le recours à des sous-traitants ultérieurs
```

Avec `--json`, le schéma est stable (`schema_version: 1`) ; les identifiants, statuts et codes `reason` ne dépendent pas de la langue.

## Codes de sortie

| Code | Signification |
|---|---|
| 0 | Aucun écart bloquant dans les réponses déclarées (ce n'est pas un constat de conformité). |
| 1 | Au moins un écart bloquant : un point bloquant déclaré absent ou non démontré. |
| 2 | Entrée ou usage invalide : fichier illisible, JSON invalide, clé dupliquée, racine qui n'est pas un objet, option inconnue. Rien n'est écrit sur la sortie standard ; l'erreur va sur stderr (en anglais). |

## Limites

- L'outil ne lit que ce que vous déclarez. Il n'inspecte ni les contrats, ni les systèmes, ni les sites, et un `true` n'est pas vérifié.
- Il n'évalue ni le droit ni les pratiques de surveillance du pays de destination. L'évaluation de l'impact du transfert doit être faite par des personnes ; l'outil enregistre seulement si elle est documentée.
- Il n'embarque aucune liste de décisions d'adéquation, volontairement : les listes évoluent. Consultez la liste à jour de la Commission et le champ de la décision.
- Il ne couvre que l'externalisation à l'étranger. Il ne couvre pas l'analyse d'impact relative à la protection des données (art. 35), le registre des traitements (art. 30), l'information des personnes (art. 13 et 14), la responsabilité conjointe (art. 26), les règles de prospection téléphonique ou par courriel, l'enregistrement des appels, les règles sociales ou sectorielles, ni le droit national du pays de destination.
- La checklist de l'art. 28 suit le texte de l'art. 28, par. 2 à 4 et 9. Votre autorité de contrôle ou votre conseil peuvent attendre davantage.
- Un point recommandé ou informatif ne modifie jamais le code de sortie. L'ISO/IEC 27001 est un élément de preuve sur le management de la sécurité de l'information, pas une preuve de conformité au RGPD.
- Les mentions de documents du CEPD (lignes directrices 2/2018 sur l'art. 49, recommandations 01/2020 sur les mesures supplémentaires) sont des repères ; lisez les originaux.

## Sources officielles

- RGPD, règlement (UE) 2016/679 : https://eur-lex.europa.eu/eli/reg/2016/679/oj
- Clauses contractuelles types, décision d'exécution (UE) 2021/914 de la Commission : https://eur-lex.europa.eu/eli/dec_impl/2021/914/oj
- CJUE, affaire C-311/18 (Schrems II) : https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:62018CJ0311 (aussi sur https://curia.europa.eu/)

Article associé (français) : https://altavista360.com/blog/rgpd-externalisation-offshore/

---

Created by ALTA VISTA360, S.L.U. (`kanibal-studio`).

- [Altavista360](https://altavista360.com/)
- [Altavista Conseil](https://altavista-conseil.com/)
- [Kanibal Studio](https://infos.kanibal-studio.com/)

Licensed under the [MIT License](LICENSE).
