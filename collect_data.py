from page_revs import get_diffs_from_page, dropout_neutral_lines,get_category_members
import asyncio
from tqdm import tqdm
import csv
import os
import ssl
import re
import aiohttp
import certifi

DATA_FILE_NAME = "data/diffs.csv"
DIFF_FILE_NAME = "data/diffs2.csv"
RUWIKT_API: str = "https://ru.wiktionary.org/w/api.php"
CATEGORY_NAME = "Категория:Русский язык"
IP_REGEX = "^((25[0-5]|(2[0-4]|1\d|[1-9]|)\d)(\.(?!$)|$)){4}$"

async def parse(article_name):
    result = await get_diffs_from_page(article_name, lambda diff: diff.rollbacked or diff.patrolled)
    good_diffs = []
    bad_diffs = []
    
    for rbk in result.get(lambda diff: (diff.rollbacked or diff.patrolled)):
        if rbk.patrolled:
            row = {
                "article": article_name,
                "author": rbk.diff_author,
                "revid": rbk.revid,
                "timestamp": rbk.timestamp,
                "patrolled": rbk.patrolled,
                "patrolled_by": rbk.patrolled_by,
                "rollbacked": False,
                "rollbacked_by": "good diff",
                "minor": rbk.minor,
                "summary": rbk.summary,
                "diff": dropout_neutral_lines(rbk.diff),
                "size_delta": rbk.size_delta,
                "size": rbk.size
            }
            good_diffs.append(row)
        else:
            row = {
                "article": article_name,
                "author": rbk.diff_author,
                "revid": rbk.revid,
                "timestamp": rbk.timestamp,
                "patrolled": False,
                "patrolled_by": "bad diff",
                "rollbacked": rbk.rollbacked,
                "rollbacked_by": rbk.rollbacked_by,
                "minor": rbk.minor,
                "summary": rbk.summary,
                "diff": dropout_neutral_lines(rbk.diff),
                "size_delta": rbk.size_delta,
                "size": rbk.size
            }
            bad_diffs.append(row)
    #pbar.update(1)
    return [good_diffs,bad_diffs]


async def main():
    print("Starting main function...")
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context)

    async with aiohttp.ClientSession(connector=connector) as session:
        print(await parse("псина"))
        pages = await get_category_members(session, CATEGORY_NAME)
        print(f"Found {len(pages)} pages in the category.")

        good_diffs = []
        bad_diffs = []

        # Use tqdm to show progress while parsing each page
        for page in tqdm(pages[:25000], desc="Parsing pages", unit="page"):
            try:
                outcome = await parse(page)
                good_diffs.extend(outcome[0])
                bad_diffs.extend(outcome[1])
            except KeyError:
                print(page)
        file_exists = os.path.isfile(DATA_FILE_NAME)
        with open(DATA_FILE_NAME, mode="a", newline="", encoding="utf-8") as file:
            fieldnames = ["article","author","revid","timestamp","patrolled","patrolled_by","rollbacked","rollbacked_by","minor","summary","diff","size_delta","size"]
            writer=csv.DictWriter(file, fieldnames=fieldnames)
            if not file_exists:
                writer.writerow(fieldnames)
            print(len(good_diffs), len(bad_diffs))
            for k in range(min(len(good_diffs), len(bad_diffs))):
                #print(good_diffs[k])
                #print(bad_diffs[k])
                writer.writerow(good_diffs[k])
                writer.writerow(bad_diffs[k])



loop = asyncio.get_event_loop()
loop.run_until_complete(main())