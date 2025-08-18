from mistralai import Mistral
import os
import jsonlines

my_model = "mistral-small-latest"

api_key = os.environ["MISTRAL_API_KEY"]

client = Mistral(api_key=api_key)

my_job = client.fine_tuning.jobs.list()[0]

def get_diff_response(diff):
    diff_response = client.chat.complete(
        model=my_job.fine_tuned_model,
        messages = [{"role":'user', "content":diff}]
    )
    return diff_response


if __name__ == "__main__":
    with jsonlines.open('diffs_to_test.jsonl') as reader, jsonlines.open('tested_diffs.jsonl', mode='w') as writer:
        for diff in reader:
            writer.write(get_diff_response(diff))



