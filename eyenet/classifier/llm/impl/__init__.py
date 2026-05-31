"""Concrete LLM provider backends. Selected via ``EYENET_LLM_PROVIDER``.

Never imported directly by production code — go through
:func:`eyenet.classifier.llm.factory.get_provider`, which lazily imports the one
selected backend so an unused (potentially heavy) provider never loads.
"""
