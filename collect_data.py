import json

from page_revs import get_diffs_from_page, dropout_neutral_lines,get_category_members
import asyncio
from tqdm import tqdm
import csv
import os
import ssl
import re
import aiohttp
import certifi
from random import shuffle
import jsonlines

TRAIN_FILE_NAME = "data/diffs_train.jsonl"
TEST_FILE_NAME = "data/diffs_test.jsonl"
RUWIKT_API: str = "https://ru.wiktionary.org/w/api.php"
CATEGORY_NAME = "Категория:Русский язык"
#IP_REGEX = "^((25[0-5]|(2[0-4]|1\d|[1-9]|)\d)(\.(?!$)|$)){4}$"
USER_AGENT: str = "ru-wikt-vandalism-bot/0.1 (https://github.com/sfedia/ru-wikt-vandalism-detection)"
MAX_CONCURRENT_REQUESTS = 100

semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

async def parse(article_name):
    async with semaphore:
        result = await get_diffs_from_page(article_name, lambda diff: diff.rollbacked or diff.patrolled)
        good_diffs = []
        bad_diffs = []

        for rbk in result.get(lambda diff: (diff.rollbacked or diff.patrolled)):
            row = {
                "role": "editor",
                "content": [
                    {
                        "article": article_name,
                        "author": rbk.diff_author,
                        "revid": rbk.revid,
                        "timestamp": rbk.timestamp,
                        "minor": rbk.minor,
                        "summary": rbk.summary,
                        "diff": dropout_neutral_lines(rbk.diff),
                        "size_delta": rbk.size_delta,
                        "size": rbk.size
                    }
                ]
            }
            if rbk.patrolled:
                response = {
                    "role": "admin",
                    "good": True
                }
                thisDiff = {"messages":[row, response]}
                good_diffs.append(thisDiff)
            else:
                bad_diffs.append(row)
                response = {
                    "role": "admin",
                    "good": False
                }
                thisDiff = {"messages": [row, response]}
                bad_diffs.append(thisDiff)
        #pbar.update(1)
        return [good_diffs,bad_diffs]

async def make_dataset(pages,DATA_FILE_NAME):
    good_diffs = []
    bad_diffs = []
    tasks = [parse(page) for page in pages[:50000]]
    # Use tqdm to show progress while parsing each page
    for future in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Parsing pages", unit="page"):
        try:
            outcome = await future
            good_diffs.extend(outcome[0])
            bad_diffs.extend(outcome[1])
        except KeyError:
            print(future)
    with jsonlines.open(DATA_FILE_NAME, mode="w") as writer:
        print(len(good_diffs), len(bad_diffs))
        for k in range(min(len(good_diffs), len(bad_diffs))):
            writer.write(good_diffs[k])
            writer.write(bad_diffs[k])


async def main():
    print("Starting main function...")
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context)

    async with aiohttp.ClientSession(connector=connector, headers={"User-Agent": USER_AGENT}) as session:
        pages = await get_category_members(session, CATEGORY_NAME)
        print(f"Found {len(pages)} pages in the category.")


        shuffle(pages) # Randomizing the pages array so we can produce a training set
        await make_dataset(pages[:25000], TRAIN_FILE_NAME)  # making training dataset
        await make_dataset(pages[25000:35000], TEST_FILE_NAME)  # making testing dataset

if __name__ == "__main__":
    asyncio.run(main())