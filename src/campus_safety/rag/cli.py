"""rag: build the index from the warehouse, ask one question (Gemini, public incident data
only), or eval a question file (one question per line) for faithfulness and citation
correctness. Logs carry counts and scores; `ask` prints the answer and its citations."""

import argparse
import logging
import statistics
from collections.abc import Sequence
from pathlib import Path

from campus_safety.news import gemini
from campus_safety.rag import index as rag_index
from campus_safety.rag import metrics
from campus_safety.rag.graph import Agent, Generate

log = logging.getLogger("rag")
WAREHOUSE = Path("data", "warehouse", "warehouse.duckdb")


def build(warehouse: Path, path: Path) -> int:
    n = rag_index.build(warehouse, path)
    log.info("%d documents indexed at %s", n, path)
    return 0


def ask(path: Path, question: str, generate: Generate) -> int:
    index = rag_index.Index(path)
    try:
        state = Agent(index, generate).ask(question)
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


def evaluate(path: Path, questions: Path, generate: Generate) -> int:
    lines = [q.strip() for q in questions.read_text().splitlines() if q.strip()]
    index = rag_index.Index(path)
    faith, cite, refused, empty = [], [], 0, 0
    try:
        agent = Agent(index, generate)
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
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build", help="rebuild the index from the warehouse")
    build_parser.add_argument("--warehouse", type=Path, default=WAREHOUSE)
    ask_parser = commands.add_parser("ask", help="answer one question with citations")
    ask_parser.add_argument("question")
    eval_parser = commands.add_parser("eval", help="score a file of questions")
    eval_parser.add_argument("questions", type=Path)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.command == "build":
            return build(args.warehouse, args.index)
        if args.command == "ask":
            return ask(args.index, args.question, gemini.generate)
        return evaluate(args.index, args.questions, gemini.generate)
    except (FileNotFoundError, gemini.GeminiError) as e:
        log.error("%s", e)
        return 1
