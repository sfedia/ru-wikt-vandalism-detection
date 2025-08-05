import asyncio
import csv
import typing as tp
from difflib import Differ
import aiohttp
import ssl
import certifi

from tqdm.asyncio import tqdm_asyncio
from tqdm import tqdm

import logging

import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RUWIKT_API: str = "https://ru.wiktionary.org/w/api.php"
CATEGORY_NAME = "Категория:Русский язык"
IP_REGEX = "^((25[0-5]|(2[0-4]|1\d|[1-9]|)\d)(\.(?!$)|$)){4}$"

class PageDiff:
    def __init__(self, json_diff):
        self.timestamp = json_diff["timestamp"]
        self.diff_author = json_diff["user"]
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

async def get_category_members(session: aiohttp.ClientSession, category_name: str) -> tp.List[str]:
    """Fetch all page titles in the given category."""
    print("Fetching category members...")
    members = []
    cmcontinue = None
    while True:
        params = {
            "action": "query",
            "format": "json",
            "list": "categorymembers",
            "cmtitle": category_name,
            "cmlimit": 500,
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue

        async with session.get(RUWIKT_API, params=params) as response:
            data = await response.json()
            if "query" not in data or "categorymembers" not in data["query"]:
                print(f"Unexpected response: {data}")
                break
            members.extend(page["title"] for page in data["query"]["categorymembers"])

            if "continue" in data:
                cmcontinue = data["continue"]["cmcontinue"]
            else:
                break
    print(f"Found {len(members)} category members.")
    return members

async def get_diffs_from_page(
    session: aiohttp.ClientSession, page_name: str, diff_computing_selector: tp.Callable
) -> DiffChain:
    """Fetch diffs for a given page."""
    print(f"Fetching diffs for page: {page_name}")
    params = {
        "action": "query",
        "format": "json",
        "prop": "revisions",
        "titles": page_name,
        "formatversion": 2,
        "rvprop": "flagged|flags|user|timestamp|size|ids|content|comment",
        "rvslots": "main",
        "rvlimit": 500,
    }
    async with session.get(RUWIKT_API, params=params) as response:
        result = DiffChain(diff_computing_selector)
        resp = await response.json()
        if "query" not in resp or "pages" not in resp["query"] or not resp["query"]["pages"]:
            print(f"Unexpected response for page {page_name}: {resp}")
            return result
        revisions = resp["query"]["pages"][0].get("revisions", [])
        result.extend([PageDiff(json_diff) for json_diff in revisions])
        print(f"Fetched {len(revisions)} revisions for page: {page_name}")
        return result

async def process_page(session, page_name, writer_lock):
    try:
        logger.info(f"Processing page: {page_name}")
        chain = await get_diffs_from_page(session, page_name, lambda diff: True)
        rows = []
        good_rows = []
        bad_rows = []
        for diff in chain.get(lambda d: True):
            rows.append({
                "page": page_name,
                "timestamp": diff.timestamp,
                "user": diff.diff_author,
                "size_delta": diff.str_size_delta(),
                "patrolled": diff.patrolled,
                "rollbacked": diff.rollbacked,
                "diff": "\n".join(dropout_neutral_lines(diff.diff)) if diff.diff else ""
            })
            if re.search(IP_REGEX,diff.diff_author):
                if diff.patrolled == True and len(good_rows)>100:
                    good_rows.append(row)
                elif row.rollbacked == True and len(bad_rows)>100:
                    bad_rows.append(row)
        logger.info(f"Processed {len(rows)} diffs for page: {page_name}")
        return [rows,good_rows,bad_rows]
    except Exception as e:
        logger.error(f"Error fetching diffs for page {page_name}: {e}")
        return []

async def main():
    print("Starting main function...")
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context)

    async with aiohttp.ClientSession(connector=connector) as session:
        pages = await get_category_members(session, CATEGORY_NAME)
        print(f"Found {len(pages)} pages in the category.")

        good_rows=[]
        bad_rows=[]

        with open("diffs.csv", "w", newline='', encoding="utf-8") as csvfile,open("diffs2.csv", "w", newline='', encoding="utf-8") as csvfile2:
            fieldnames = ["page", "timestamp", "user", "size_delta", "patrolled", "rollbacked", "diff"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer2 = csv.DictWriter(csvfile2, fieldnames=fieldnames)
            writer2.writeheader()

            tasks = [process_page(session, page_name, None) for page_name in pages]
            for result in tqdm_asyncio.as_completed(tasks, desc="Fetching pages", total=len(tasks)):
                outcome = await result
                print("#######\n")
                print(outcome)
                print("\n#######")
                rows = outcome[0]
                good_rows = outcome[1]
                bad_rows = outcome[2]
                for row in rows:
                    writer.writerow(row)
                rang = min(len(good_rows),len(bad_rows),100)
                for k in range(rang):
                    writer2.writerow(good_rows[k])
                    writer2.writerow(bad_rows[k])


        print("CSV writing completed.")

    


if __name__ == "__main__":
    asyncio.run(main())
