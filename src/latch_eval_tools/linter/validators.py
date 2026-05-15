import re

from pydantic import ValidationError

from ..graders.predicate import BOOLEAN_OPS, KNOWN_OPS, resolve_jsonpath
from ..types import EvalGraderSelection
from .schema import (
    ALLOWED_GRADER_FIELDS,
    ALLOWED_METADATA_FIELDS,
    ALLOWED_TOP_LEVEL_FIELDS,
    DATA_NODE_PATTERN,
    GRADER_CONFIGS,
    MULTIPLE_CHOICE_PLACEHOLDER,
    VALID_EVAL_TYPES,
    VALID_GRADER_TYPES,
    VALID_KITS,
    VALID_TASKS,
    VALID_TIME_HORIZONS,
    VALID_TOLERANCE_TYPES,
    LintIssue,
)


def validate_required_fields(data: dict) -> list[LintIssue]:
    issues = []

    if "id" not in data:
        issues.append(LintIssue("error", "E001", "Missing required field: id"))
    elif not isinstance(data["id"], str) or not data["id"].strip():
        issues.append(
            LintIssue("error", "E002", "Field 'id' must be a non-empty string")
        )

    if "task" not in data:
        issues.append(LintIssue("error", "E003", "Missing required field: task"))
    elif not isinstance(data["task"], str) or not data["task"].strip():
        issues.append(
            LintIssue("error", "E004", "Field 'task' must be a non-empty string")
        )

    if "metadata" not in data:
        issues.append(LintIssue("error", "E005", "Missing required field: metadata"))
    elif not isinstance(data["metadata"], dict):
        issues.append(LintIssue("error", "E006", "Field 'metadata' must be an object"))

    return issues


def validate_metadata(data: dict) -> list[LintIssue]:
    issues = []
    metadata = data.get("metadata")

    if not isinstance(metadata, dict):
        return issues

    if "task" not in metadata:
        issues.append(
            LintIssue("error", "E010", "Missing required field: metadata.task")
        )
    elif metadata["task"] not in VALID_TASKS:
        issues.append(
            LintIssue(
                "error",
                "E011",
                f"Invalid metadata.task: '{metadata['task']}'. Must be one of: {VALID_TASKS}",
            )
        )

    if "kit" not in metadata:
        issues.append(
            LintIssue("error", "E012", "Missing required field: metadata.kit")
        )
    elif metadata["kit"] not in VALID_KITS:
        issues.append(
            LintIssue(
                "error",
                "E013",
                f"Invalid metadata.kit: '{metadata['kit']}'. Must be one of: {VALID_KITS}",
            )
        )

    if "time_horizon" not in metadata:
        issues.append(
            LintIssue("error", "E014", "Missing required field: metadata.time_horizon")
        )
    elif metadata["time_horizon"] not in VALID_TIME_HORIZONS:
        issues.append(
            LintIssue(
                "error",
                "E015",
                f"Invalid metadata.time_horizon: '{metadata['time_horizon']}'. Must be one of: {VALID_TIME_HORIZONS}",
            )
        )

    if "eval_type" not in metadata:
        issues.append(
            LintIssue(
                "warning",
                "W001",
                f"Missing metadata.eval_type. Consider adding one of: {VALID_EVAL_TYPES}",
            )
        )
    elif metadata["eval_type"] not in VALID_EVAL_TYPES:
        issues.append(
            LintIssue(
                "error",
                "E016",
                f"Invalid metadata.eval_type: '{metadata['eval_type']}'. Must be one of: {VALID_EVAL_TYPES}",
            )
        )

    return issues


def validate_data_node(data: dict) -> list[LintIssue]:
    issues = []
    data_node = data.get("data_node")

    if data_node is None:
        return issues

    def check_node(node: str, location: str) -> list[LintIssue]:
        if not isinstance(node, str):
            return [
                LintIssue(
                    "error",
                    "E020",
                    f"data_node must be string, got {type(node).__name__}",
                    location,
                )
            ]
        if not DATA_NODE_PATTERN.match(node):
            return [
                LintIssue(
                    "error",
                    "E021",
                    f"Invalid data_node format: '{node}'. Expected: latch://<id>.(account|node)/<path>",
                    location,
                )
            ]
        return []

    if isinstance(data_node, str):
        issues.extend(check_node(data_node, "data_node"))
    elif isinstance(data_node, list):
        for i, node in enumerate(data_node):
            issues.extend(check_node(node, f"data_node[{i}]"))
    else:
        issues.append(
            LintIssue(
                "error",
                "E022",
                f"data_node must be string or list, got {type(data_node).__name__}",
            )
        )

    return issues


def validate_task_answer_format(data: dict) -> list[LintIssue]:
    issues = []
    task = data.get("task", "")
    grader_types = _collect_grader_types(data)

    if "<EVAL_ANSWER>" not in task:
        issues.append(
            LintIssue(
                "warning",
                "W010",
                "Task description does not contain <EVAL_ANSWER> format specification",
            )
        )
    elif "</EVAL_ANSWER>" not in task:
        issues.append(
            LintIssue(
                "warning",
                "W011",
                "Task description has <EVAL_ANSWER> but missing closing </EVAL_ANSWER> tag",
            )
        )
    else:
        task_lower = task.lower()
        has_return_exactly = (
            "return exactly" in task_lower or "respond exactly" in task_lower
        )
        if not has_return_exactly:
            issues.append(
                LintIssue(
                    "warning",
                    "W012",
                    "Task has <EVAL_ANSWER> but missing 'Return EXACTLY:' instruction before it",
                )
            )

        if "multiple_choice" in grader_types:
            answer_pattern = re.search(r'"answer"\s*:\s*"([^"]*)"', task)
            if answer_pattern:
                placeholder = answer_pattern.group(1)
                if placeholder != MULTIPLE_CHOICE_PLACEHOLDER:
                    issues.append(
                        LintIssue(
                            "warning",
                            "W013",
                            f"Multiple choice answer placeholder should be '{MULTIPLE_CHOICE_PLACEHOLDER}', "
                            f"found '{placeholder}'",
                            "task",
                        )
                    )

    return issues


def validate_grader(data: dict) -> list[LintIssue]:
    grader = data.get("grader")
    if grader is None:
        return []

    return _validate_single_grader(grader, grader_path="grader")


def validate_graders(data: dict) -> list[LintIssue]:
    if "graders" not in data and "grader" not in data:
        return []

    selection_payload = {key: data[key] for key in ("grader", "graders") if key in data}

    try:
        selection = EvalGraderSelection.model_validate(selection_payload)
    except ValidationError as exc:
        return _selection_validation_issues(exc, data)

    if selection.graders is None:
        return []

    issues: list[LintIssue] = []
    for i, grader in enumerate(selection.graders):
        issues.extend(_validate_single_grader(grader, f"graders[{i}]"))
    return issues


def _selection_validation_issues(exc: ValidationError, data: dict) -> list[LintIssue]:
    issues: list[LintIssue] = []

    for err in exc.errors():
        err_type = err.get("type", "")
        loc = err.get("loc", ())
        head = loc[0] if loc else None

        if err_type == "value_error":
            message = err.get("msg", "")
            prefix = "Value error, "
            if message.startswith(prefix):
                message = message[len(prefix) :]
            code = "E038" if "mutually exclusive" in message else "E039"
            issues.append(LintIssue("error", code, message, "graders"))
            continue

        if head == "graders":
            graders_value = data.get("graders")
            if not isinstance(graders_value, list):
                message = (
                    "Field 'graders' must be a non-empty list, got "
                    f"{type(graders_value).__name__}"
                )
            else:
                message = (
                    "Field 'graders' items must be objects; "
                    f"got invalid item at graders[{loc[1]}]"
                    if len(loc) > 1
                    else "Field 'graders' must be a non-empty list"
                )
            issues.append(LintIssue("error", "E039", message, "graders"))
            continue

        if head == "grader":
            grader_value = data.get("grader")
            message = f"grader must be object, got {type(grader_value).__name__}"
            issues.append(LintIssue("error", "E030", message, "grader"))

    return issues


def _validate_single_grader(grader, grader_path: str) -> list[LintIssue]:
    issues = []

    if not isinstance(grader, dict):
        issues.append(
            LintIssue(
                "error",
                "E030",
                f"grader must be object, got {type(grader).__name__}",
                grader_path,
            )
        )
        return issues

    grader_type = grader.get("type")
    if grader_type is None:
        issues.append(
            LintIssue(
                "error",
                "E031",
                "Missing required field: grader.type",
                f"{grader_path}.type",
            )
        )
        return issues

    if grader_type not in VALID_GRADER_TYPES:
        issues.append(
            LintIssue(
                "error",
                "E032",
                f"Invalid grader.type: '{grader_type}'. Must be one of: {VALID_GRADER_TYPES}",
                f"{grader_path}.type",
            )
        )
        return issues

    config = grader.get("config")
    if config is None:
        issues.append(
            LintIssue(
                "error",
                "E033",
                "Missing required field: grader.config",
                f"{grader_path}.config",
            )
        )
        return issues

    if not isinstance(config, dict):
        issues.append(
            LintIssue(
                "error",
                "E034",
                f"grader.config must be object, got {type(config).__name__}",
                f"{grader_path}.config",
            )
        )
        return issues

    grader_spec = GRADER_CONFIGS.get(grader_type, {})

    for req_field in grader_spec.get("required", []):
        if req_field not in config:
            if (
                grader_type == "marker_gene_precision_recall"
                and req_field == "answer_field"
            ):
                issues.append(
                    LintIssue(
                        "error",
                        "E037",
                        "Missing 'answer_field' - specify which JSON field contains the gene list",
                        f"{grader_path}.config.{req_field}",
                    )
                )
            else:
                issues.append(
                    LintIssue(
                        "error",
                        "E035",
                        f"Missing required config field for {grader_type}: {req_field}",
                        f"{grader_path}.config.{req_field}",
                    )
                )

    for req_any_group in grader_spec.get("required_any", []):
        if not any(f in config for f in req_any_group):
            issues.append(
                LintIssue(
                    "error",
                    "E036",
                    f"Missing required config field for {grader_type}: one of {req_any_group}",
                    f"{grader_path}.config",
                )
            )

    issues.extend(_validate_tolerances(config, grader_path))
    issues.extend(_validate_ranges(config, grader_path))
    issues.extend(
        _validate_unrecognized_config_fields(grader_type, config, grader_path)
    )
    issues.extend(_validate_config_types(grader_type, config, grader_path))
    issues.extend(_validate_config_semantics(grader_type, config, grader_path))
    issues.extend(_validate_config_edge_cases(grader_type, config, grader_path))
    issues.extend(_validate_taxonomy_grader_config(grader_type, config, grader_path))

    return issues


def _validate_unrecognized_config_fields(
    grader_type: str, config: dict, grader_path: str
) -> list[LintIssue]:
    issues = []
    grader_spec = GRADER_CONFIGS.get(grader_type, {})
    recognized = grader_spec.get("recognized", set())

    if not recognized:
        return issues

    for field in config.keys():
        if field not in recognized:
            issues.append(
                LintIssue(
                    "warning",
                    "W030",
                    f"Config field '{field}' is not recognized by {grader_type} grader and will be ignored",
                    f"{grader_path}.config.{field}",
                )
            )

    return issues


def _validate_config_types(
    grader_type: str, config: dict, grader_path: str
) -> list[LintIssue]:
    issues = []

    if grader_type in ("numeric_tolerance", "distribution_comparison", "numeric_range"):
        ground_truth = config.get("ground_truth")
        if ground_truth is not None and not isinstance(ground_truth, dict):
            issues.append(
                LintIssue(
                    "error",
                    "E060",
                    f"ground_truth must be object, got {type(ground_truth).__name__}",
                    f"{grader_path}.config.ground_truth",
                )
            )

    if grader_type in (
        "label_set_jaccard",
        "jaccard_label_set",
        "marker_gene_precision_recall",
    ):
        ground_truth_labels = config.get("ground_truth_labels")
        if ground_truth_labels is not None and not isinstance(
            ground_truth_labels, list
        ):
            issues.append(
                LintIssue(
                    "error",
                    "E062",
                    f"ground_truth_labels must be list, got {type(ground_truth_labels).__name__}",
                    f"{grader_path}.config.ground_truth_labels",
                )
            )

    if grader_type in (
        "label_set_jaccard",
        "jaccard_label_set",
        "spatial_adjacency",
        "marker_gene_separation",
        "marker_gene_precision_recall",
    ):
        scoring = config.get("scoring")
        if scoring is not None and not isinstance(scoring, dict):
            issues.append(
                LintIssue(
                    "error",
                    "E065",
                    f"scoring must be object, got {type(scoring).__name__}",
                    f"{grader_path}.config.scoring",
                )
            )

    return issues


def _validate_config_semantics(
    grader_type: str, config: dict, grader_path: str
) -> list[LintIssue]:
    issues = []

    if grader_type == "numeric_tolerance":
        ground_truth = config.get("ground_truth", {})
        tolerances = config.get("tolerances", {})
        if isinstance(ground_truth, dict) and isinstance(tolerances, dict):
            for field_name in ground_truth.keys():
                if field_name not in tolerances:
                    issues.append(
                        LintIssue(
                            "warning",
                            "W070",
                            f"ground_truth field '{field_name}' has no tolerance specified (defaults to 0)",
                            f"{grader_path}.config.ground_truth.{field_name}",
                        )
                    )

    issues.extend(_validate_tolerance_values(config, grader_path))
    issues.extend(_validate_threshold_ranges(grader_type, config, grader_path))

    return issues


def _validate_tolerance_values(config: dict, grader_path: str) -> list[LintIssue]:
    issues = []
    tolerances = config.get("tolerances", {})

    if not isinstance(tolerances, dict):
        return issues

    for field_name, tol_config in tolerances.items():
        if not isinstance(tol_config, dict):
            continue

        value = tol_config.get("value")
        if isinstance(value, (int, float)) and value < 0:
            issues.append(
                LintIssue(
                    "error",
                    "E080",
                    f"Tolerance value must be non-negative, got {value}",
                    f"{grader_path}.config.tolerances.{field_name}.value",
                )
            )

        lower = tol_config.get("lower")
        if isinstance(lower, (int, float)) and lower < 0:
            issues.append(
                LintIssue(
                    "error",
                    "E080",
                    f"Tolerance lower bound must be non-negative, got {lower}",
                    f"{grader_path}.config.tolerances.{field_name}.lower",
                )
            )

        upper = tol_config.get("upper")
        if isinstance(upper, (int, float)) and upper < 0:
            issues.append(
                LintIssue(
                    "error",
                    "E080",
                    f"Tolerance upper bound must be non-negative, got {upper}",
                    f"{grader_path}.config.tolerances.{field_name}.upper",
                )
            )

    return issues


def _validate_threshold_ranges(
    grader_type: str, config: dict, grader_path: str
) -> list[LintIssue]:
    issues = []
    scoring = config.get("scoring", {})

    if not isinstance(scoring, dict):
        return issues

    if grader_type in ("label_set_jaccard", "jaccard_label_set"):
        pass_threshold = scoring.get("pass_threshold")
        if isinstance(pass_threshold, (int, float)):
            if pass_threshold < 0 or pass_threshold > 1:
                issues.append(
                    LintIssue(
                        "error",
                        "E081",
                        f"Jaccard pass_threshold must be in [0, 1], got {pass_threshold}",
                        f"{grader_path}.config.scoring.pass_threshold",
                    )
                )

    if grader_type == "marker_gene_precision_recall":
        pass_thresholds = scoring.get("pass_thresholds", {})
        if isinstance(pass_thresholds, dict):
            for key in ("precision_at_k", "recall_at_k"):
                val = pass_thresholds.get(key)
                if isinstance(val, (int, float)) and (val < 0 or val > 1):
                    issues.append(
                        LintIssue(
                            "error",
                            "E082",
                            f"Precision/recall threshold must be in [0, 1], got {val}",
                            f"{grader_path}.config.scoring.pass_thresholds.{key}",
                        )
                    )

    return issues


def _validate_config_edge_cases(
    grader_type: str, config: dict, grader_path: str
) -> list[LintIssue]:
    issues = []

    if grader_type == "numeric_tolerance":
        has_tolerance = "tolerance" in config
        has_tolerances = "tolerances" in config
        if has_tolerance and has_tolerances:
            issues.append(
                LintIssue(
                    "warning",
                    "W085",
                    "Both 'tolerance' and 'tolerances' present; 'tolerances' will be used",
                    f"{grader_path}.config",
                )
            )

    if grader_type == "marker_gene_precision_recall":
        has_canonical = "canonical_markers" in config
        has_ground_truth_labels = "ground_truth_labels" in config
        if not has_canonical and has_ground_truth_labels:
            issues.append(
                LintIssue(
                    "warning",
                    "W086",
                    "Using 'ground_truth_labels' as fallback for 'canonical_markers'",
                    f"{grader_path}.config",
                )
            )

    if grader_type == "distribution_comparison":
        ground_truth = config.get("ground_truth", {})
        if isinstance(ground_truth, dict):
            distribution = ground_truth.get("cell_type_distribution", ground_truth)
            if isinstance(distribution, dict):
                percentages = [
                    v for v in distribution.values() if isinstance(v, (int, float))
                ]
                if percentages:
                    total = sum(percentages)
                    if abs(total - 100) > 5:
                        issues.append(
                            LintIssue(
                                "warning",
                                "W080",
                                f"Distribution percentages sum to {total}, expected ~100%",
                                f"{grader_path}.config.ground_truth",
                            )
                        )

    return issues


_PREDICATE_OP_RECOGNIZED: dict[str, set[str]] = {
    "equals": {"op", "arg"},
    "in": {"op", "args"},
    "unordered_set_eq": {"op", "expected"},
    "and": {"op", "args"},
    "or": {"op", "args"},
    "not": {"op", "arg"},
    "any": {"op", "path", "body"},
    "every": {"op", "path", "body"},
    "none": {"op", "path", "body"},
    "field": {"op", "name", "body"},
    "jaccard_ge": {"op", "possible_sets", "threshold"},
    "f1": {"op", "expected"},
    "jaccard": {"op", "possible_sets"},
    "weighted_label": {"op", "table", "default"},
}

_PREDICATE_MAX_DEPTH = 8
_COMPOSITE_MAX_DEPTH = 8


def _validate_taxonomy_grader_config(
    grader_type: str, config: dict, grader_path: str
) -> list[LintIssue]:
    """Single dispatcher for the predicate-leaf / composite taxonomy."""
    location = f"{grader_path}.config"
    if grader_type == "predicate_leaf":
        return _validate_predicate_leaf_inline(config, location, allow_additive=False)
    if grader_type == "all_of":
        return _validate_all_of_config(config, location)
    if grader_type == "list_match":
        return _validate_list_match_config(config, location)
    if grader_type == "dict_match":
        return _validate_dict_match_config(config, location)
    return []


def _validate_predicate_leaf_inline(
    leaf, location: str, *, allow_additive: bool
) -> list[LintIssue]:
    """Validating a predicate leaf single or as composite"""
    if not isinstance(leaf, dict):
        return [
            LintIssue(
                "error",
                "E070",
                f"predicate-leaf must be an object, got {type(leaf).__name__}",
                location,
            )
        ]

    issues: list[LintIssue] = []

    if "predicate" in leaf:
        issues.extend(_validate_predicate(leaf["predicate"], f"{location}.predicate"))
    else:
        issues.append(
            LintIssue(
                "error",
                "E070",
                "predicate-leaf missing required key 'predicate'",
                location,
            )
        )

    role = leaf.get("role")
    if role is None:
        issues.append(
            LintIssue(
                "error",
                "E074",
                "predicate-leaf missing required key 'role'",
                f"{location}.role",
            )
        )
    elif role not in {"gate", "additive", "hard_fail"}:
        issues.append(
            LintIssue(
                "error",
                "E074",
                f"role must be one of gate/additive/hard_fail, got {role!r}",
                f"{location}.role",
            )
        )
    elif role == "additive" and not allow_additive:
        issues.append(
            LintIssue(
                "error",
                "E076",
                "role 'additive' is invalid here; valid only inside "
                "list_match.ground_truth[*].fields.*, dict_match.ground_truth[*], "
                "or as a direct child of all_of",
                f"{location}.role",
            )
        )
    elif role == "hard_fail" and not leaf.get("name"):
        issues.append(
            LintIssue(
                "error",
                "E090",
                "role 'hard_fail' leafs must declare a 'name' for failure reports",
                f"{location}.name",
            )
        )

    if "threshold" in leaf:
        predicate = leaf.get("predicate")
        op = predicate.get("op") if isinstance(predicate, dict) else None
        if op in BOOLEAN_OPS:
            issues.append(
                LintIssue(
                    "warning",
                    "W040",
                    f"'threshold' is set on a boolean predicate (op={op!r}); it will be ignored",
                    f"{location}.threshold",
                )
            )

    return issues


def _validate_composite_child(child, location: str, depth: int) -> list[LintIssue]:
    """Dispatching one composite child. Can be bare predicate leaf or composite"""
    if depth > _COMPOSITE_MAX_DEPTH:
        return [
            LintIssue(
                "error",
                "E089",
                f"composite nesting exceeds depth {_COMPOSITE_MAX_DEPTH}",
                location,
            )
        ]
    if not isinstance(child, dict):
        return [
            LintIssue(
                "error",
                "E078",
                f"composite child must be an object, got {type(child).__name__}",
                location,
            )
        ]

    if "predicate" in child and "type" not in child:
        return _validate_predicate_leaf_inline(child, location, allow_additive=True)

    if "type" not in child:
        return [
            LintIssue(
                "error",
                "E078",
                "composite child must be a composite envelope ({type, config, ...}) "
                "or a bare predicate-leaf ({predicate, role, ...})",
                location,
            )
        ]

    child_type = child["type"]
    if child_type not in VALID_GRADER_TYPES:
        return [
            LintIssue(
                "error",
                "E032",
                f"Invalid grader.type: {child_type!r}. Must be one of: {VALID_GRADER_TYPES}",
                f"{location}.type",
            )
        ]
    child_config = child.get("config")
    if child_config is None:
        return [
            LintIssue(
                "error",
                "E033",
                "Missing required field: grader.config",
                f"{location}.config",
            )
        ]
    if not isinstance(child_config, dict):
        return [
            LintIssue(
                "error",
                "E034",
                f"grader.config must be object, got {type(child_config).__name__}",
                f"{location}.config",
            )
        ]

    inner_loc = f"{location}.config"
    if child_type == "all_of":
        return _validate_all_of_config(child_config, inner_loc, depth + 1)
    if child_type == "list_match":
        return _validate_list_match_config(child_config, inner_loc, depth + 1)
    if child_type == "dict_match":
        return _validate_dict_match_config(child_config, inner_loc, depth + 1)
    if child_type == "predicate_leaf":
        return _validate_predicate_leaf_inline(
            child_config, inner_loc, allow_additive=True
        )
    return []


def _validate_all_of_config(
    config: dict, location: str, depth: int = 0
) -> list[LintIssue]:
    issues: list[LintIssue] = []

    pass_rule = config.get("pass_rule", "all")
    if pass_rule not in {"all", "min_passing", "score_threshold"}:
        issues.append(
            LintIssue(
                "error",
                "E079",
                f"pass_rule must be one of all/min_passing/score_threshold, got {pass_rule!r}",
                f"{location}.pass_rule",
            )
        )

    children = config.get("children", [])
    if not isinstance(children, list):
        issues.append(
            LintIssue(
                "error",
                "E078",
                f"children must be a list, got {type(children).__name__}",
                f"{location}.children",
            )
        )
        return issues

    n_scoring = sum(
        1
        for c in children
        if not (isinstance(c, dict) and c.get("role") == "hard_fail")
    )

    if pass_rule == "min_passing":
        n = config.get("min_passing_children")
        if not isinstance(n, int) or isinstance(n, bool):
            issues.append(
                LintIssue(
                    "error",
                    "E079",
                    "min_passing_children must be an int when pass_rule='min_passing'",
                    f"{location}.min_passing_children",
                )
            )
        elif n > n_scoring:
            issues.append(
                LintIssue(
                    "error",
                    "E085",
                    f"min_passing_children={n} exceeds count of scoring children ({n_scoring})",
                    f"{location}.min_passing_children",
                )
            )
    elif pass_rule == "score_threshold":
        thr = config.get("score_threshold")
        if not isinstance(thr, (int, float)) or isinstance(thr, bool):
            issues.append(
                LintIssue(
                    "error",
                    "E079",
                    "score_threshold must be a number when pass_rule='score_threshold'",
                    f"{location}.score_threshold",
                )
            )

    for i, child in enumerate(children):
        issues.extend(
            _validate_composite_child(child, f"{location}.children[{i}]", depth)
        )

    return issues


def _validate_list_match_config(
    config: dict, location: str, depth: int = 0
) -> list[LintIssue]:
    issues: list[LintIssue] = []

    match_key = config.get("match_key")
    k = config.get("k")
    tuple_pass_min = config.get("tuple_pass_min", 0)
    additive_score_min = config.get("additive_score_min", 0)
    gt_entries = config.get("ground_truth", [])

    if (
        isinstance(k, int)
        and not isinstance(k, bool)
        and isinstance(tuple_pass_min, int)
        and not isinstance(tuple_pass_min, bool)
        and tuple_pass_min > k
    ):
        issues.append(
            LintIssue(
                "error",
                "E084",
                f"tuple_pass_min={tuple_pass_min} exceeds k={k}",
                f"{location}.tuple_pass_min",
            )
        )

    if not isinstance(gt_entries, list):
        issues.append(
            LintIssue(
                "error",
                "E088",
                f"ground_truth must be a list, got {type(gt_entries).__name__}",
                f"{location}.ground_truth",
            )
        )
        return issues

    n_additive_fields = 0
    for i, gt in enumerate(gt_entries):
        gt_loc = f"{location}.ground_truth[{i}]"
        if not isinstance(gt, dict):
            issues.append(
                LintIssue(
                    "error",
                    "E088",
                    f"ground_truth entry must be object, got {type(gt).__name__}",
                    gt_loc,
                )
            )
            continue
        if isinstance(match_key, str) and match_key not in gt:
            issues.append(
                LintIssue(
                    "error",
                    "E086",
                    f"ground_truth entry missing match_key {match_key!r}",
                    gt_loc,
                )
            )
        fields = gt.get("fields", {})
        if not isinstance(fields, dict):
            issues.append(
                LintIssue(
                    "error",
                    "E088",
                    f"ground_truth[{i}].fields must be object, got {type(fields).__name__}",
                    f"{gt_loc}.fields",
                )
            )
            continue
        for fname, leaf in fields.items():
            issues.extend(
                _validate_predicate_leaf_inline(
                    leaf, f"{gt_loc}.fields.{fname}", allow_additive=True
                )
            )
            if isinstance(leaf, dict) and leaf.get("role") == "additive":
                n_additive_fields += 1

    if (
        isinstance(additive_score_min, (int, float))
        and not isinstance(additive_score_min, bool)
        and additive_score_min > n_additive_fields
    ):
        issues.append(
            LintIssue(
                "warning",
                "W043",
                f"additive_score_min={additive_score_min} exceeds maximum possible "
                f"additive contributions ({n_additive_fields})",
                f"{location}.additive_score_min",
            )
        )

    return issues


def _validate_dict_match_config(
    config: dict, location: str, depth: int = 0
) -> list[LintIssue]:
    issues: list[LintIssue] = []

    gt = config.get("ground_truth")
    if not isinstance(gt, dict):
        issues.append(
            LintIssue(
                "error",
                "E087",
                f"ground_truth must be object, got {type(gt).__name__}",
                f"{location}.ground_truth",
            )
        )
        return issues

    for key, entry in gt.items():
        entry_loc = f"{location}.ground_truth.{key}"
        if not isinstance(entry, dict):
            issues.append(
                LintIssue(
                    "error",
                    "E087",
                    f"ground_truth.{key} must be object, got {type(entry).__name__}",
                    entry_loc,
                )
            )
            continue
        if "predicate" in entry:
            issues.extend(
                _validate_predicate_leaf_inline(entry, entry_loc, allow_additive=True)
            )
            continue
        if "fields" in entry:
            fields = entry["fields"]
            if not isinstance(fields, dict):
                issues.append(
                    LintIssue(
                        "error",
                        "E087",
                        f"ground_truth.{key}.fields must be object, got {type(fields).__name__}",
                        f"{entry_loc}.fields",
                    )
                )
                continue
            for fname, leaf in fields.items():
                issues.extend(
                    _validate_predicate_leaf_inline(
                        leaf, f"{entry_loc}.fields.{fname}", allow_additive=True
                    )
                )
            continue
        issues.append(
            LintIssue(
                "error",
                "E087",
                f"ground_truth.{key} must have 'predicate' (scalar form) or 'fields' (object form)",
                entry_loc,
            )
        )

    return issues


def _validate_predicate(pred, location: str, depth: int = 0) -> list[LintIssue]:
    """Recursively validate a predicate AST node."""
    if depth > _PREDICATE_MAX_DEPTH:
        return [
            LintIssue(
                "error",
                "E077",
                f"predicate nesting exceeds depth {_PREDICATE_MAX_DEPTH}",
                location,
            )
        ]
    if not isinstance(pred, dict):
        return [
            LintIssue(
                "error",
                "E070",
                f"predicate must be an object, got {type(pred).__name__}",
                location,
            )
        ]
    if "op" not in pred:
        return [
            LintIssue(
                "error",
                "E070",
                "predicate must have an 'op' key",
                location,
            )
        ]
    op = pred["op"]
    if op not in KNOWN_OPS:
        return [
            LintIssue(
                "error",
                "E071",
                f"Unknown predicate op: {op!r}. Known ops: {sorted(KNOWN_OPS)}",
                location,
            )
        ]

    issues: list[LintIssue] = []

    recognized = _PREDICATE_OP_RECOGNIZED.get(op, {"op"})
    for key in pred:
        if key not in recognized:
            issues.append(
                LintIssue(
                    "warning",
                    "W042",
                    f"Predicate op {op!r} does not recognize key {key!r}; it will be ignored",
                    f"{location}.{key}",
                )
            )

    if op == "equals":
        if "arg" not in pred:
            issues.append(_missing_pred_arg(op, "arg", location))
    elif op == "in":
        issues.extend(_require_list_arg(pred, op, "args", location))
    elif op == "unordered_set_eq":
        issues.extend(_require_list_arg(pred, op, "expected", location))
    elif op in {"and", "or"}:
        sub_issues = _require_list_arg(pred, op, "args", location)
        issues.extend(sub_issues)
        if not sub_issues:
            for i, sub in enumerate(pred["args"]):
                issues.extend(
                    _validate_predicate(sub, f"{location}.args[{i}]", depth + 1)
                )
    elif op == "not":
        if "arg" not in pred:
            issues.append(_missing_pred_arg(op, "arg", location))
        else:
            issues.extend(
                _validate_predicate(pred["arg"], f"{location}.arg", depth + 1)
            )
    elif op in {"any", "every", "none"}:
        if "path" not in pred:
            issues.append(_missing_pred_arg(op, "path", location))
        else:
            issues.extend(_validate_jsonpath(pred["path"], f"{location}.path"))
        if "body" not in pred:
            issues.append(_missing_pred_arg(op, "body", location))
        else:
            issues.extend(
                _validate_predicate(pred["body"], f"{location}.body", depth + 1)
            )
    elif op == "field":
        name = pred.get("name")
        if name is None:
            issues.append(_missing_pred_arg(op, "name", location))
        elif not isinstance(name, str):
            issues.append(
                LintIssue(
                    "error",
                    "E073",
                    f"Predicate op 'field' arg 'name' must be string, got {type(name).__name__}",
                    f"{location}.name",
                )
            )
        if "body" not in pred:
            issues.append(_missing_pred_arg(op, "body", location))
        else:
            issues.extend(
                _validate_predicate(pred["body"], f"{location}.body", depth + 1)
            )
    elif op == "jaccard_ge":
        issues.extend(_require_list_arg(pred, op, "possible_sets", location))
        threshold = pred.get("threshold")
        if threshold is None:
            issues.append(_missing_pred_arg(op, "threshold", location))
        elif isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            issues.append(
                LintIssue(
                    "error",
                    "E073",
                    f"Predicate op 'jaccard_ge' arg 'threshold' must be number, got {type(threshold).__name__}",
                    f"{location}.threshold",
                )
            )
    elif op == "f1":
        issues.extend(_require_list_arg(pred, op, "expected", location))
    elif op == "jaccard":
        issues.extend(_require_list_arg(pred, op, "possible_sets", location))
    elif op == "weighted_label":
        table = pred.get("table")
        if table is None:
            issues.append(_missing_pred_arg(op, "table", location))
        elif not isinstance(table, dict):
            issues.append(
                LintIssue(
                    "error",
                    "E073",
                    f"Predicate op 'weighted_label' arg 'table' must be object, got {type(table).__name__}",
                    f"{location}.table",
                )
            )

    return issues


def _missing_pred_arg(op: str, key: str, location: str) -> LintIssue:
    return LintIssue(
        "error",
        "E072",
        f"Predicate op {op!r} requires arg {key!r}",
        location,
    )


def _require_list_arg(pred: dict, op: str, key: str, location: str) -> list[LintIssue]:
    if key not in pred:
        return [_missing_pred_arg(op, key, location)]
    if not isinstance(pred[key], list):
        return [
            LintIssue(
                "error",
                "E073",
                f"Predicate op {op!r} arg {key!r} must be list, got {type(pred[key]).__name__}",
                f"{location}.{key}",
            )
        ]
    return []


def _validate_jsonpath(path, location: str) -> list[LintIssue]:
    """Re-uses runtime resolver as syntax oracle."""
    if not isinstance(path, str):
        return [
            LintIssue(
                "error",
                "E075",
                f"jsonpath must be string, got {type(path).__name__}",
                location,
            )
        ]
    try:
        resolve_jsonpath({}, path)
    except ValueError as exc:
        return [
            LintIssue(
                "error",
                "E075",
                f"invalid jsonpath {path!r}: {exc}",
                location,
            )
        ]
    return []


def _validate_tolerances(config: dict, grader_path: str) -> list[LintIssue]:
    issues = []
    tolerances = config.get("tolerances")

    if tolerances is None:
        return issues

    if not isinstance(tolerances, dict):
        issues.append(
            LintIssue(
                "error",
                "E040",
                f"tolerances must be object, got {type(tolerances).__name__}",
                f"{grader_path}.config.tolerances",
            )
        )
        return issues

    for field_name, tol_config in tolerances.items():
        if not isinstance(tol_config, dict):
            issues.append(
                LintIssue(
                    "error",
                    "E041",
                    f"tolerance config must be object, got {type(tol_config).__name__}",
                    f"{grader_path}.config.tolerances.{field_name}",
                )
            )
            continue

        tol_type = tol_config.get("type")
        if tol_type is None:
            issues.append(
                LintIssue(
                    "error",
                    "E042",
                    "Missing tolerance type",
                    f"{grader_path}.config.tolerances.{field_name}.type",
                )
            )
        elif tol_type not in VALID_TOLERANCE_TYPES:
            issues.append(
                LintIssue(
                    "error",
                    "E043",
                    f"Invalid tolerance type: '{tol_type}'. Must be one of: {VALID_TOLERANCE_TYPES}",
                    f"{grader_path}.config.tolerances.{field_name}.type",
                )
            )

        has_value = "value" in tol_config
        has_lower = "lower" in tol_config
        has_upper = "upper" in tol_config

        if not has_value and not has_lower and not has_upper:
            issues.append(
                LintIssue(
                    "error",
                    "E044",
                    "Missing tolerance: need 'value' or 'lower'/'upper' for asymmetric",
                    f"{grader_path}.config.tolerances.{field_name}",
                )
            )
        elif has_value:
            tol_value = tol_config["value"]
            if not isinstance(tol_value, (int, float)):
                issues.append(
                    LintIssue(
                        "error",
                        "E045",
                        f"Tolerance value must be numeric, got {type(tol_value).__name__}",
                        f"{grader_path}.config.tolerances.{field_name}.value",
                    )
                )
        if has_lower and not isinstance(tol_config["lower"], (int, float)):
            issues.append(
                LintIssue(
                    "error",
                    "E046",
                    f"Tolerance lower must be numeric, got {type(tol_config['lower']).__name__}",
                    f"{grader_path}.config.tolerances.{field_name}.lower",
                )
            )
        if has_upper and not isinstance(tol_config["upper"], (int, float)):
            issues.append(
                LintIssue(
                    "error",
                    "E047",
                    f"Tolerance upper must be numeric, got {type(tol_config['upper']).__name__}",
                    f"{grader_path}.config.tolerances.{field_name}.upper",
                )
            )

    return issues


def _validate_ranges(config: dict, grader_path: str) -> list[LintIssue]:
    ranges = config.get("ranges")
    ground_truth = config.get("ground_truth", {})

    if ranges is None:
        return []

    if not isinstance(ranges, dict):
        return [
            LintIssue(
                "error",
                "E083",
                f"ranges must be object, got {type(ranges).__name__}",
                f"{grader_path}.config.ranges",
            )
        ]

    errors = []
    valid_intervals: dict[str, tuple[int | float, int | float]] = {}

    for field_name, range_config in ranges.items():
        if not isinstance(range_config, dict):
            errors.append(
                f"{field_name}: range config must be object, got {type(range_config).__name__}"
            )
            continue
        if "min" not in range_config or not isinstance(
            range_config["min"], (int, float)
        ):
            errors.append(
                f"{field_name}: range minimum must be numeric, got {type(range_config['min']).__name__}"
            )
            continue
        if "max" not in range_config or not isinstance(
            range_config["max"], (int, float)
        ):
            errors.append(
                f"{field_name}: range maximum must be numeric, got {type(range_config['max']).__name__}"
            )
            continue
        if range_config["min"] >= range_config["max"]:
            errors.append(
                f"{field_name}: range minimum must be less than maximum, got ({range_config['min']}, {range_config['max']})"
            )
            continue

        valid_intervals[field_name] = (range_config["min"], range_config["max"])

    if isinstance(ground_truth, dict):
        for field_name, expected_value in ground_truth.items():
            if field_name not in ranges:
                errors.append(f"{field_name}: missing range config")
                continue

            if not isinstance(expected_value, (int, float)):
                errors.append(
                    f"{field_name}: ground truth must be numeric, got {type(expected_value).__name__}"
                )
                continue

            interval = valid_intervals.get(field_name)
            if interval is None:
                continue

            minimum_value, maximum_value = interval
            if not minimum_value < expected_value < maximum_value:
                errors.append(
                    f"{field_name}: ground truth {expected_value} not in open interval "
                    f"({minimum_value}, {maximum_value})"
                )

    if not errors:
        return []

    return [
        LintIssue(
            "error",
            "E083",
            "Invalid numeric_range config: " + "; ".join(errors),
            f"{grader_path}.config.ranges",
        )
    ]


def validate_answer_fields_match(data: dict) -> list[LintIssue]:
    issues = []
    task = data.get("task", "")

    graders = _iter_graders(data)
    if not graders:
        return issues

    per_grader_fields: list[tuple[str, list[str]]] = []
    for location, grader in graders:
        grader_type = grader.get("type")
        config = grader.get("config", {})
        if not grader_type or grader_type not in GRADER_CONFIGS:
            continue
        if not isinstance(config, dict):
            continue
        grader_spec = GRADER_CONFIGS.get(grader_type, {})
        fields = _get_expected_answer_fields(grader_spec, config)
        per_grader_fields.append((location, fields))

    if len(per_grader_fields) > 1:
        field_owners: dict[str, list[str]] = {}
        for location, fields in per_grader_fields:
            for field in fields:
                field_owners.setdefault(field, []).append(location)

        for field, owners in field_owners.items():
            if len(owners) > 1:
                owner_list = ", ".join(owners)
                issues.append(
                    LintIssue(
                        "error",
                        "E051",
                        f"Duplicate answer field '{field}' declared by multiple graders "
                        f"({owner_list}). Each expected answer field must belong to exactly one grader.",
                        "graders",
                    )
                )

    expected_fields: set[str] = set()
    optional_fields: set[str] = set()
    for _, grader in graders:
        grader_type = grader.get("type")
        config = grader.get("config", {})
        if not grader_type or grader_type not in GRADER_CONFIGS:
            continue
        if not isinstance(config, dict):
            continue
        grader_spec = GRADER_CONFIGS.get(grader_type, {})
        expected_fields.update(_get_expected_answer_fields(grader_spec, config))
        optional_fields.update(grader_spec.get("answer_fields_optional", []))

    if not expected_fields:
        return issues

    task_fields = _extract_answer_fields_from_task(task)
    if not task_fields:
        return issues

    missing_in_task = (expected_fields - task_fields) - optional_fields
    extra_in_task = task_fields - expected_fields

    for field in missing_in_task:
        issues.append(
            LintIssue(
                "error",
                "E050",
                f"Grader expects answer field '{field}' but task <EVAL_ANSWER> does not include it",
                "task",
            )
        )

    grader_types = sorted(_collect_grader_types(data))
    grader_type_label = ", ".join(grader_types) if grader_types else "grader"
    for field in extra_in_task:
        issues.append(
            LintIssue(
                "warning",
                "W031",
                f"Task <EVAL_ANSWER> has field '{field}' not expected by {grader_type_label} grader",
                "task",
            )
        )

    return issues


def _iter_graders(data: dict) -> list[tuple[str, dict]]:
    results: list[tuple[str, dict]] = []

    grader = data.get("grader")
    if isinstance(grader, dict):
        results.append(("grader", grader))

    graders = data.get("graders")
    if isinstance(graders, list):
        for i, g in enumerate(graders):
            if isinstance(g, dict):
                results.append((f"graders[{i}]", g))

    return results


def _collect_grader_types(data: dict) -> set[str]:
    types: set[str] = set()
    for _, grader in _iter_graders(data):
        g_type = grader.get("type")
        if isinstance(g_type, str):
            types.add(g_type)
    return types


def _get_expected_answer_fields(grader_spec: dict, config: dict) -> list[str]:
    if "answer_fields" in grader_spec:
        return grader_spec["answer_fields"]

    if "answer_fields_from" in grader_spec:
        source_field = grader_spec["answer_fields_from"]
        source_data = config.get(source_field, {})
        if isinstance(source_data, dict):
            return list(source_data.keys())

    if "answer_field_from_config" in grader_spec:
        config_key = grader_spec["answer_field_from_config"]
        default = grader_spec.get("answer_field_default", "value")
        field_name = config.get(config_key, default)
        return [field_name]

    return []


def _extract_answer_fields_from_task(task: str) -> set[str]:
    match = re.search(r"<EVAL_ANSWER>\s*(\{[^}]+\})\s*</EVAL_ANSWER>", task, re.DOTALL)
    if not match:
        return set()

    json_template = match.group(1)
    field_matches = re.findall(r'"([^"]+)"\s*:', json_template)
    return set(field_matches)


def validate_unknown_fields(data: dict) -> list[LintIssue]:
    issues = []

    for field in data.keys():
        if field not in ALLOWED_TOP_LEVEL_FIELDS:
            issues.append(
                LintIssue(
                    "warning", "W020", f"Unknown top-level field: '{field}'", field
                )
            )

    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        for field in metadata.keys():
            if field not in ALLOWED_METADATA_FIELDS:
                issues.append(
                    LintIssue(
                        "warning",
                        "W021",
                        f"Unknown metadata field: '{field}'",
                        f"metadata.{field}",
                    )
                )

    grader = data.get("grader")
    if isinstance(grader, dict):
        issues.extend(_check_unknown_grader_fields(grader, "grader"))

    graders = data.get("graders")
    if isinstance(graders, list):
        for i, entry in enumerate(graders):
            if isinstance(entry, dict):
                issues.extend(_check_unknown_grader_fields(entry, f"graders[{i}]"))

    return issues


def _check_unknown_grader_fields(grader: dict, grader_path: str) -> list[LintIssue]:
    issues = []
    for field in grader.keys():
        if field not in ALLOWED_GRADER_FIELDS:
            issues.append(
                LintIssue(
                    "warning",
                    "W022",
                    f"Unknown grader field: '{field}'",
                    f"{grader_path}.{field}",
                )
            )
    return issues


ALL_VALIDATORS = [
    validate_required_fields,
    validate_metadata,
    validate_data_node,
    validate_task_answer_format,
    validate_grader,
    validate_graders,
    validate_answer_fields_match,
    validate_unknown_fields,
]
