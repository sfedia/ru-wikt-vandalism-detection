"""
Get the revision chain of a given page, label edits patrolled / rollbacked, compute diffs for selected revisions
"""

import requests
import typing as tp
from difflib import Differ

RUWIKT_API: str = "https://ru.wiktionary.org/w/api.php"


class PageDiff:
    def __init__(self, json_diff):
        self.timestamp = json_diff["timestamp"]
        self.diff_author = json_diff["user"]
        self.patrolled = (
            "flagged" in json_diff
            and "tags" in json_diff["flagged"]
            and json_diff["flagged"]["tags"]["accuracy"] == 1
        )
        self.content = json_diff["slots"]["main"]["content"]
        self.diff = None
        self.rollbacked = False
        self.rollbacked_by = None
        self.size = json_diff["size"]
        self.size_delta = None

    def str_size_delta(self) -> str:
        if self.size_delta > 0:
            return f"+{self.size_delta}"
        else:
            return f"{self.size_delta}"

    def __repr__(self):
        return (
            f"<Diff {self.timestamp}, User {self.diff_author}, "
            f"Delta {self.str_size_delta()}{', Patrolled' if self.patrolled else ''}"
            f"{(f', Rollbacked by {self.rollbacked_by}') if self.rollbacked else ''}>"
        )


class DiffChain:
    def __init__(self, diff_computing_selector=lambda page_diff: False):
        self.diffs: tp.List[PageDiff] = []
        self.selector = diff_computing_selector

    def extend(self, new_diffs: tp.List[PageDiff]) -> None:
        self.diffs.extend(new_diffs)
        self.recompute_deltas()
        self.diff_based_rollback_marking()
        self.compute_diffs_for_filtered()

    def recompute_deltas(self) -> None:
        for i in range(len(self.diffs) - 1, -1, -1):
            if i == len(self.diffs) - 1:
                self.diffs[i].size_delta = self.diffs[i].size
            else:
                self.diffs[i].size_delta = self.diffs[i].size - self.diffs[i + 1].size

    def diff_based_rollback_marking(self) -> None:
        content = []
        rollbacked = []
        l = len(self.diffs)
        for i in range(len(self.diffs) - 1, -1, -1):
            content.append(self.diffs[i].content)
        for i in range(len(content)):
            for j in range(i - 1, -1, -1):
                if content[i] == content[j]:
                    for k in range(j + 1, i):
                        self.diffs[l - 1 - k].rollbacked = True
                        self.diffs[l - 1 - k].rollbacked_by = self.diffs[
                            l - 1 - i
                        ].diff_author
                    break

    def compute_diffs_for_filtered(self):
        differ = Differ()
        for i in range(len(self.diffs) - 1, -1, -1):
            if not self.selector(self.diffs[i]):
                continue
            if i == len(self.diffs) - 1:
                self.diffs[i].diff = list(
                    differ.compare([""], self.diffs[i].content.splitlines())
                )
            else:
                self.diffs[i].diff = list(
                    differ.compare(
                        self.diffs[i + 1].content.splitlines(),
                        self.diffs[i].content.splitlines(),
                    )
                )

    def get(self, filter: tp.Callable) -> tp.List[PageDiff]:
        return [diff for diff in self.diffs if filter(diff)]

    def get_by_author(self, author: str) -> tp.List[PageDiff]:
        return [diff for diff in self.diffs if diff.diff_author == author]


def dropout_neutral_lines(diff: tp.List[str]) -> tp.List[str]:
    return [line for line in diff if line.startswith("+ ") or line.startswith("- ")]


def get_diffs_from_page(
    page_name: str, diff_computing_selector: tp.Callable
) -> DiffChain:
    params = {
        "action": "query",
        "format": "json",
        "prop": "revisions",
        "titles": page_name,
        "formatversion": "2",
        "rvprop": "flagged|flags|user|timestamp|size|ids|content",
        "rvslots": "main",
        "rvlimit": "500",
        "wrappedhtml": "1",
    }
    response = requests.get(RUWIKT_API, params=params)
    result = DiffChain(diff_computing_selector)
    result.extend(
        [
            PageDiff(json_diff)
            for json_diff in response.json()["query"]["pages"][0]["revisions"]
        ]
    )
    return result


if __name__ == "__main__":
    chain = get_diffs_from_page("собака", lambda diff: diff.rollbacked)
    for rbk in chain.get(lambda diff: diff.rollbacked):
        print(rbk)
        print(dropout_neutral_lines(rbk.diff))
        print()
