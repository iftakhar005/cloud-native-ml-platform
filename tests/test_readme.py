"""The README is the first thing a visitor reads, so it must not point at files that are not there
or quietly drop the statements that keep it honest."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_every_relative_link_points_at_a_file_or_folder_that_exists():
    targets = re.findall(r"\]\((?!https?://|#)([^)\s]+)\)", README)
    assert targets, "the README should link to the docs"
    for target in targets:
        assert (ROOT / target.split("#")[0]).exists(), f"README links to a missing path: {target}"


def test_every_docs_file_is_reachable_from_the_readme():
    for doc in sorted((ROOT / "docs").glob("*.md")):
        assert f"docs/{doc.name}" in README, f"{doc.name} is not linked from the README"


def test_the_readme_says_which_kubernetes_and_how_traffic_gets_in():
    for fact in ("Docker Desktop's built-in Kubernetes", "not Minikube", "single node",
                 "LoadBalancer", "localhost:8088", "ClusterIP"):
        assert fact in README, fact


def test_the_readme_keeps_its_honest_limits():
    for statement in ("A prototype, not a product", "synthetic addresses", "not real data",
                      "are tied", "No real-address evaluation"):
        assert statement in README, statement
