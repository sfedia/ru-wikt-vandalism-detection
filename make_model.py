import time
import vertexai
from vertexai.tuning import sft

"""
Use 
    gcloud auth application-default login
to authenticate
Run:
    conda activate vertex-tuning   
then
    python make_model.py
in terminal
"""

PROJECT_ID = "gen-lang-client-0717941928"
vertexai.init(project=PROJECT_ID, location="europe-west1")

tuning_job = sft.train(
    source_model='gemini-2.5-flash',
    train_dataset='gs://ru-wiktionary-diffs/diffs_train.jsonl',
    validation_dataset='gs://ru-wiktionary-diffs/diffs_val.jsonl',
    epochs=3,
    learning_rate_multiplier=1.0,
    tuned_model_display_name='edit-classifier',
)

while not tuning_job.has_ended:
    time.sleep(60)
    tuning_job.refresh()
    print("Tuning in progress...")

print("Tuned Model Name:", tuning_job.tuned_model_name)
print("Endpoint Name:", tuning_job.tuned_model_endpoint_name)
