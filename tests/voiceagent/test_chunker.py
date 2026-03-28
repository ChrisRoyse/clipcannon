"""Tests for SentenceChunker."""
import pytest
from voiceagent.tts.chunker import SentenceChunker


@pytest.fixture
def chunker():
    return SentenceChunker()


def test_extract_simple_sentence(chunker):
    result = chunker.extract_sentence("This is a test. More text follows.")
    assert result == "This is a test."


def test_extract_question(chunker):
    result = chunker.extract_sentence("How are you doing today? I am fine.")
    assert result == "How are you doing today?"


def test_extract_exclamation(chunker):
    result = chunker.extract_sentence("What a great day it is! Let's go.")
    assert result == "What a great day it is!"


def test_newline_sentence_end(chunker):
    result = chunker.extract_sentence("This is a sentence.\nNew paragraph.")
    assert result == "This is a sentence."


def test_single_word_sentence_skipped(chunker):
    result = chunker.extract_sentence("Hello! ")
    assert result is None


def test_two_word_sentence_skipped(chunker):
    result = chunker.extract_sentence("Hi there! ")
    assert result is None


def test_three_word_sentence_extracted(chunker):
    result = chunker.extract_sentence("One two three. ")
    assert result == "One two three."


def test_prd_example_hello_how_are_you(chunker):
    buf = "Hello. How are you? "
    result = chunker.extract_sentence(buf)
    assert result == "Hello. How are you?"


def test_long_clause_at_comma(chunker):
    text = "This is a very long clause that keeps going on and on and exceeds sixty characters, and then continues"
    result = chunker.extract_sentence(text)
    assert result == "This is a very long clause that keeps going on and on and exceeds sixty characters,"


def test_long_clause_at_semicolon(chunker):
    text = "This is another very long clause that keeps going on and on past sixty characters; then more"
    result = chunker.extract_sentence(text)
    assert result == "This is another very long clause that keeps going on and on past sixty characters;"


def test_short_clause_not_extracted(chunker):
    result = chunker.extract_sentence("Short, text here")
    assert result is None


def test_empty_buffer_returns_none(chunker):
    assert chunker.extract_sentence("") is None


def test_no_punctuation_returns_none(chunker):
    assert chunker.extract_sentence("no punctuation here at all") is None


def test_only_punctuation_returns_none(chunker):
    assert chunker.extract_sentence("! ") is None


def test_multiple_sentences_extracts_first_valid(chunker):
    result = chunker.extract_sentence("I am good. You are too. Great!")
    assert result == "I am good."


def test_buffer_without_trailing_space(chunker):
    result = chunker.extract_sentence("This is a test.")
    assert result is None


def test_max_words_force_split(chunker):
    words = " ".join(f"word{i}" for i in range(60))
    result = chunker.extract_sentence(words)
    assert result is not None
    assert len(result.split()) == 50


def test_sentence_preferred_over_clause(chunker):
    text = "This is a sentence. This is a very long clause that goes on, with more"
    result = chunker.extract_sentence(text)
    assert result == "This is a sentence."


def test_buffer_not_modified(chunker):
    buf = "This is a test. More text."
    original = buf
    chunker.extract_sentence(buf)
    assert buf == original
