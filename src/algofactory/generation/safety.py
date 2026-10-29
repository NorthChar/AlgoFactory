"""Reject unsupported code before Docker; this is defense in depth, not a sandbox."""

import ast

from algofactory.workflow_models import WorkflowFailure

IMPORTS = {
    "sklearn.naive_bayes": {"MultinomialNB"},
    "sklearn.feature_extraction.text": {"TfidfVectorizer"},
    "sklearn.compose": {"ColumnTransformer"},
    "sklearn.impute": {"SimpleImputer"},
    "sklearn.linear_model": {"LogisticRegression", "Ridge"},
    "sklearn.pipeline": {"Pipeline"},
    "sklearn.preprocessing": {"OneHotEncoder", "StandardScaler"},
    "sklearn.svm": {"LinearSVC"},
}
NODES = (
    ast.Module,
    ast.ImportFrom,
    ast.alias,
    ast.FunctionDef,
    ast.arguments,
    ast.arg,
    ast.Assign,
    ast.Return,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Subscript,
    ast.keyword,
    ast.Expr,
)


def check_code(code: str):
    if len(code.encode()) > 32768:
        raise WorkflowFailure("code_size_exceeded")
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        raise WorkflowFailure("invalid_python") from None
    nodes = list(ast.walk(tree))
    if any(isinstance(node, ast.Import) for node in nodes):
        raise WorkflowFailure("unapproved_import")
    if len(nodes) > 1500 or any(not isinstance(node, NODES) for node in nodes):
        raise WorkflowFailure("unsafe_or_unsupported_syntax")
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if len(functions) != 1 or functions[0].name != "build_pipeline":
        raise WorkflowFailure("missing_build_pipeline")
    fn = functions[0]
    if (
        fn.decorator_list
        or fn.returns
        or fn.args.defaults
        or fn.args.kwonlyargs
        or fn.args.vararg
        or fn.args.kwarg
        or fn.args.posonlyargs
        or [a.arg for a in fn.args.args] != ["config"]
        or fn.args.args[0].annotation
    ):
        raise WorkflowFailure("invalid_factory_signature")
    constructors = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.level or node.module not in IMPORTS:
                raise WorkflowFailure("unapproved_import")
            for alias in node.names:
                if alias.asname or alias.name not in IMPORTS[node.module]:
                    raise WorkflowFailure("unapproved_import")
                constructors.add(alias.name)
        elif node is not fn and not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            raise WorkflowFailure("top_level_execution_rejected")
    for node in nodes:
        if isinstance(node, ast.ImportFrom) and node not in tree.body:
            raise WorkflowFailure("nested_import_rejected")
        if isinstance(node, ast.FunctionDef) and node is not fn:
            raise WorkflowFailure("nested_function_rejected")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise WorkflowFailure("private_access_rejected")
        if isinstance(node, ast.Call) and (
            not isinstance(node.func, ast.Name) or node.func.id not in constructors
        ):
            raise WorkflowFailure("unapproved_call")
        if isinstance(node, ast.Assign) and any(
            not isinstance(target, ast.Name) or target.id in constructors or target.id == "config"
            for target in node.targets
        ):
            raise WorkflowFailure("unsafe_assignment")
    if not any(isinstance(node, ast.Return) for node in fn.body):
        raise WorkflowFailure("factory_missing_return")
