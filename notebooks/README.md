# P4 note: why there is no LSTM in v0.1

The served text model is TF-IDF (1-2 grams) plus logistic regression on the **pre-decision request sentence only**. Its test ROC-AUC on 2025 is 0.7476 (`eval/text_model_report.json`). An LSTM or GRU over the same sentences is optional for P4 and was not trained, for three reasons:

1. **Short inputs.** The request sentence is short (a median of 10 words) and mostly names the service or drug. A bag of n-grams captures that, and word order adds little.
2. **Training size.** About 32k training sentences (train + validation) is small for training a sequence model from scratch. A pretrained encoder would be the stronger step up, but it adds a heavy dependency to the Streamlit and Container Apps image.
3. **Leakage.** The full Findings text gives an AUC of 0.995 because it states the decision. Any sequence model trained on it would learn that leakage. That number is therefore reported only as a leakage upper bound.

A future experiment would be a bidirectional LSTM (embedding 128, hidden 64) on `request_text`, with the same time split (train ≤2023, validation 2024, test 2025), compared on ROC-AUC, Brier score and the subcategory-rate baseline.
