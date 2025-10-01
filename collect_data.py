import csv
from page_revs import get_diffs_from_page, dropout_neutral_lines, PAGES_TRAIN_CSV, PAGES_TEST_CSV
import asyncio
from tqdm.asyncio import tqdm
import ssl
import aiohttp
import certifi
import jsonlines
import random

TRAIN_FILE_NAME = "data/diffs_train.jsonl"
TEST_FILE_NAME = "data/diffs_test.jsonl"
CATEGORY_NAME = "Категория:Русский язык"
USER_AGENT = "ru-wikt-vandalism-bot/0.1 (https://github.com/sfedia/ru-wikt-vandalism-detection)"

async def parse(session, article_name):
    try:
        await asyncio.sleep(1 + random.random())
        result = await get_diffs_from_page(session, article_name, lambda diff: diff.rollbacked or diff.patrolled)
        good_diffs = []
        bad_diffs = []
        for rbk in result.get(lambda diff: diff.rollbacked or diff.patrolled):
            row = {
                "article": article_name,
                "author": rbk.diff_author,
                "revid": rbk.revid,
                "timestamp": rbk.timestamp,
                "minor": rbk.minor,
                "summary": rbk.summary,
                "diff": dropout_neutral_lines(rbk.diff) if rbk.diff else [],
                "size_delta": rbk.size_delta,
                "size": rbk.size,
            }
            if rbk.patrolled:
                good_diffs.append({"messages": [{"role":"editor","diff":row}, {"role": "admin", "good": True}]})
            else:
                bad_diffs.append({"messages": [{"role":"editor","diff":row}, {"role": "admin", "good": False}]})
        return good_diffs, bad_diffs
    except aiohttp.ClientResponseError as e:
        if e.status == 429:
            print(f"Rate limited for {article_name}. Retrying after 10 seconds...")
            await asyncio.sleep(10)
            return await parse(session, article_name)
        raise

async def make_dataset(session, csv_path, file_name):
    good_diffs = []
    bad_diffs = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        pages = [row["page_title"] for row in reader]

    semaphore = asyncio.Semaphore(10)  # Limit concurrency

    async def parse_with_semaphore(session, page):
        async with semaphore:
            try:
                return await parse(session, page)
            except KeyError:
                print(f"KeyError on page: {page}")
                return [], []
            except Exception as e:
                print(f"Error on page {page}: {e}")
                return [], []

    tasks = [parse_with_semaphore(session, page) for page in pages]
    results = await tqdm.gather(*tasks, desc=f"Parsing {csv_path}")

    for g, b in results:
        good_diffs.extend(g)
        bad_diffs.extend(b)

    with jsonlines.open(file_name, mode="w") as writer:
        for k in range(min(len(good_diffs), len(bad_diffs))):
            writer.write(good_diffs[k])
            writer.write(bad_diffs[k])

async def main():
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        await make_dataset(session, PAGES_TRAIN_CSV, TRAIN_FILE_NAME)
        await make_dataset(session, PAGES_TEST_CSV, TEST_FILE_NAME)

if __name__ == "__main__":
    asyncio.run(main())
