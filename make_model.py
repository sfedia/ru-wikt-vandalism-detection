from mistralai import Mistral
import os

TRAIN_FILE_NAME = "data/diffs_train.jsonl"
TEST_FILE_NAME = "data/diffs_test.jsonl"

my_model = "mistral-small-latest"

api_key = os.environ["MISTRAL_API_KEY"]

client = Mistral(api_key=api_key)

diffs_train = client.files.upload(file={
    "file_name": TRAIN_FILE_NAME,
    "content": open(TRAIN_FILE_NAME, "rb"),
})
diffs_test = client.files.upload(file={
    "file_name": TEST_FILE_NAME,
    "content": open(TEST_FILE_NAME, "rb"),
})

created_jobs = client.fine_tuning.jobs.create(
    model=my_model,
    training_files=[{"file_id": diffs_train.id, "weight": 1}],
    validation_files=[diffs_test.id],
    hyperparameters={
        "training_steps": 10,
        "learning_rate":0.0001
    },
    auto_start=False
)

client.fine_tuning.jobs.start(job_id = created_jobs.id)

created_jobs

