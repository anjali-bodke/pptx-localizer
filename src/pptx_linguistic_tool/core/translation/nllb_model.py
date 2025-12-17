"""
nllb_model.py

Provides NLLB-200-based translation functionality using HuggingFace Transformers.
Includes logic to split input into sentence-aligned chunks for reliable long-text translation.
"""

import re
import torch
from transformers import NllbTokenizer, AutoModelForSeq2SeqLM

class NLLBTranslator:
    """
    Wrapper around the NLLB-200 model for translating text between supported languages.
    Automatically loads the tokenizer and model and moves it to the appropriate device (CUDA/CPU).
    """

    def __init__(
        self,
        source_lang: str = "deu_Latn",
        target_lang: str = "eng_Latn",
        model_name: str = "facebook/nllb-200-3.3B"
    ):
        """
        Initializes the translator with specified source/target languages and model.

        Args:
            source_lang (str): Source language code.
            target_lang (str): Target language code.
            model_name (str): HuggingFace model ID.
        """
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = NllbTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name).to(self.device)
        self.source_lang = source_lang
        self.target_lang = target_lang

    def _split_by_sentences(self, text: str, max_chars: int = 400) -> list[str]:
        """
        Splits text into ~400 character chunks using sentence boundaries.

        Args:
            text (str): The full input text.
            max_chars (int): Approximate max characters per chunk.

        Returns:
            list[str]: List of sentence-aligned chunks.
        """
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        chunks, current = [], ""

        for sentence in sentences:
            if len(current) + len(sentence) <= max_chars:
                current += " " + sentence if current else sentence
            else:
                chunks.append(current.strip())
                current = sentence

        if current:
            chunks.append(current.strip())

        return chunks

    def translate(self, text: str, max_chars: int = 400, log: callable = None) -> str:
        """
        Translates text using NLLB, chunked by sentence.

        Args:
            text (str): The input text to translate.
            max_chars (int): Max characters per chunk.
            log (callable): Optional logger function.

        Returns:
            str: Full translated text.
        """
        chunks = self._split_by_sentences(text, max_chars)
        results = []

        for idx, chunk in enumerate(chunks):
            if log:
                log(f"Translating chunk {idx + 1}/{len(chunks)}")

            self.tokenizer.src_lang = self.source_lang

            inputs = self.tokenizer(
                chunk,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512,
            ).to(self.device)

            generated_tokens = self.model.generate(
                **inputs,
                forced_bos_token_id=self.tokenizer.convert_tokens_to_ids(self.target_lang),
                max_length=1024,
                num_beams=5,
                early_stopping=True,
                no_repeat_ngram_size=3,
                length_penalty=1.05,
                repetition_penalty=1.1,
            )


            translated_text = self.tokenizer.batch_decode(generated_tokens, skip_special_tokens=True)[0]
            results.append(translated_text.strip())

        return "\n".join(results)