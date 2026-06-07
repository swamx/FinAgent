# parser.py

import orjson

RELATIONSHIP_MAPPING = {
    "owner": "OWNS",
    "director": "DIRECTOR_OF",
    "associate": "ASSOCIATED_WITH",
    "parent": "PARENT_OF",
    "subsidiary": "SUBSIDIARY_OF",
    "familyPerson": "FAMILY_OF",
    "member": "MEMBER_OF",
    "employee": "EMPLOYEE_OF",
    "operator": "OPERATES"
}


def parse_entity(entity):

    node = {
        "id": entity["id"],
        "name": entity.get("caption"),
        "schema": entity.get("schema"),
        "datasets": ",".join(
            entity.get("datasets", [])
        )
    }

    rels = []

    props = entity.get(
        "properties",
        {}
    )

    for field, rel_type in RELATIONSHIP_MAPPING.items():

        values = props.get(field, [])

        for target in values:

            rels.append(
                {
                    "source": entity["id"],
                    "target": target,
                    "rel_type": rel_type
                }
            )

    return node, rels


def stream_entities(filename):

    with open(filename, "rb") as f:

        for line in f:
            yield orjson.loads(line)