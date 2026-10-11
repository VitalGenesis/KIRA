TOOLS = {}


def register(name, description, handler, schema, risk="low", confirm=False):
    TOOLS[name] = {
        "name": name,
        "description": description,
        "handler": handler,
        "schema": schema,
        "risk": risk,
        "confirm": confirm,
    }


def public_definitions():
    return [
        {
            "name": v["name"],
            "description": v["description"],
            "schema": v["schema"],
            "risk": v["risk"],
            "confirm": v["confirm"],
        }
        for v in TOOLS.values()
    ]
