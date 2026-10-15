# Evaluation: Vision-language models

Status: ✗ failed (depth 0, target subject). Prerequisites opened at depth 1.

## Q1
A vision-language model such as LLaVA can look at a photo and answer a question about it in text. In your own words, describe how such a model is built: what are its main components, how does information from the image reach the part of the model that writes the answer, and how is it trained?

**Answer:**

I'm not sure, but I assume that there is a neural network most likely based on CNN that is built using transformer architecture. The image features (RGB) are processed through the CNN to some numerical values which is then appended with the text input which finally predicts the next word? I'm assuming.

**Verdict:** ✗ Fail. The answer has the right outline: an image is turned into numbers, combined with the text, and the model predicts the next word. But it's guessed rather than understood. It confuses the image encoder (a CNN or ViT) with the transformer language model, and it doesn't mention the projector or how the model is trained.
