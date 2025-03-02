from page_revs import RUWIKT_API
import requests
from tqdm import tqdm

PAGE_NAME_FILE = "data/pages.txt"

def api_get_pages(category_name, cmcontinue=None):
    req = requests.get(RUWIKT_API, {
        "action": "query",
        "format": "json",
        "list": "categorymembers",
        "formatversion": 2,
        "cmtitle": category_name,
        "cmlimit": 500,
        "cmcontinue": cmcontinue
    })
    resp = req.json()
    if resp["query"]["categorymembers"]:
        for pg in resp["query"]["categorymembers"]:
            with open(PAGE_NAME_FILE, "a") as file:
                file.write(pg["title"] + "\n")
                file.close()
        pbar.update(500)
        api_get_pages(category_name, resp["continue"]["cmcontinue"])
    else:
        pbar.update(500)

def get_category_size(category_name):
    req = requests.get(RUWIKT_API, {
      "action": "query",
      "format": "json",
      "prop": "categoryinfo",
      "titles": category_name,
      "formatversion": 2
    })
    resp = req.json()
    return resp["query"]["pages"][0]["categoryinfo"]["pages"]

def get_pages(category_name):
    global pbar
    size = get_category_size(category_name)
    pbar = tqdm(total=size, desc=f"Loading category {category_name}")
    api_get_pages(category_name)

if __name__ == "__main__":
    get_pages("Категория:Русский язык")