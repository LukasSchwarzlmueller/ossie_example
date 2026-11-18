"""Rescue the Ossie file that the official Databricks converter writes for a joined Metric View.

The converter (wrap_metric_view_in_ossie_model) returns one dataset that reads the Metric View itself,
with no tables, no relationship and measures only Databricks can evaluate. Its names, descriptions,
labels and synonyms are kept. Everything it dropped is restored from the Metric View YAML: the source
and each join become a dataset, each join a relationship, each dimension a field of the table it reads,
each measure a model metric with its formula. What Ossie has no field for (format, window, ...) goes
into a DATABRICKS extension.

A Metric View has one namespace, so a join key is often exposed under another name (customer_key for
customers.customer_id). Ossie fields belong to one table, so a join key gets its real column name back.

Anything it cannot map faithfully stops with an error: nested or one_to_many joins, join conditions
other than equal columns, wildcards, and dimensions that read more than one table.
"""

import re

import yaml

PORTABLE = "OSSIE_SQL_2026"
DATABRICKS = "DATABRICKS"
FACT_ALIAS = "source"
COLUMN = re.compile(r"\w+")
SIMPLE_AGGREGATE = re.compile(r"(SUM|AVG|MIN|MAX|COUNT)\(\s*(DISTINCT\s+)?(\*|\w+(\.\w+)?)\s*\)", re.IGNORECASE)
STRING_LITERAL = re.compile(r"('(?:[^']|'')*')")


class MetricViewRescueError(ValueError):
    """The Metric View uses something this rescue cannot map faithfully."""


def _extension(stash: dict) -> dict:
    return {"nonportable_extensions": [{"vendor_name": DATABRICKS, "data": {"_v": 1, **stash}}]} if stash else {}


def _stash(item: dict, keys: tuple[str, ...]) -> dict:
    return {key: item[key] for key in keys if key in item}


def _expression(text: str, dialect: str) -> dict:
    return {"dialects": [{"dialect": dialect, "expression": text}]}


def _outside_literals(text: str, rewrite) -> str:
    """Apply `rewrite` to the SQL in `text`, leaving quoted strings alone."""
    parts = STRING_LITERAL.split(text)
    return "".join(part if index % 2 else rewrite(part) for index, part in enumerate(parts))


def _qualifiers(text: str, aliases: set[str]) -> set[str]:
    found: set[str] = set()
    for index, part in enumerate(STRING_LITERAL.split(text)):
        if not index % 2:
            found |= {alias for alias in aliases if re.search(rf"\b{re.escape(alias)}\s*\.", part)}
    return found


def _join_columns(join: dict, child: str) -> tuple[list[str], list[str]]:
    """(fact columns, joined table columns) of an equal-columns join."""
    condition = join.get("on")
    if not condition:
        if not join.get("using"):
            raise MetricViewRescueError(f"join '{child}' has no 'on' or 'using' condition")
        return list(join["using"]), list(join["using"])

    fact_columns, child_columns = [], []
    for clause in re.split(r"\s+AND\s+", condition, flags=re.IGNORECASE):
        found = re.fullmatch(r"\s*(?:(\w+)\.)?(\w+)\s*=\s*(?:(\w+)\.)?(\w+)\s*", clause)
        if not found:
            raise MetricViewRescueError(f"join '{child}': only equal columns are supported, got '{condition}'")
        left_alias, left, right_alias, right = found.groups()
        if right_alias == child and left_alias in (FACT_ALIAS, None):
            fact_columns.append(left)
            child_columns.append(right)
        elif left_alias == child and right_alias in (FACT_ALIAS, None):
            fact_columns.append(right)
            child_columns.append(left)
        else:
            raise MetricViewRescueError(f"join '{child}': only equal columns are supported, got '{condition}'")
    return fact_columns, child_columns


def _dataset_of(dimension: dict, fact: str, joined: set[str]) -> tuple[str, str]:
    """(dataset the dimension belongs to, its expression without table qualifiers)."""
    name, expr = dimension["name"], dimension["expr"].strip()
    if "*" in expr:
        raise MetricViewRescueError(f"dimension '{name}': wildcards are not supported")
    used = _qualifiers(expr, joined | {FACT_ALIAS})
    if len(used) > 1:
        raise MetricViewRescueError(f"dimension '{name}' reads more than one table: {sorted(used)}")
    alias = used.pop() if used else FACT_ALIAS
    bare = _outside_literals(expr, lambda sql: re.sub(rf"\b{re.escape(alias)}\s*\.\s*", "", sql))
    return (fact if alias == FACT_ALIAS else alias), bare


def _converted(items: dict, kind: str, name: str) -> dict:
    """What the converter wrote for this dimension or measure, without its expression."""
    if name not in items:
        raise MetricViewRescueError(f"the converter output has no {kind} '{name}'")
    return {key: value for key, value in items[name].items() if key not in ("name", "expression")}


def _field(dimension: dict, expr: str, converted: dict) -> dict:
    field = {
        "name": dimension["name"],
        "expression": _expression(expr, PORTABLE if COLUMN.fullmatch(expr) else DATABRICKS),
    }
    return field | _converted(converted, "field", dimension["name"]) | _extension(_stash(dimension, ("format",)))


def _metric(measure: dict, fact: str, view_is_filtered: bool, converted: dict) -> dict:
    expr = _outside_literals(measure["expr"].strip(), lambda sql: re.sub(rf"\b{FACT_ALIAS}\s*\.", f"{fact}.", sql))
    # A window, partition or view filter changes the value, so a plain aggregate would be wrong elsewhere.
    portable = (
        SIMPLE_AGGREGATE.fullmatch(expr)
        and not view_is_filtered
        and not {"window", "partition"} & measure.keys()
    )
    metric = {"name": measure["name"], "expression": _expression(expr, PORTABLE if portable else DATABRICKS)}
    return metric | _converted(converted, "metric", measure["name"]) | _extension(_stash(measure, ("format", "window", "partition", "display_name")))


def _is_used_by_measures(name: str, measures: list[dict]) -> bool:
    return any(re.search(rf"\b{re.escape(name)}\b", f"{m['expr']} {m.get('window', '')}") for m in measures)


def _key_fields(columns: list[str], dataset: dict, measures: list[dict]) -> list[str]:
    """The fields that read these columns, named after the column wherever that is safe."""
    names = []
    for column in columns:
        fields = dataset["fields"]
        taken = any(f["name"] == column for f in fields)
        match = next((f for f in fields if f["expression"]["dialects"][0]["expression"] == column), None)
        if match is None:  # the view joins on a column it doesn't expose
            if taken:
                raise MetricViewRescueError(f"dataset '{dataset['name']}': field '{column}' hides the join column")
            match = {"name": column, "expression": _expression(column, PORTABLE)}
            fields.append(match)
        elif not taken and not _is_used_by_measures(match["name"], measures):
            match["name"] = column
        names.append(match["name"])
    return names


def rescue_converter_output(converted: dict, metric_view_yaml: str) -> dict:
    """The full Ossie model: the converter's output plus what it dropped from the Metric View."""
    if len(converted["datasets"]) != 1:
        raise MetricViewRescueError("expected the converter's one-dataset model")
    wrapped = converted["datasets"][0]
    converted_fields = {field["name"]: field for field in wrapped.get("fields") or []}
    converted_metrics = {metric["name"]: metric for metric in wrapped.get("metrics") or []}
    view = yaml.safe_load(metric_view_yaml)
    source = view["source"]
    if not re.fullmatch(r"[\w`-]+(\.[\w`-]+)*", source):
        raise MetricViewRescueError("a Metric View reading a SQL query as its source is not supported")

    fact = source.rsplit(".", 1)[-1].strip("`")
    joins = view.get("joins") or []
    for join in joins:
        if join.get("joins"):
            raise MetricViewRescueError(f"join '{join['name']}': nested joins are not supported")
        if str(join.get("cardinality", "many_to_one")).lower() != "many_to_one":
            raise MetricViewRescueError(f"join '{join['name']}': only many_to_one joins are supported")
    joined = {join["name"] for join in joins}
    if FACT_ALIAS in joined or fact in joined:
        raise MetricViewRescueError(f"a join may not be named '{FACT_ALIAS}' or '{fact}'")

    datasets = {fact: {"name": fact, "source": source, "fields": []}}
    for join in joins:
        datasets[join["name"]] = {"name": join["name"], "source": join["source"], "fields": []}
    for dimension in view.get("dimensions") or view.get("fields") or []:
        dataset, expr = _dataset_of(dimension, fact, joined)
        datasets[dataset]["fields"].append(_field(dimension, expr, converted_fields))

    measures = view.get("measures") or []
    relationships = []
    for join in joins:
        child = join["name"]
        fact_columns, child_columns = _join_columns(join, child)
        to_columns = _key_fields(child_columns, datasets[child], measures)
        if (join.get("rely") or {}).get("at_most_one_match"):
            datasets[child] = {
                "name": child,
                "source": join["source"],
                "unique_keys": [list(to_columns)],
                "fields": datasets[child]["fields"],
            }
        relationships.append({
            "name": f"{fact}_to_{child}",
            "from": fact,
            "to": child,
            "from_columns": _key_fields(fact_columns, datasets[fact], measures),
            "to_columns": to_columns,
        } | _extension(_stash(join, ("rely", "cardinality", "on"))))

    model = {"version": converted["version"], "name": fact}
    if wrapped.get("description"):
        model["description"] = wrapped["description"]
    model["datasets"] = list(datasets.values())
    if relationships:
        model["relationships"] = relationships
    if measures:
        model["metrics"] = [_metric(measure, fact, "filter" in view, converted_metrics) for measure in measures]
    return model | _extension(_stash(view, ("filter", "parameters", "materialization")))
