"""
Get the revision chain of a given page, label edits patrolled / rollbacked, compute diffs for selected revisions
"""

import typing as tp
from difflib import Differ
import aiohttp
import time
import asyncio
import csv
import os
import ssl

import certifi

CATEGORY_NAME = "Категория:Русский язык"
PAGES_TRAIN_CSV = "data/pages_train.csv"
PAGES_TEST_CSV = "data/pages_test.csv"
PAGES_VAL_CSV = "data/pages_val.csv"
RUWIKT_API: str = "https://ru.wiktionary.org/w/api.php"
USER_AGENT: str = "ru-wikt-vandalism-bot/0.1 (https://github.com/sfedia/ru-wikt-vandalism-detection)"


class PageDiff:
    def __init__(self, json_diff):
        self.timestamp = json_diff["timestamp"]
        self.diff_author = json_diff["user"]
        if not self.diff_author:
            self.diff_author = "Erased"
        self.patrolled = (
            "flagged" in json_diff
            and "tags" in json_diff["flagged"]
            and json_diff["flagged"]["tags"]["accuracy"] == 1
        )
        self.patrolled_by = None
        if self.patrolled:
            self.patrolled_by = json_diff["flagged"]["user"]
        self.revid = json_diff["revid"]
        self.minor = json_diff["minor"]
        self.summary = json_diff["comment"]
        self.content = json_diff["slots"]["main"]["content"]
        if not self.content:
            self.content = "Rollback or Content Erased"
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


async def get_diffs_from_page(
    session: aiohttp.ClientSession,
    page_name: str,
    diff_computing_selector: tp.Callable
) -> DiffChain:
    params = {
        "action": "query",
        "format": "json",
        "prop": "revisions",
        "titles": page_name,
        "formatversion": 2,
        "rvprop": "flagged|flags|user|timestamp|size|ids|content|comment",
        "rvslots": "main",
        "rvlimit": 500,
        "wrappedhtml": 1,
    }
    async with session.get(RUWIKT_API, params=params) as response:
        result = DiffChain(diff_computing_selector)
        resp = await response.json()
        result.extend(
            [
                PageDiff(json_diff)
                for json_diff in resp["query"]["pages"][0]["revisions"]
            ]
        )
        return result


async def get_category_members(session: aiohttp.ClientSession, category_name: str) -> tp.List[str]:
    """Fetch all page titles in the given category with retries, backoff, and progress timing."""
    print("Fetching category members...")
    members = []
    cmcontinue = None

    total_start = time.perf_counter()
    last_checkpoint = total_start

    while True: # do we need them ALL for training/testing?
        params = {
            "action": "query",
            "format": "json",
            "list": "categorymembers",
            "cmtitle": category_name,
            "cmlimit": 500,
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue

        # Retry loop
        for attempt in range(5):
            try:
                async with session.get(
                    RUWIKT_API,
                    params=params,
                    headers={"User-Agent": USER_AGENT},
                ) as response:
                    if response.status == 429:
                        wait_time = 2 ** attempt
                        print(f"Rate limited (429). Waiting {wait_time}s before retry...")
                        await asyncio.sleep(wait_time)
                        continue
                    response.raise_for_status()
                    data = await response.json()
                    break
            except aiohttp.ClientError as e:
                wait_time = 2 ** attempt
                print(f"Request failed ({e}). Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
        else:
            raise RuntimeError("Max retries exceeded while fetching category members")

        if "query" not in data or "categorymembers" not in data["query"]:
            print(f"Unexpected response: {data}")
            break

        members.extend(page["title"] for page in data["query"]["categorymembers"])

        if len(members) % 1000 == 0:
            now = time.perf_counter()
            batch_time = now - last_checkpoint
            total_time = now - total_start
            print(f"Processed {len(members)} pages "
                  f"(last 1000 took {batch_time:.2f}s, total {total_time:.2f}s)")
            last_checkpoint = now

        if "continue" in data:
            cmcontinue = data["continue"]["cmcontinue"]
        else:
            break

    total_time = time.perf_counter() - total_start
    print(f"Found {len(members)} category members in {total_time:.2f}s.")
    return members

async def export_category_pages_to_csv():
    """Fetch all pages in CATEGORY_NAME, shuffle, and save to two CSV files."""
    os.makedirs("data", exist_ok=True)
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        pages = await get_category_members(session, CATEGORY_NAME)
        print(f"Fetched {len(pages)} pages from category.")
        from random import shuffle
        shuffle(pages)
        with open(PAGES_TRAIN_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["page_title"])
            for page in pages[:25000]:
                writer.writerow([page])
        with open(PAGES_TEST_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["page_title"])
            for page in pages[25000:27500]:
                writer.writerow([page])
        with open(PAGES_VAL_CSV, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["page_title"])
                    for page in pages[27500:30000]:
                        writer.writerow([page])
        print(f"Exported 25000 pages to {PAGES_TRAIN_CSV} and 2500 pages to {PAGES_VAL_CSV} and 2500 pages to {PAGES_TEST_CSV}.")

if __name__ == "__main__":
    asyncio.run(export_category_pages_to_csv())