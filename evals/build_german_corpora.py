#!/usr/bin/env python3
import build_ai_corpus_de
import build_human_corpus_de
import build_paragraph_corpus_de


def main() -> None:
    for module in (build_human_corpus_de, build_ai_corpus_de, build_paragraph_corpus_de):
        print(f"=== {module.__name__} ===")
        module.main()


if __name__ == "__main__":
    main()
