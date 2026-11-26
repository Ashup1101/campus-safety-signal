"""rag: build the index from the warehouse, ask one question (Gemini by default or OpenAI;
public incident data only), or eval a question file (one question per line, capped) for
faithfulness and citation correctness. Logs carry counts and scores; `ask` prints the answer
and its citations."""

import argparse
import logging
import os
import statistics
from collections.abc import Callable, Sequence
from pathlib import Path

from campus_safety.env import load_keys
from campus_safety.lake.storage import LakeConfigError, open_lake
from campus_safety.models import gates
from campus_safety.news import providers
from campus_safety.rag import index as rag_index
from campus_safety.rag import metrics
from campus_safety.rag.graph import Agent, Generate

log = logging.getLogger("rag")
WAREHOUSE = Path("data", "warehouse", "warehouse.duckdb")


def _t4() -> Callable[[str], bool] | None:
    """T4 from the lake when its newest run won; otherwise the rule checks alone."""
    try:
        return gates.text_gate(open_lake(os.environ.get("LAKE_URI")), "t4")
    except LakeConfigError:
        return None


def build(warehouse: Path, path: Path) -> int:
    n = rag_index.build(warehouse, path)
    log.info("%d documents indexed at %s", n, path)
    return 0


def ask(path: Path, question: str, generate: Generate) -> int:
    index = rag_index.Index(path)
    try:
        state = Agent(index, generate, screen=_t4()).ask(question)
    finally:
        index.close()
    print(state["answer"])
    for citation in state.get("citations", []):
        print(f"  - {citation}")
    scores = metrics.score(state["answer"], state.get("hits", []))
    log.info(
        "%d retrieved, %d problems on the last draft, faithfulness %.2f, citations %.2f",
        len(state.get("hits", [])),
        len(state.get("problems", [])),
        scores.faithfulness,
        scores.citation_correctness,
    )
    return 0


def evaluate(path: Path, questions: Path, generate: Generate, limit: int = 20) -> int:
    lines = [q.strip() for q in questions.read_text().splitlines() if q.strip()][:limit]
    index = rag_index.Index(path)
    faith, cite, refused, empty = [], [], 0, 0
    try:
        agent = Agent(index, generate, screen=_t4())
        for question in lines:
            state = agent.ask(question)
            if state.get("refused"):
                refused += 1
                continue
            if not state.get("hits"):
                empty += 1
                continue
            scores = metrics.score(state["answer"], state["hits"])
            faith.append(scores.faithfulness)
            cite.append(scores.citation_correctness)
    finally:
        index.close()
    log.info(
        "%d questions: %d refused, %d without matches, %d scored; faithfulness median %.2f,"
        " citation correctness median %.2f; %d model calls",
        len(lines),
        refused,
        empty,
        len(faith),
        statistics.median(faith) if faith else 0.0,
        statistics.median(cite) if cite else 0.0,
        agent.calls,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rag", description=__doc__)
    parser.add_argument("--index", type=Path, default=rag_index.INDEX)
    parser.add_argument("--provider", choices=providers.PROVIDERS, default="gemini")
    parser.add_argument("--model", default=None, help="default: the provider's pinned model")
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build", help="rebuild the index from the warehouse")
    build_parser.add_argument("--warehouse", type=Path, default=WAREHOUSE)
    ask_parser = commands.add_parser("ask", help="answer one question with citations")
    ask_parser.add_argument("question")
    eval_parser = commands.add_parser("eval", help="score a file of questions")
    eval_parser.add_argument("questions", type=Path)
    eval_parser.add_argument("--limit", type=int, default=20, help="most questions per run")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_keys()
    model = args.model or providers.default_model(args.provider)
    # Answers are prose with [n] citations, not JSON.
    generate = providers.generator(args.provider, model, json_mode=False)
    errors: tuple[type[Exception], ...] = (FileNotFoundError, *providers.ERRORS)
    try:
        if args.command == "build":
            return build(args.warehouse, args.index)
        if args.command == "ask":
            return ask(args.index, args.question, generate)
        return evaluate(args.index, args.questions, generate, args.limit)
    except errors as e:
        log.error("%s", e)
        return 1
