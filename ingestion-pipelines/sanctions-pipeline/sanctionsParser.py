import orjson

RELATIONSHIP_MAPPING = {
    "owner":          "OWNS",
    "director":       "DIRECTOR_OF",
    "associate":      "ASSOCIATED_WITH",
    "parent":         "PARENT_OF",
    "subsidiary":     "SUBSIDIARY_OF",
    "familyPerson":   "FAMILY_OF",
    "member":         "MEMBER_OF",
    "employee":       "EMPLOYEE_OF",
    "operator":       "OPERATES",
    "holder":         "HOLDS",
    "representative": "REPRESENTS",
    "sibling":        "SIBLING_OF",
    "spouse":         "SPOUSE_OF",
    # Sanction record → sanctioned entity (schema=Sanction, property=entity)
    "entity":         "SANCTIONED_BY",
    # Security → issuing company (schema=Security, property=issuer)
    "issuer":         "ISSUED_BY",
}

# Schema-specific properties to extract (first value wins)
_SCHEMA_PROPS = {
    "Person":       ["birthDate", "position", "passportNumber"],
    "Company":      ["incorporationDate", "registrationNumber", "jurisdiction"],
    "LegalEntity":  ["incorporationDate", "registrationNumber", "jurisdiction"],
    "Organization": ["incorporationDate", "registrationNumber", "jurisdiction"],
    "Vessel":       ["imoNumber", "mmsi", "flag", "vesselType", "callSign"],
    "Security":     ["isin", "cusip", "ticker", "exchange"],
    "Sanction":     ["program", "startDate", "endDate", "reason", "authority"],
    "Position":     ["description"],
}


def parse_entity(entity: dict) -> tuple[dict, list[dict]]:
    schema = entity.get("schema", "")
    props = entity.get("properties", {})

    def _first(key: str) -> str:
        vals = props.get(key, [])
        return vals[0] if vals else ""

    def _joined(key: str) -> str:
        return ",".join(str(v) for v in props.get(key, []))

    node: dict = {
        "id":       entity["id"],
        "name":     entity.get("caption", ""),
        "schema":   schema,
        "datasets": ",".join(entity.get("datasets", [])),
        # topics is the primary categorisation field:
        # values: pep, sanction, debarment, crime, wanted, freeze, regulatory
        "topics":   _joined("topics"),
        "aliases":  ",".join(
            [str(v) for v in props.get("alias", [])] +
            [str(v) for v in props.get("weakAlias", [])]
        ),
        "country":  _joined("country") or _joined("nationality"),
    }

    for field in _SCHEMA_PROPS.get(schema, []):
        node[field] = _first(field)

    rels: list[dict] = []
    for field, rel_type in RELATIONSHIP_MAPPING.items():
        for target in props.get(field, []):
            rels.append({"source": entity["id"], "target": str(target), "rel_type": rel_type})

    return node, rels


def stream_entities(filename: str):
    with open(filename, "rb") as f:
        for line in f:
            yield orjson.loads(line)
