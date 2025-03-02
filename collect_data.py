from page_revs import get_diffs_from_page, dropout_neutral_lines
import asyncio
from tqdm import tqdm
import csv
import os

DATA_FILE_NAME = "data/diffs.csv"

async def parse(article_name):
    result = await get_diffs_from_page(article_name, lambda diff: diff.rollbacked or diff.patrolled)
    file_exists = os.path.isfile(DATA_FILE_NAME)
    with open(DATA_FILE_NAME, mode="a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        header = ["author","revid","timestamp","patrolled","patrolled_by","rollbacked","rollbacked_by","minor","summary","diff","size_delta","size"]
        if not file_exists:
             writer.writerow(header)
        for rbk in result.get(lambda diff: diff.rollbacked or diff.patrolled):
            row = {
                "article": article_name,
                "author": rbk.diff_author,
                "revid": rbk.revid,
                "timestamp": rbk.timestamp,
                "patrolled": rbk.patrolled,
                "patrolled_by": rbk.patrolled_by,
                "rollbacked": rbk.rollbacked,
                "rollbacked_by": rbk.rollbacked_by,
                "minor": rbk.minor,
                "summary": rbk.summary,
                "diff": dropout_neutral_lines(rbk.diff),
                "size_delta": rbk.size_delta,
                "size": rbk.size
            }
            writer.writerow([row[k] for k in header])
    pbar.update(1)

async def main():
    global pbar
    articles = ["кошка", "собака", "что-то"] * 9
    total = len(articles)
    pbar = tqdm(total=total, desc="Parsing articles")

    await asyncio.gather(*[parse(article) for article in articles])

loop = asyncio.get_event_loop()
loop.run_until_complete(main())